# Hermes Meta-Skill Router — Integration Plan

Pre-implementation analysis. No production code, no package installs, no behavior change.

| Item | Value |
|---|---|
| Router design under review | this repository (`hermes-meta-skill-router`), commit `22e7430` |
| Hermes codebase inspected | `NousResearch/hermes-agent`, commit `2332a64` (2026-09-23), shallow read-only clone |
| Method | direct reads of the agent loop, tool registry, skills tooling, plugin surface, state DB, approval and logging modules; three parallel read-only surveys; counts measured with shell one-liners |
| Line references | `path:line` refer to the Hermes commit above unless the path starts with `references/` or `SKILL.md` (this repo) |

> **Implementation status.** The MVP in sections 8–9 is implemented as the plugin under
> `plugin/meta-skill-router/` with tests under `tests/` (run against the pinned Hermes commit by
> `.github/workflows/tests.yml`). Decisions U1, U2, U3 were taken as recommended: plugin-first,
> default mode `shadow`, upstream `pre_llm_call` kwarg proposed after the plugin exists. Two details
> changed during implementation and are reflected in the code and README: the retrieval admission
> rule uses "any distinctive query token" instead of Hermes' single rarest-token gate (which rejects
> multi-skill requests), and "explicit mention" promotion requires the user to name a skill *as a
> skill* (hyphenated/namespaced identifier, "use X", "the X skill", `/X`), not a bare word that
> happens to match a skill name.

---

## 1. Executive summary

- **Hermes has no router today.** Skill selection is the main model reading a `<available_skills>` block in the system prompt and calling `skill_view`. There is no lexical, semantic, or embedding index over skills, no eligibility scoring, no routing budget, and no routing trace. The prompt guidance actively tells the model to over-load ("err on the side of loading", `agent/prompt_builder.py:1379-1400`).
- **Three of the four assumed primitives exist under the assumed names**; the fourth does not. `skills_list` and `skill_view` exist (`tools/skills_tool.py:688-723`), `delegate_task` exists (`tools/delegate_tool.py:737-750`), but the todo primitive is a tool named `todo_list` backed by an in-memory `TodoStore` on the agent, not persisted state (`tools/todo_tool.py:26,280`). Their interfaces differ from the design's assumptions in ways listed in section 3.
- **The exact integration point is the per-turn prologue hook, not the agent core.** `pre_llm_call` fires once per turn before the first model call with the user message and history, and its return value is appended to the outgoing user message (`agent/turn_context.py:745-798`, `:1222-1236`). `pre_tool_call` can block or escalate a tool call (`agent/tool_executor.py:651-665`, `hermes_cli/plugins.py:1966`). `post_tool_call` carries `turn_id`, `tool_call_id`, `duration_ms`, and `status` (`model_tools.py:679-703`). Those three seams are the sanctioned "between intent and execution" boundary. The system prompt is byte-stable for the life of a conversation and is off limits (`AGENTS.md` invariants; `agent/AGENTS.md`).
- **Recommended shape: a Hermes plugin, not a core service.** Hermes' contribution rules rank a plugin far above a new core module or core tool (Footprint Ladder, root `AGENTS.md`), and "plugins never touch core" is a hard rule (`plugins/AGENTS.md`). Every MVP capability is reachable through `PluginContext`: hooks, `register_tool`, `ctx.llm.complete_structured`, `register_auxiliary_task`, `register_system_prompt_section`, `get_config`, and `plugin_data_dir`. One small additive core change is desirable later (section 13, U3) but not required.
- **Two architecture assumptions conflict hard with Hermes and must change.** (1) `skill.manifest.yaml` with mandatory security metadata would make 100% of real skills ineligible; none of 208 shipped skills has one. The catalog must be derived from SKILL.md frontmatter with the manifest as an optional overlay. (2) Full SKILL.md injection through the hook channel is spilled to disk above 10,000 characters (`tools/hook_output_spill.py:24`); the median shipped SKILL.md is 9,175 bytes and 94 of 208 exceed the cap. Loading must therefore stay on `skill_view`, and the router injects a compact directive.
- **MVP** = catalog compiled from frontmatter + BM25 shortlist (≤12) + one structured auxiliary LLM selection call + a directive injected via `pre_llm_call` + `skill_view` gating via `pre_tool_call` in active mode + one bounded reroute through a `skill_route` tool + JSONL traces. Three rollout modes (`shadow`, `advisory`, `active`). Default `shadow`, which adds zero bytes to any prompt.

---

## 2. Current-state architecture

### 2.1 Skill discovery

| Concern | Where | Notes |
|---|---|---|
| Skill roots | `agent/skill_utils.py:420` `get_all_skills_dirs()`; `:517` `get_project_skills_dirs()`; `:359` `get_external_skills_dirs()` | Order: trusted project dirs (`<git root>/.hermes/skills`, `<git root>/.agents/skills`, gated by `skills.trusted_project_dirs`) → `<HERMES_HOME>/skills` → `skills.create_dir` → `skills.external_dirs` (read-only) |
| Bundled skills | `skills/<category>/<name>/SKILL.md` (58 files); `optional-skills/` (150, inactive until installed) | Bundled skills are copied into `<HERMES_HOME>/skills` by `tools/skills_sync.py` and tracked in `.bundled_manifest` (md5). Not read in place. |
| Plugin skills | `hermes_cli/plugins.py:993` `register_skill(name, path, description, frontmatter)`; listed by `list_plugin_skill_metadata()` `:1529` | Namespaced `plugin:name`. Appear in `skills_list` but **not** in the system prompt index (docstring `:997-1000`). |
| Org mirror | `agent/skill_utils.py:33-70`, `:783-800` | `<skills>/_org/<org_id>/`, token-gated by `.active_org`. |
| Walker | `agent/skill_utils.py:783` `iter_skill_index_files(skills_dir, filename)` | Sorted `os.walk`, follows symlinks, prunes `EXCLUDED_SKILL_DIRS` (`:23`) and support dirs (`references templates assets scripts`, `:31`). |
| Project quarantine | `agent/skill_utils.py:555` `is_quarantined_project_skill`, `:581` `iter_project_skill_files` | Runs `tools/skills_guard.scan_skill_cached`; a `dangerous` verdict hides the skill; fails closed. |
| Frontmatter parser | `agent/skill_utils.py:105` `parse_frontmatter(content) -> (dict, body)` | YAML via CSafeLoader; falls back to naive `key: value` lines; `{}` on failure. |
| Frontmatter fields in use | measured over 61 bundled SKILL.md files | `name` 61, `description` 61, `version` 60, `platforms` 59, `license` 59, `author` 59, `metadata` 57 (`metadata.hermes.tags`, `related_skills`, `config`, `requires_tools`, `requires_toolsets`, `fallback_for_*`, `session_platforms`), `prerequisites` 12 (`env_vars`, `commands`), `triggers` 2, `tags` 2, `required_credential_files` 1. No file carries `skill.manifest.yaml`. |
| Conditional visibility | `agent/skill_utils.py:657-663` `extract_skill_conditions`; `agent/prompt_builder.py:1229` `_skill_should_show` | Visibility only. Not an execution permission. |
| Disable lists | `agent/skill_utils.py:300` `get_disabled_skill_names(platform)`; config `skills.disabled`, `skills.platform_disabled.<platform>` | `ESSENTIAL_SKILLS = {"hermes-agent"}` cannot be disabled (`:297`). |
| Hub index cache | `<HERMES_HOME>/skills/.hub/index-cache/`, `lock.json` (`tools/skills_hub.py:295-330`) | `lock.json` records `content_hash`, `trust_level`, `scan_verdict` per installed skill. |
| Repo `skills/index-cache/` | website build fallback only (`website/scripts/extract-skills.py`) | Never read at runtime. |

There are **three independent index paths**, each re-parsing frontmatter:

1. **System prompt index** — `agent/prompt_builder.py:1262` `build_skills_system_prompt(...)` → `:1411` `_build_skills_system_prompt_inner` → `:1346` `_render_skills_index`. Two-layer cache: in-process LRU of 32 (`:1118`) and a disk snapshot `<HERMES_HOME>/.skills_prompt_snapshot.json` v3 validated by a file-signature manifest (`:1140`). Descriptions are cut to **60 characters** (`agent/skill_utils.py:763-775`). Entries are never dropped; coding "focus" posture demotes categories to names-only (`agent/coding_context.py:409`). Rendered under `## Skills` with the guidance "you MUST load it with skill_view(name) … Err on the side of loading" (`:1379-1400`); one-shot sessions get the opposite guidance (`agent/oneshot_footprint.py:42`).
2. **`skills_list` tool** — `tools/skills_tool.py:180` `_find_all_skills` (30 s TTL, mtime signature `:40`), `:224` `skills_list(category, task_id)`. Reads the first 4,000 bytes of each SKILL.md; description up to **1,024 characters** (`tools/skills_tool_plugin.py:16`).
3. **Slash commands** — `agent/skill_commands.py:391` `scan_skill_commands()`; `/skill-name` per skill.

No path performs lexical or semantic retrieval. The only reusable ranking engine in the tree is the BM25 + Snowball-stemmer search over deferred tools in `tools/tool_search_catalog.py:102-215` (`build_catalog`, `search_catalog`); `snowballstemmer` is already a core dependency (`pyproject.toml`). There is no embedding-provider abstraction in core.

### 2.2 Skill loading

| Concern | Where | Notes |
|---|---|---|
| Model-driven load | `tools/skills_tool.py:573` `skill_view(name, file_path=None, task_id=None, preprocess=True) -> str` | Resolves bare name, `category/name`, `plugin:name`; refuses ambiguous collisions (`:520-536`); refuses quarantined project skills (`:540-548`); platform/disabled checks (`:617-621`); readiness: required env vars are captured interactively and registered for sandbox passthrough (`:445-498`); `${HERMES_SKILL_DIR}` templating and (off by default) inline shell (`agent/skill_preprocessing.py:99`); org provenance header (`:414-441`). Returns JSON with `content`, `tags`, `related_skills`, `linked_files`, `metadata`, readiness fields, `_source_path`. |
| Repeat-view dedup | `tools/skills_tool.py:699` `_skill_view_with_bump`; `tools/skills_tool_dedup.py` | Same unchanged file viewed twice in a task returns a stub; usage counters bumped via `tools/skill_usage.py` `bump_view`/`bump_use`. |
| Explicit pins | CLI `cli.py:1279` `_run_skill_slash_command`; gateway `gateway/run_inbound.py:1140` `_hm_skill_slash_rewrite`; builder `agent/skill_commands.py:504` `build_skill_invocation_message` | Injects the full skill as a **user message** starting with `[IMPORTANT: The user has invoked the "<name>" skill …]` (`:31-37` markers). Stacked `/a /b` up to 5 skills (`:521`). |
| Session pins | `skills.auto_load` → `agent/skill_commands.py:653` `build_auto_load_prompt`; placed in the stable prompt tier (`agent/system_prompt.py:316-339`) | Resolved once per agent; never re-rendered. |
| Bundles | `agent/skill_bundles.py` | YAML aliases under `<HERMES_HOME>/skill-bundles/`. |
| Content limits | `MAX_NAME_LENGTH = 64`, `MAX_DESCRIPTION_LENGTH = 1024` (`tools/skills_tool_plugin.py:15-16`); agent-written skills capped at 100k chars | Measured shipped SKILL.md bytes: min 1,549 / p50 9,175 / p90 16,705 / max 72,164; 94 of 208 exceed 10,000. |

### 2.3 Orchestration

| Concern | Where | Notes |
|---|---|---|
| Agent facade | `run_agent.py:230` `class AIAgent(...)`; construction `agent/agent_init.py:2318` `init_agent(...)` | ~60 kwargs; relevant: `enabled_toolsets`, `disabled_toolsets`, `platform`, `session_db`, `skip_context_files`, `skip_memory`, `iteration_budget`. |
| Turn entry | `agent/turn_facade.py:22` `run_conversation(...)` → `agent/conversation_loop.py:1594` `run_conversation` → `:1437` `_run_conversation_turn` | Synchronous. |
| Turn prologue | `agent/turn_context.py:980` `build_turn_context`; `:1078` restore/build system prompt; `:1114` `_collect_pre_llm_call_context` | `pre_llm_call` fires here once per turn with `session_id, task_id, turn_id, user_message, conversation_history, is_first_turn, model, platform, parent_session_id, sender_id` (`:757-769`). Returned `{"context": str}` or `str` is appended to the outgoing user message at API time (`:93-104` `compose_user_api_content`, `:1222-1236`), stored in the `api_content` sidecar so retries and replays send identical bytes. Per-hook context above `hooks.output_spill.max_chars` (default 10,000) is spilled to `<HERMES_HOME>/hook_outputs/<session>/` and replaced by a preview (`tools/hook_output_spill.py:24-116`). |
| Iteration loop | `agent/conversation_loop.py:1535` `while (api_call_count < agent.max_iterations and agent.iteration_budget.remaining > 0) or agent._budget_grace_call:` | Phases live in `agent/turn_*.py`; tool rounds in `agent/turn_tool_round.py:46`. |
| System prompt tiers | `agent/system_prompt.py:659` `build_system_prompt_parts` | `stable` (identity, guidance, pinned skills, coding brief) → `context` (caller `system_message`, AGENTS.md files) → `volatile` (skills index first `:708`, memory, plugin sections at `after_memory` `:711`, timestamp). Persisted per session (`hermes_state_sessions.py:654` `update_system_prompt`) and restored verbatim on later turns (`agent/conversation_loop.py:659-790`). |
| Plugin prompt sections | `hermes_cli/plugins.py:936` `register_system_prompt_section(id, content, *, position="after_memory", max_chars=...)` | Only position is `after_memory`; ≤4,000 chars; frozen into the session prompt. |
| Delegation | `tools/delegate_tool.py:530` `delegate_task(goal, context, tasks, ..., parent_agent, ...)`; `run_agent.py:1350` `_dispatch_delegate_task` | Model-facing schema is `tasks[{goal, context, output_schema, images, group}]` plus `action` list/steer/stop (`:660-735`). Top-level delegations always run in the background and results re-enter as a new message; orchestrator children (depth > 0) are synchronous. Children: fresh `AIAgent` with `platform="subagent"`, `skip_context_files=True`, `skip_memory=True`, toolsets inherited minus `DELEGATE_BLOCKED_TOOLS = {delegate_task, clarify, memory, send_message, cronjob_manage}` (`tools/delegate_tool_toolsets.py:14`). `output_schema` is validated with one bounded correction retry (`tools/delegation_output_schema.py`). `delegation.max_iterations` in config is authoritative. |
| Skill creation nudge | `agent/turn_finalizer.py:675-701`; interval `skills.creation_nudge_interval` (`agent/agent_init.py:1342`) | Spawns a background review fork; not a routing mechanism. |
| Hook fire order per turn | `on_session_start` (first build) → `pre_llm_call` → [`pre_api_request` → model → `post_api_request` → tool round: `pre_tool_call` → dispatch → `post_tool_call` → `transform_tool_result`]* → `pre_verify` (coding turns) → `transform_llm_output` → `post_llm_call` → `on_session_end` (end of **every** turn, `agent/turn_finalizer.py:708-720`) | `on_skill_lifecycle` fires from `tools/skill_usage.py:473` on skill state changes. |
| Hook registry | `hermes_cli/plugins.py:108` `VALID_HOOKS`; dispatch `hermes_cli/lifecycle.py:26` `invoke_hook(hook_name, **kwargs)` | Callbacks are signature-inspected; unknown kwargs are dropped, so callbacks should accept `**kwargs`. |
| Middleware | `hermes_cli/middleware.py:24` `VALID_MIDDLEWARE = {tool_request, tool_execution, llm_request, llm_execution}` | Behavior-changing wrappers; heavier than hooks. |

### 2.4 Tool execution

| Concern | Where | Notes |
|---|---|---|
| Registry | `tools/registry.py:655` `register(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False, description="", emoji="", max_result_size_chars=None, dynamic_schema_overrides=None, override=False, scope=None)`; `:880` `dispatch(name, args, *, scope=None, **kwargs)` | Handlers are `lambda args, **kw` and return a JSON string; `dispatch` passes only the kwargs the handler accepts (`task_id`, `session_id`, `parent_agent`, `store`, …). A tool is exposed only if a toolset names it (`toolsets.py`; `tools/AGENTS.md`). |
| Plugin tools | `hermes_cli/plugins.py:456` `register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False, description="", emoji="", override=False)` | Plugin toolsets are discovered automatically (`toolsets.py:411`) and enabled per platform (`hermes_cli/tools_config.py:605`). |
| Dispatch | `model_tools.py:872` `handle_function_call(function_name, function_args, task_id=None, tool_call_id=None, session_id=None, turn_id=None, api_request_id=None, user_task=None, enabled_tools=None, ...)` | Order: arg coercion → alias map → tool-search bridge → `tool_request` middleware → `_AGENT_LOOP_TOOLS` rejection (`todo_list, memory, session_search, delegate_task` at `:612`) → `pre_tool_call` + ACP edit approval → `tool_execution` middleware → `registry.dispatch` → `post_tool_call` → `transform_tool_result`. |
| Agent-level tools | `agent/inline_tool_executors.py:235-280` `INLINE_TOOL_EXECUTORS` | `todo_list`, `memory`, `session_search`, `clarify`, `delegate_task`, desktop tools. Bypass the registry because they need live agent state. |
| `pre_tool_call` contract | `hermes_cli/plugins.py:1966` `_dispatch_pre_tool_call_hooks(tool_name, args, **hook_kwargs) -> (block_message, modified_args)` | Return `{"action": "block", "message"}` to veto, `{"action": "approve", "message", "rule_key"?}` to escalate to the human gate (`tools/approval.py:1095` `request_tool_approval`), `{"action": "modify", ...}` to rewrite args. Block wins over approve. |
| `post_tool_call` payload | `model_tools.py:679-703` | `tool_name, args, result, task_id, session_id, tool_call_id, turn_id, api_request_id, duration_ms, status, error_type, error_message, middleware_trace`. |
| Budgets / timeouts | `tools/budget_config.py:44` (result-size limits: 100k per result, 200k per turn); `agent/tool_executor.py:180,807` (batch 420 s, sequential call timeout) | Not per-skill. |
| Auxiliary LLM | `agent/auxiliary_client.py:7786` `call_llm(task=None, *, provider, model, base_url, api_key, main_runtime, messages, temperature, max_tokens, tools, timeout, extra_body, ...)`; plugin facade `agent/plugin_llm.py:446` `PluginLlm.complete(...)`, `:460` `complete_structured(*, instructions, input, json_schema=None, json_mode=False, ...)` | Per-task routing via `auxiliary.<task>` config; plugins add keys with `register_auxiliary_task` (`hermes_cli/plugins.py:863`). Structured output is `response_format` with a rejection-retry ladder; there is no separate helper named `auxiliary_structured_output`. Existing small classifier precedent: `tools/approval_smart.py:109` (`call_llm(task="approval", temperature=0, max_tokens=16)`). |

### 2.5 Permissions

| Concern | Where | Notes |
|---|---|---|
| Approval mode | `hermes_cli/approval_mode.py:16` `manual | smart | off`; default `smart` (`hermes_cli/config_defaults.py:1638-1676`) | Effective mode `tools/approval_context.py:228`; bypasses `HERMES_YOLO_MODE`, per-session `/yolo`, `mode: off`. |
| Shell gate | `tools/approval.py:1159` `check_all_command_guards(command, env_type, approval_callback=None, has_host_access=False) -> dict` | Floors (`tools/approval_floors.py`: hardline patterns, `approvals.deny`, sudo-stdin) run before any bypass; `command_allowlist` for permanent approvals; smart mode uses a guardian LLM (`tools/approval_smart.py:74`). |
| Other gates | `check_execute_code_guard` (`tools/approval.py:1233`); file-write guards (`tools/file_tools_write_guards.py`); `request_tool_approval` (`tools/approval.py:1095`); `_run_approval_gate` (`:951`) | Approval memory is per session key plus `command_allowlist` (`:249,:366,:448`). |
| Skill trust | `tools/skills_guard.py:23-32` `TRUSTED_REPOS`, `INSTALL_POLICY` (builtin/trusted/community/agent-created × safe/caution/dangerous); `:821` `_resolve_trust_level(source)`; `:670` `scan_skill_cached`; `:664` `content_hash`, `:849` `full_content_hash` | Trust is decided at **install** time (hub) and at **scan** time (project skills). Loading an installed skill is not gated at all. |
| Skill write gate | `tools/write_approval.py:170` `evaluate_gate`; `skills.write_approval`, `skills.guard_agent_created` | Applies to `skill_manage` writes, not loads. |
| Provenance labels | `tools/skill_usage.py:452` `telemetry_provenance` → `installed | agent_created | external | local | unknown` | Sidecar `<skills>/.usage.json` holds `view_count`, `use_count`, timestamps — no success/failure signal. |
| Per-skill permission scope | none | Skills carry no permission metadata; `metadata.hermes.requires_tools` only hides the index entry. All side effects run as the main model's tool calls under the gates above. |

### 2.6 Task state

| Concern | Where | Notes |
|---|---|---|
| Session DB | `hermes_state.py:443` `class SessionDB(...)`; file `<HERMES_HOME>/state.db` (SQLite WAL), schema v30 (`hermes_state_common.py:239,328-581`) | Tables: `sessions` (~60 columns incl. `system_prompt_hash`, `model_config` JSON, `tool_names`), `messages`, `session_model_usage`, `state_meta` (global KV: `get_meta`/`set_meta`/`list_meta_prefix` at `hermes_state.py:1557-1597`), `async_delegations`, FTS5 tables. No generic task table. |
| Todo | `tools/todo_tool.py:26` `TodoStore` (in-memory, one per agent, `agent/agent_init.py:1181`); tool `todo_list` in toolset `todo` (`:280`); `run_agent.py:1045` `_hydrate_todo_store(history)` | Survives only by riding tool results in message history; re-injected after compression (`format_for_injection`, `:97`). |
| IDs | `session_id` = `hermes_state_ids.new_session_id()`; `task_id` = per-turn uuid (`agent/turn_context.py:544`); `turn_id = "{session_id}:{task_id}:{hex8}"` (`:547`) | All three are in the hook payloads. Gateway builds a fresh `AIAgent` per message. |
| Checkpoints | `tools/checkpoint_manager.py:593` | Filesystem snapshots for `/rollback`; unrelated to routing state. |
| Plugin storage | `plugins/plugin_storage.py:27` `plugin_data_dir(name) -> Path`, `:36` `plugin_db(name)` | `<HERMES_HOME>/plugin-data/<name>/`, profile-aware. Sanctioned place for plugin state. |

### 2.7 Logging

| Concern | Where | Notes |
|---|---|---|
| Process logs | `hermes_logging.py:203` `setup_logging(...)` → `<HERMES_HOME>/logs/agent.log`, `errors.log`, `gateway.log` | Plain text, rotating, `RedactingFormatter`; no JSON option. |
| Redaction | `agent/redact.py:862` `redact_sensitive_text(text, *, force=False, code_file=False, ...)`; `:1133` `redact_for_egress`; plugins can add patterns via `register_redaction_patterns` | Reusable for trace files. |
| Trajectories | `agent/trajectory.py:37` `save_trajectory(...)` | Opt-in; JSONL written **relative to the process cwd**. Not a trace sink. |
| Existing structured records | skill hub `audit.log`; curator ledger `<skills>/.curator_ledger.jsonl` (`tools/skill_ledger.py`); MoA traces `<HERMES_HOME>/moa-traces/<session>.jsonl`; dashboard auth JSONL | Precedent for per-feature JSONL under `HERMES_HOME`. |
| Per-tool telemetry | `post_tool_call` payload (2.4); log lines `agent/tool_executor.py:1055-1057` | Correlate on `turn_id`/`tool_call_id`. |
| Outbound telemetry | `hermes_cli/observability/` relay shared metrics (opt-in), Langfuse plugin (opt-in), `agent/monitoring/` OTLP (content-free) | Root `AGENTS.md`: no outbound telemetry without an explicit opt-in gate. Router traces must stay local. |

---

## 3. Verification of assumed primitives

| Assumed | Verified name | Registration | Model-facing interface | Behavior that differs from the design's assumptions |
|---|---|---|---|---|
| `skills_list` | `skills_list` (toolset `skills`) | `tools/skills_tool.py:688-691`; handler `skills_list(category=None, task_id=None) -> str` (`:224`) | params `{category?}`; returns `{success, skills:[{name, description, category}], categories, count, hint}` | Name + description (≤1,024 chars) + category only. No tags, triggers, requirements, version, or query filter. Plugin skills appended with `category: "plugin"`. Disabled and platform-incompatible skills omitted. 30 s cache keyed on directory mtimes. |
| `skill_view` | `skill_view` (toolset `skills`) | `:721-723`; handler `_skill_view_with_bump` → `skill_view(name, file_path=None, task_id=None, preprocess=True)` (`:573`) | params `{name, file_path?}`; returns JSON with `content`, `tags`, `related_skills`, `linked_files`, `metadata`, readiness fields | Side effects: interactive secret capture for `required_environment_variables`, env passthrough registration, usage counters, repeat-view stub, security warnings (log only). Explicit loads of platform-incompatible or disabled skills return an error. This is the only path that applies templating, inline shell, and org provenance. |
| `delegate_task` | `delegate_task` (toolset `delegation`) | `tools/delegate_tool.py:737-750`; python `delegate_task(goal=None, context=None, tasks=None, max_iterations=None, role=None, background=None, output_schema=None, images=None, action=None, subagent_id=None, message=None, parent_agent=None, credentials_cfg=None) -> str` (`:530`) | `tasks[{goal, context, output_schema?, images?, group?}]`, `action` | Requires a live `parent_agent`; dispatched inline by the agent loop (`agent/inline_tool_executors.py:279`, `run_agent.py:1350`), so a plugin hook cannot invoke it directly (`ctx.dispatch_tool` resolves a parent agent only in CLI mode, `hermes_cli/plugins.py:688`). Top-level calls always run in the background and results re-enter as a **new message**, so a router cannot run a synchronous DAG inside one turn. `output_schema` gives JSON-schema-validated child output with one retry — the nearest existing "typed artifact". |
| todo / task state | tool `todo_list` (toolset `todo`), class `TodoStore` | `tools/todo_tool.py:280`; `todo_tool(todos=None, merge=False, store=None)` (`:191`) | `{todos:[{id, content, status, parent?}], merge?}`; returns `{todos, revision, summary}` | No tool named `todo`. State is in-memory per agent, rebuilt from history on resume, not in the session DB, and not passed to hooks. A hook can recover it by reading the latest `todo_list` tool result in `conversation_history` (the same rule `_hydrate_todo_store` uses). |

Also checked: there is no `$skill` mention syntax, and `agents/openai.yaml` in this repo is not read by Hermes. `send_message` is not a registered tool (`tools/send_message_tool.py:22-24`).

---

## 4. Gap analysis

| Router component (`references/architecture.md`) | Hermes today | Gap | Severity |
|---|---|---|---|
| Discovery service | Three walkers (2.1) share `skill_utils` primitives; plugin skills excluded from the prompt index | No unified catalog object; must aggregate local + project + external + plugin sources ourselves | Medium |
| Catalog compiler / `SkillManifest` | Frontmatter only; descriptions truncated to 60 chars in the prompt; digests only for hub installs (`lock.json content_hash`) and bundled md5 | New: frontmatter → manifest adapter, per-skill content digest (`tools/skills_guard.content_hash` reusable), incremental rebuild keyed on directory signature | High (core of MVP) |
| Candidate retriever | None; model scans the whole index | New: BM25 over name/description/tags/triggers/category; embeddings deferred (no provider abstraction, no new deps) | High |
| Selection planner (structured LLM) | None for skills; precedent for small aux classifiers and `ctx.llm.complete_structured` | New prompt + JSON schema; deterministic post-validation | High |
| Execution supervisor | The agent loop, approval gates, and hooks already are the supervisor | Replace the concept: the router never executes; it injects a directive and gates `skill_view` | Design change |
| Typed artifact envelopes / DAG | No artifact store; skills are documents, not functions | Defer to V2; nearest primitive is `delegate_task.output_schema` | Out of MVP |
| Evaluator + recursive router | No completion assessment; `pre_verify` is coding-only; mid-turn injection only via tool results | MVP: one bounded reroute through a `skill_route` tool; evaluation is the model's own judgment of "remaining requirement" | Medium |
| Trust model (core/signed/approved/untrusted/revoked, digest-bound approval) | `skills_guard` trust levels + verdicts, project quarantine, provenance labels, hub content hashes; no signing/revocation; no load-time approval | Reuse provenance + verdict as trust input; digest recorded in the trace; "approval invalidation" has nothing to invalidate today | Medium |
| Per-node permission scope | Tool-level approval only; skills carry no scopes | Replace with `policy_context = {approval mode, available tools, blocked tools}`; router never widens anything | Design change |
| Routing budgets | Iteration budget per turn exists; no routing budget | New, small (passes per turn, skills per turn) | Low |
| Structured trace | Hooks carry correlation IDs; no JSONL sink; redaction helpers exist | New JSONL writer under `plugin_data_dir` | Low |
| `task_state` input | `conversation_history` + latest `todo_list` result | Adapter, no new state | Low |
| Explicit pins | Slash commands, stacked skills, `auto_load`, `-s` preload | Router must detect and stand down (`_SKILL_INVOCATION_PREFIX` marker) | Low |
| Capability gap | Hub search exists (`hermes skills search`, `auxiliary.skills_hub`) | Gap object can recommend a search over the official index; never installs | Low |

---

## 5. Reuse, modify, replace

### Reuse as-is (public, in-tree names)

- `agent.skill_utils`: `parse_frontmatter`, `iter_skill_index_files`, `iter_project_skill_files`, `get_project_skills_dirs`, `get_external_skills_dirs`, `get_all_skills_dirs`, `get_disabled_skill_names`, `extract_skill_conditions`, `skill_matches_platform`, `skill_matches_environment`, `skill_matches_apps`, `extract_skill_description`, `parse_qualified_name`, `EXCLUDED_SKILL_DIRS`. (Do **not** use `get_scan_ordered_skills_dirs`; it is a compat pointer scheduled for removal, `agent/skill_utils.py:820-833`.)
- `hermes_cli.plugins.get_plugin_manager().list_plugin_skill_metadata()` for plugin skills.
- `tools.skills_guard.content_hash` / `full_content_hash` for digests; `tools.skills_guard.scan_skill_cached` verdicts when present in the hub lock file.
- `tools.skill_usage` provenance helpers (`is_bundled`, `is_hub_installed`, `is_agent_created`, `telemetry_provenance`).
- `hermes_constants.get_hermes_home()` (call-time, never cached), `plugins.plugin_storage.plugin_data_dir`.
- `agent.redact.redact_sensitive_text` for trace redaction.
- `snowballstemmer` (core dependency) and the BM25 formulation in `tools/tool_search_catalog.py:119-136` as a pattern. `search_catalog` itself is tool-shaped (`CatalogEntry.schema`, private `_tokens`), so the router keeps its own ~40-line copy rather than depending on private fields.
- `PluginContext`: `register_hook`, `register_tool`, `register_command`, `register_auxiliary_task`, `register_system_prompt_section`, `get_config`, `ctx.llm.complete_structured`, `emit`.
- Explicit-pin markers: `agent.skill_commands._SKILL_INVOCATION_PREFIX` is private; the router should match the documented literal prefix `[IMPORTANT: The user has invoked the ` and treat a change in that literal as a test failure (covered by a test that imports the constant).
- `skill_view` as the single loading path (dedup, readiness, telemetry come free).

### Modify (in this repository)

- `SKILL.md`: operating loop steps 7, 10, and 11 must say loading happens through `skill_view`, execution is the host loop, and evaluation is the model's remaining-requirement judgment; "Default to four routing passes and eight total selected skills" becomes MVP defaults of one reroute and five skills per turn (matches Hermes' stacked-skill cap).
- `skill.manifest.yaml` and `references/contracts.md`: manifest becomes an optional overlay; add the frontmatter-derivation rules (section 8.3); remove "missing security metadata makes autonomous execution ineligible".
- `references/hermes-integration.md`: replace the assumed `route/execute_plan/evaluate` interfaces with the hook-based contract (section 7); record the verified primitive names.
- `references/testing.md`: acceptance 6 ("typed artifacts between two skills") moves to V2.
- `agents/openai.yaml`: keep for other hosts; note that Hermes ignores it.

### Replace

- "Execution supervisor" → the existing `AIAgent` loop + approval gates + `pre_tool_call` gating.
- "Permission scope per node" → read-only `policy_context` derived from Hermes settings.
- "Route again with updated state" (recursive `route()` call) → `skill_route` tool call with a per-turn budget.
- "SQLite catalog" (roadmap) → in-memory catalog plus a JSON snapshot in `plugin_data_dir`; the pattern mirrors `.skills_prompt_snapshot.json`. `state.db` is core-owned and not a plugin surface.

---

## 6. Conflicts between the architecture and the real codebase

1. **"Core service wrapped by a meta-skill" vs. the Footprint Ladder.** Root `AGENTS.md` ranks new core modules and core tools last; `plugins/AGENTS.md` forbids plugins from touching core. Resolution: plugin first; propose at most one additive core kwarg upstream (13.U3).
2. **Per-turn routing vs. byte-stable system prompt.** The skills index and its guidance cannot change per turn (`agent/AGENTS.md` invariants; prompt restored from the DB at `agent/conversation_loop.py:709`). The router can only speak through the user-message injection channel and tool results. Its output must be small and deterministic per turn (the `api_content` sidecar replays it on retries).
3. **Guidance contradiction.** The index says "you MUST load … err on the side of loading" (`agent/prompt_builder.py:1379-1400`); the router says "prefer no skill". In `shadow`/`advisory` modes both coexist and the directive can only nudge. Making "prefer no skill" real requires either `active` mode gating (plugin) or a config-gated guidance variant in `_render_skills_index` (core change, 13.U9). The one-shot variant (`agent/oneshot_footprint.py:42`) already matches router semantics and is precedent.
4. **Hook spill cap vs. full-content injection.** Default 10,000-char cap per hook context; p50 shipped SKILL.md is 9,175 bytes and 45% exceed the cap. Injecting full skills through `pre_llm_call` would be spilled to disk and replaced with a preview. Resolution: inject a directive; load via `skill_view`.
5. **Manifest security metadata.** `references/contracts.md` makes skills without `security:` ineligible. Zero shipped skills have it. Resolution: eligibility derives from provenance + scan verdict + disable lists + platform/tool conditions; manifest fields are an optional overlay.
6. **`todo` primitive.** It is `todo_list`, in-memory, hook-invisible. Task state for routing is `conversation_history` plus the latest todo result.
7. **`delegate_task` from a router.** Needs `parent_agent`; top-level calls are asynchronous with results arriving as a new message; children cannot delegate unless orchestration is enabled. A synchronous DAG executed by the router is not possible; composition in the MVP is "load these skills in this order" within one turn, and parallel fan-out is the model's own `delegate_task` call (V2 can attach `output_schema` contracts per child).
8. **No embeddings, no new packages.** MVP retrieval is lexical (BM25 + Snowball) and the "semantic" step is the structured LLM selection over the shortlist.
9. **`pre_llm_call` has no tool-availability field.** Eligibility rules like `requires_tools` need `agent.valid_tool_names`, which the payload lacks. MVP approximates from `platform` via `toolsets.resolve_toolset("hermes-<platform>")` and registry availability, and treats the result as advisory; the exact set needs an additive kwarg upstream (13.U3).
10. **Subagent turns.** Children run with `platform="subagent"` and fire `pre_llm_call` like any agent. Routing inside every child multiplies aux calls. Default: skip when `platform in {"subagent"}`.
11. **Fresh agent per gateway message.** Router state must be keyed by `session_id` and stored durably (`plugin_data_dir`), not on the agent.
12. **Plugin skills are absent from the prompt index but present in `skills_list`.** The catalog includes them for parity with `skills_list`.
13. **Prompt-section position.** A static "router protocol" note can be registered but only at `after_memory` (after the skills index) and ≤4,000 chars; it is frozen per session, so it must not encode per-turn state.
14. **Historical reliability is unavailable.** `.usage.json` records views/uses, not outcomes. The 0.10 ranking weight for "historical reliability" is zero in the MVP.
15. **Trajectory files are cwd-relative** (`agent/trajectory.py:40`). The router must not depend on them for traces.
16. **Sep 2026 decomposition compat window.** Any import of a `PLUGIN-COMPAT` re-export fails CI in-tree and is scheduled for removal; the plugin must import canonical module paths only.

---

## 7. Recommended integration point

**Between user intent and skill execution the seam is the turn prologue.** Concretely:

```
user text ──► CLI / gateway slash rewrite (explicit pins; untouched)
          ──► AIAgent.run_conversation
          ──► agent/turn_context.py::build_turn_context
                 ├─ restore byte-stable system prompt (untouched)
                 └─ _collect_pre_llm_call_context  ◄── ROUTER: pre_llm_call
                        │   intent = user_message (+ open todo items from history)
                        │   catalog → eligibility → BM25 shortlist (≤12)
                        │   ctx.llm.complete_structured → {NO_SKILL | SELECT_SKILLS | CAPABILITY_GAP}
                        │   deterministic validation, budgets, trace
                        ▼
                 directive text appended to this turn's user message (advisory/active)
          ──► model call(s)
          ──► tool round
                 ├─ pre_tool_call        ◄── ROUTER (active): allow skill_view only for selected
                 │                           names or within the reroute budget; log otherwise
                 ├─ skill_view / other tools (untouched; the only loading path)
                 ├─ skill_route          ◄── ROUTER tool: one bounded reroute per turn
                 └─ post_tool_call       ◄── ROUTER: record selected vs unselected loads
          ──► post_llm_call / on_session_end   ◄── ROUTER: close the turn record, flush trace
```

Why this point and not another:

- `pre_llm_call` is the only hook whose return value reaches the model, is documented for exactly this purpose ("memory plugins, RAG integrations, guardrails"), and preserves the prompt cache (`website/docs/developer-guide/plugins/index.md`, "pre_llm_call context injection").
- `pre_tool_call` is the only sanctioned place to veto a tool call, and it already carries `session_id`, `turn_id`, and `tool_call_id`, so budgets can be enforced per turn deterministically.
- The explicit-pin paths (`cli.py:1279`, `gateway/run_inbound.py:1140`) run **before** the turn and rewrite the user text with a known prefix; the hook can detect that prefix and stand down, which is the "preserve valid explicit user pins" requirement with no code change.
- A new core tool or a modified `skills_list` would be paid for on every API call by every user (root `AGENTS.md`: "every model tool is sent on every API call"). A plugin tool in its own toolset is opt-in per platform.

Rejected alternatives: modifying `_render_skills_index` per turn (breaks the cache invariant); a `tool_execution` middleware wrapping `skill_view` (heavier than `pre_tool_call`, same power); routing inside `skills_list` (core change, and the model would still have to call it first).

---

## 8. Recommended MVP

### 8.1 Scope

Prove, with a plugin only:

| Requirement | MVP mechanism |
|---|---|
| Dynamic skill discovery | Catalog rebuilt when the directory signature changes (same stat-based rule as `tools/skills_tool.py:40`), covering local, project, external, and plugin skills |
| Metadata-only candidate retrieval | Catalog reads ≤4 KB per SKILL.md (frontmatter), never the body; BM25 shortlist ≤12 |
| Semantic skill selection | One `ctx.llm.complete_structured` call with a fixed JSON schema over the shortlist; temperature 0; ≤300 output tokens; 8 s timeout; fail-open to `NO_SKILL` |
| Load only selected SKILL.md files | Directive names the selected skills; `active` mode blocks `skill_view` for unselected names beyond budget; `advisory` mode measures the unselected-load rate |
| No / one / multi-skill decisions | Decision enum `NO_SKILL`, `SELECT_SKILLS` (1..max_selected, ordered), `CAPABILITY_GAP`, plus `PINNED` (explicit slash skill detected) and `SKIPPED` (gated out) |
| One bounded reroute | `skill_route(remaining_requirement, tried_skills?)` tool; per-`turn_id` budget of 1; second call returns `budget_exhausted` |
| Structured routing logs | JSONL under `<HERMES_HOME>/plugin-data/meta-skill-router/traces/<session_id>.jsonl`, one record per decision, reroute, load, and turn close; redacted |

Out of MVP: embeddings, DAG execution, artifact envelopes, parallel composition, learned reranking, signing, capability ontology, remote catalogs.

### 8.2 Modes

| Mode | `pre_llm_call` | `pre_tool_call` | Purpose |
|---|---|---|---|
| `shadow` (default) | routes and traces; injects nothing | logs only | measure decision quality against what the model did on its own; zero prompt bytes |
| `advisory` | injects the directive (≤1,500 chars) | logs only | prove the model follows routing; measure double loads |
| `active` | injects the directive | blocks `skill_view` for names outside the selection unless the reroute budget allows; block message points at `skill_route` | prove "load only selected" deterministically |

### 8.3 Manifest derivation (frontmatter → `SkillManifest`)

| Manifest field | Source |
|---|---|
| `identity.id` | `<provenance>:<category>/<name>` or `plugin:<name>`; `identity.name` = frontmatter `name` or directory name |
| `identity.version` | frontmatter `version` or `""` |
| `identity.description` | frontmatter `description` (full, ≤1,024) |
| `routing.capabilities/intents/positive_triggers` | frontmatter `metadata.hermes.tags`, `tags`, `triggers`, `category`; `related_skills` for compatibility hints |
| `requirements.tools` | `metadata.hermes.requires_tools` + `requires_toolsets`; `fallback_for_*` as negative conditions |
| `requirements.credentials` | `prerequisites.env_vars`, `required_environment_variables[].name`, `required_credential_files` |
| `requirements.platforms` | frontmatter `platforms`, `environments`, `requires_apps`, `metadata.hermes.session_platforms` |
| `security.trust_requirement` | derived: `bundled` → core; hub `trust_level`+`scan_verdict` from `lock.json` → signed/approved; `agent_created` → approved-local; `external` → approved-local; project → approved-local unless quarantined; unknown → untrusted |
| `security.digest` | `tools.skills_guard.content_hash(skill_dir)` |
| everything else | optional overlay from `skill.manifest.yaml` if present next to SKILL.md; overlay never widens trust |

### 8.4 Configuration (`plugins.entries.meta-skill-router.settings`)

`mode` (shadow), `max_candidates` (12), `max_selected` (3), `max_skills_per_turn` (5), `max_reroutes_per_turn` (1), `skip_platforms` (["subagent"]), `min_message_chars` (12), `selection_timeout_s` (8), `directive_max_chars` (1500), `trace.enabled` (true), `trace.max_bytes` (5 MiB, oldest-first trim as in `tools/skill_ledger.py`), `protocol_section` (false; registers the static after-memory note). Auxiliary routing via `auxiliary.meta_skill_router` (registered task key).

### 8.5 Directive format (advisory/active)

Plain text, deterministic, no secrets, no skill bodies:

```
[Skill routing] Decision: SELECT_SKILLS (confidence high).
Load in this order with skill_view(name) before acting: 1) research/arxiv — matches "find recent papers"; 2) note-taking/obsidian — matches "save to my vault".
Do not load other skills for this request. If a requirement remains unmet after these, call skill_route(remaining_requirement=...) once.
```

`NO_SKILL` injects a single line only in `active` mode ("[Skill routing] No installed skill applies; proceed with general tools.") and nothing in `advisory` mode, so the common case costs nothing.

---

## 9. File-by-file implementation plan

All new code lives in this repository under `plugin/meta-skill-router/` (installable by copying or symlinking to `<HERMES_HOME>/plugins/meta-skill-router/`). Hermes core is not modified in the MVP. Order numbers are implementation order; each step has its own tests and can be merged alone.

### 9.1 Files to create

| # | File | Responsibility | Depends on | Tests | Migration risk |
|---|---|---|---|---|---|
| 1 | `plugin/meta-skill-router/plugin.yaml` | Manifest: `name: meta-skill-router`, `kind: standalone`, `provides_hooks: [pre_llm_call, pre_tool_call, post_tool_call, on_session_end]`, `provides_tools: [skill_route]`, `requires_hermes`, settings schema | — | manifest parses via `hermes_cli.plugins_manifest.parse_manifest_file`; discovery via `PluginManager.discover_and_load` in a temp `HERMES_HOME` (pattern: `tests/plugins/test_disk_cleanup_plugin.py`) | none |
| 2 | `plugin/meta-skill-router/router/schemas.py` | Dataclasses + JSON schemas: `SkillManifest`, `TaskIntent`, `Candidate`, `RoutingDecision` (`decision`, `selected[{name, reason, order}]`, `confidence`, `missing_capabilities`), `CapabilityGap`, trace record types; `to_json` helpers | stdlib | schema round-trips; selection JSON schema rejects unknown decisions and >`max_selected` items | none |
| 3 | `router/manifest.py` | Frontmatter → `SkillManifest` adapter (8.3); optional `skill.manifest.yaml` overlay; trust derivation from provenance + hub lock | `agent.skill_utils.parse_frontmatter`, `tools.skill_usage`, `tools.skills_guard.content_hash`, hub `lock.json` reader | golden frontmatter fixtures (bundled samples: obsidian, notion, arxiv); overlay cannot raise trust; missing fields default safely | frontmatter fields evolve; keep adapter tolerant |
| 4 | `router/catalog.py` | Discover all sources, build `SkillManifest` list, stat-signature cache (copy the rule in `tools/skills_tool.py:40-56`), JSON snapshot in `plugin_data_dir`, ≤4 KB read per SKILL.md | 3; `agent.skill_utils` walkers; `hermes_cli.plugins.get_plugin_manager` | new skill dir appears without restart; quarantined project skill excluded; plugin skill included; body never read (monkeypatch `open` size); 1,000 synthetic skills build < 1 s warm | profile switching: resolve `get_hermes_home()` per call |
| 5 | `router/eligibility.py` | Deterministic filters: disabled lists, platform/environment/apps gates, `requires_tools`/`fallback_for_*` vs approximated tool set, missing credentials flagged (not excluded, see 13.U8), trust floor | 3, 4; `toolsets.resolve_toolset`, `tools.registry` | each rule has a positive and negative case; unknown tool set fails open | tool set approximation (6.9) |
| 6 | `router/retrieval.py` | BM25 + Snowball over `name`, `description`, tags, triggers, category; exact-name boost; rarest-token gate as in `tools/tool_search_catalog.py:146`; returns ≤`max_candidates` | 4; `snowballstemmer` | ranking invariants (exact name first; unrelated query yields empty); p95 < 100 ms on 1,000 skills | none (no new dependency) |
| 7 | `router/selector.py` | Build the selection prompt (shortlist metadata only, treated as data), call `ctx.llm.complete_structured(json_schema=...)`, validate `selected ⊆ shortlist`, enforce `max_selected`, map failures/timeouts to `NO_SKILL` with `error` | 2, 6; `agent.plugin_llm` via `ctx.llm` | mocked `ctx.llm`: no/one/multi/gap goldens; malformed JSON → NO_SKILL; injection text inside a skill description does not change the schema-validated decision | aux model quality; cost per turn |
| 8 | `router/state.py` | Per-`session_id` routing state: selections per `turn_id`, reroutes used, loads observed; JSON in `plugin_data_dir`; TTL cleanup | `plugins.plugin_storage` | state survives a fresh agent instance; budget counters reset per turn | concurrent gateway turns: file lock |
| 9 | `router/trace.py` | JSONL writer with size trim; `redact_sensitive_text` on every string field; record kinds `route.decision`, `route.reroute`, `skill.load`, `turn.close` | 2, 8; `agent.redact` | a fake API key in the user message never appears in the trace; trim keeps newest | none |
| 10 | `router/directive.py` | Render the directive (8.5); detect explicit-pin prefix; enforce `directive_max_chars` | 2 | byte-stable for identical decisions; pinned messages produce no directive | prompt-cache: text must be identical on retry (guaranteed by sidecar) |
| 11 | `router/hooks.py` | `on_pre_llm_call`, `on_pre_tool_call`, `on_post_tool_call`, `on_session_end` handlers; mode switch; platform skip; never raises | 4–10 | integration through real `hermes_cli.lifecycle.invoke_hook` with the plugin loaded; `shadow` returns `None`; `active` returns a block dict for an unselected `skill_view` | hooks are fail-open in core; still wrap everything |
| 12 | `router/tool_skill_route.py` | `skill_route` schema + handler; reruns 4–7 for the remaining requirement, excludes loaded skills, charges the per-turn budget, returns selection or `CapabilityGap` (may suggest `hermes skills search <q>`; never installs) | 4–9; `ctx.register_tool(name="skill_route", toolset="meta_skill_router", ...)` | second call in a turn → `budget_exhausted`; names outside catalog rejected; handler returns JSON string via `tool_error`/`tool_result` | one more tool schema on platforms that enable the toolset |
| 13 | `router/config.py` | Settings with defaults (8.4) via `ctx.get_config`; validation | — | invalid values fall back to defaults with a warning | none |
| 14 | `router/commands.py` | `/route` slash command: `dry-run <text>`, `last`, `stats` (reads the trace) | 4–9; `ctx.register_command` | handler output shape | none |
| 15 | `plugin/meta-skill-router/__init__.py` | `register(ctx)`: wire 11–14, `register_auxiliary_task("meta_skill_router", ...)`, optional `register_system_prompt_section("meta-skill-router.protocol", ...)` | all | plugin loads through discovery; registration idempotent on `discover_plugins(force=True)` | none |
| 16 | `plugin/meta-skill-router/README.md` | Install, modes, config, trace format | — | — | — |
| 17 | `tests/` (this repo) mirrored per module + `tests/fixtures/skills/` synthetic SKILL.md set (≥20 skills across ≥5 categories, including one quarantined project skill and one platform-gated skill) | — | — | — | needs `hermes-agent` importable on `PYTHONPATH` in CI (clone at a pinned commit; no package install required) |

### 9.2 Files to modify (this repository)

| File | Change |
|---|---|
| `SKILL.md` | Align steps 7, 10–13 and the recursion limits with sections 7–8; name `skill_view` as the only loading path; state MVP budgets |
| `skill.manifest.yaml` | `requirements.tools: ["skills_list", "skill_view", "skill_route"]`; note that the file is an overlay |
| `references/contracts.md` | Add "Manifest derivation from SKILL.md frontmatter" (8.3); soften the security-metadata rule |
| `references/hermes-integration.md` | Replace "Stable interfaces" with the hook contract; add verified primitive table (section 3) |
| `references/architecture.md` | Mark DAG/artifacts/embeddings as V2; replace "SQLite catalog" with snapshot JSON |
| `references/testing.md` | Move acceptance 6 to V2; add the criteria in section 11 |

### 9.3 Optional upstream core changes (separate PRs to `NousResearch/hermes-agent`, not part of the MVP)

| Change | Where | Why | Rubric fit |
|---|---|---|---|
| Add `available_tools: list[str]` and `available_toolsets: list[str]` to the `pre_llm_call` payload | `agent/turn_context.py:757-769` | Exact eligibility instead of the approximation in 6.9 | Additive keyword field; consumer exists (this plugin) so it is not speculative |
| Config-gated guidance variant in `_render_skills_index` ("load only what the routing directive names") | `agent/prompt_builder.py:1379-1400` | Removes the contradiction in 6.3 for `active` mode | Must be byte-stable per session; default off |
| Optional `query` parameter on `skills_list` returning a ranked subset | `tools/skills_tool.py:665-691` | Would let any model do metadata retrieval without the plugin tool | Touches a core tool schema sent on every call; defer until shadow data justifies it |

### 9.4 Implementation order and dependencies

1 → 2 → 3 → 4 → 6 → 5 → 7 → 9 → 8 → 10 → 11 (shadow mode complete; start collecting traces) → 12 → 13 → 14 → 15 (advisory/active) → 9.2 doc updates → 9.3 upstream proposals after shadow data.

---

## 10. Test plan

Run in this repository with `hermes-agent` on `PYTHONPATH` at the pinned commit; use Hermes' own conftest conventions (temp `HERMES_HOME`, never `~/.hermes`).

**Unit**
- Manifest adapter: every field in 8.3 from fixtures; overlay cannot raise trust; malformed frontmatter yields a listable manifest with empty description (mirrors `_parse_skill_file`).
- Catalog: signature invalidation on add/remove/edit; snapshot reuse; ≤4 KB reads; plugin skills present; quarantine respected; profile switch re-resolves the home.
- Eligibility: each rule positive/negative; unknown tool availability fails open.
- Retrieval: exact-name first; rarest-token gate empties unrelated queries; stemming ("issues" matches "issue"); determinism.
- Selector: mocked `ctx.llm` returning valid, invalid, oversized, and empty JSON; timeout; injection strings in descriptions.
- Budgets: one reroute per `turn_id`; `max_skills_per_turn`; counters independent across sessions.
- Trace: redaction; trim; one record per decision.
- Directive: byte stability; length cap; pinned detection using the imported prefix constant.

**Golden routing cases** (fixture skills, mocked LLM answers, asserted plan shapes)
- no skill ("what is 2+2"), exactly one, sequential two, ambiguous pair (expect `NEED_MORE_METADATA` → second pass over ≤5 with tags), missing credential (flagged), quarantined best match (excluded), platform-gated (excluded), negative trigger, newly added skill without code change, explicit `/skill` pin (`PINNED`, nothing injected), subagent platform (`SKIPPED`).

**Integration**
- Load the plugin through `PluginManager.discover_and_load`; invoke `hermes_cli.lifecycle.invoke_hook("pre_llm_call", ...)` with a realistic payload; assert shadow returns `None`, advisory returns `{"context": ...}` under the spill cap.
- `pre_tool_call` through `hermes_cli.plugins._dispatch_pre_tool_call_hooks("skill_view", {"name": ...}, session_id=..., turn_id=...)`: allowed for selected, blocked for unselected in active mode, allowed within budget after `skill_route`.
- `skill_route` through `tools.registry.registry.dispatch` (real registry; plugin scope).
- End-to-end turn with a stubbed model client (pattern from `tests/agent/test_system_prompt*.py`): assert the system prompt bytes are identical with the plugin enabled and disabled (except the optional static section), and that the current turn's `api_content` carries the directive.

**Security**
- Skill names with `..`, absolute paths, or Windows drives are rejected by `skill_route` before touching `skill_view`.
- Directive never contains skill bodies or `.env` values.
- A skill description containing "ignore previous instructions" cannot change the decision schema.
- Active-mode block cannot be bypassed via `file_path` variants of `skill_view`.

**Scale**
- 100 / 1,000 / 10,000 synthetic skills: catalog build time, snapshot size, retrieval p95, selector prompt size ≤ 32,000 chars (~8k tokens).

---

## 11. Acceptance criteria (MVP)

| # | Criterion | Measure | Target |
|---|---|---|---|
| A1 | New trusted skill routable without code changes | add a SKILL.md to the temp skills dir between two turns | present in the next decision's candidate set |
| A2 | Metadata-only retrieval | bytes read per SKILL.md during routing; `skill_view` calls made by the router | ≤4,096 bytes; 0 calls |
| A3 | Bounded shortlist and prompt | candidates passed to the LLM; selector prompt chars | ≤12; ≤32,000 |
| A4 | No/one/multi decisions | golden suite | 100% of cases produce the expected decision shape |
| A5 | Only selected skills loaded | active mode: unselected `skill_view` blocked; advisory mode: unselected-load rate over the golden e2e runs | blocked 100%; advisory rate reported (baseline, no target) |
| A6 | One bounded reroute | second `skill_route` in a turn | `budget_exhausted`, no LLM call |
| A7 | Reconstructable, redacted trace | each turn has `route.decision` with `intent_hash, candidates, scores, rejections, selected, confidence, mode, latency_ms`, `turn.close` with loads; planted secret | present; secret absent |
| A8 | Fail-open | aux LLM raises/times out | decision `NO_SKILL` with `error`; turn completes |
| A9 | Explicit pins preserved | `/skill` scaffolded message | decision `PINNED`; zero injected bytes |
| A10 | Prompt-cache safety | system prompt bytes with plugin on vs off | identical (unless `protocol_section` enabled) |
| A11 | Shadow cost | prompt bytes added in shadow mode | 0 |
| A12 | Latency and cost | selector wall time (mocked at unit level; measured live in a manual eval) | p95 ≤ 3 s live; ≤ 1 aux call per routed turn |
| A13 | Scale | 1,000 skills | cold build ≤ 2 s, warm ≤ 50 ms, retrieval p95 ≤ 100 ms |

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Extra auxiliary call on every routed turn | latency +1–3 s, tokens +1–3k per turn | `shadow` default; `min_message_chars`; skip subagents; cheaper `auxiliary.meta_skill_router` model; skip when the catalog is empty or the message is a slash command |
| Model ignores the directive or double-loads | wasted context | `active` mode gating; measure in advisory; `skill_view` dedup already stubs repeats |
| Over-blocking in active mode | user-visible refusals to load a skill the user named | pin detection; explicit skill names in the user text are added to the allowed set deterministically before the LLM step |
| Tool-availability approximation (6.9) | wrong `requires_tools` eligibility | fail open; propose the upstream kwarg |
| Plugin imports of in-tree modules (`agent.skill_utils`, `tools.skills_guard`) are not covered by the plugin compatibility contract | breakage on refactors | pin a Hermes commit in CI; wrap imports; degrade to name+description only when a helper is missing |
| Gateway multi-profile processes | wrong profile's skills or state | resolve `get_hermes_home()` and `plugin_data_dir()` per call; key caches by `hermes_home_key()` |
| Hook context spill | directive replaced by a preview | keep directive ≤1,500 chars; assert in tests |
| Trace growth | disk | size trim; per-session files; no bodies |
| Telemetry policy | rejection upstream | local only; no network; no identifiers beyond session/turn ids already present in Hermes' own logs |
| Curator/usage side effects | skewed skill lifecycle stats | the router never bumps usage itself; `skill_view` remains the only loader |

---

## 13. Unresolved decisions

| # | Decision | Recommendation |
|---|---|---|
| U1 | Ship as a standalone plugin in this repo vs. a core PR to `hermes-agent` | Plugin first; core PRs only for 9.3 after shadow data |
| U2 | Default mode | `shadow` for the first release; `advisory` after A5 baseline is known |
| U3 | Propose the additive `available_tools`/`available_toolsets` `pre_llm_call` kwargs upstream | Yes, after the plugin exists as the consumer |
| U4 | Reroute via a plugin `skill_route` tool vs. a `query` parameter on core `skills_list` | Plugin tool now; revisit once traces show reroute frequency |
| U5 | Route inside subagent turns | Off by default |
| U6 | Embeddings provider for V2 | None in MVP; decide after measuring BM25 + LLM top-1 accuracy in shadow |
| U7 | Selector model | Main model via aux "auto" route by default; allow a cheaper pin through `auxiliary.meta_skill_router` |
| U8 | Skills with missing required credentials: exclude or select-and-flag | Select-and-flag; `skill_view` prompts for the secret interactively, which is existing UX |
| U9 | Change the index guidance in core for active mode | Defer; only if advisory data shows the guidance overrides the directive |
| U10 | Repo layout: keep `SKILL.md` as the host-facing operating policy and add `plugin/` beside it, or split into two repos | One repo; the plugin can expose the SKILL.md via `ctx.register_skill` for hosts that want the policy loaded |
| U11 | Whether `NO_SKILL` injects a line in advisory mode | No (zero bytes in the common case) |

---

## Appendix A. Evidence index

- Skills discovery/loading: `tools/skills_tool.py` (whole file), `tools/skills_tool_plugin.py:15-45`, `tools/skills_tool_dedup.py:1-40`, `agent/skill_utils.py:23-31,105,143-235,300,359,420,437-585,657-700,763-833`, `agent/prompt_builder.py:1113-1262,1262-1490`, `agent/system_prompt.py:300-339,659-720`, `agent/skill_commands.py:1-60,165-300,391-560,636-700`, `agent/skill_bundles.py:1-30`, `agent/oneshot_footprint.py:42`, `agent/coding_context.py:409`.
- Orchestration/hooks: `run_agent.py:230-300,1045-1075,1350-1363`, `agent/conversation_loop.py:659-790,1437-1600`, `agent/turn_context.py:93-118,745-800,1100-1130,1180-1240`, `agent/turn_finalizer.py:665-720`, `agent/inline_tool_executors.py:1-120,235-280`, `agent/tool_executor.py:651-665`, `hermes_cli/lifecycle.py:1-71`, `hermes_cli/plugins.py:108-204,382-390,456-505,645-700,863-1000,1529-1536,1966-1975`, `hermes_cli/middleware.py:19-26`, `hermes_cli/plugins_manifest.py:342-382`, `plugins/plugin_storage.py`, `website/docs/developer-guide/plugins/index.md:1015-1100`, `website/docs/developer-guide/plugin-llm-access.md`.
- Tools: `tools/registry.py:182-200,655-690,880`, `model_tools.py:612,679-703,872-880`, `toolsets.py:12-45,102-130,157`, `tools/delegate_tool.py:33-750`, `tools/delegate_tool_toolsets.py:14-85`, `tools/delegation_output_schema.py`, `tools/todo_tool.py`, `tools/tool_search_catalog.py:1-215`, `agent/auxiliary_client.py:7786-7835`, `agent/plugin_llm.py:1-40,440-500`, `hermes_cli/main_provider_setup.py:53-66`, `tools/hook_output_spill.py:1-50`.
- Permissions/trust: `tools/approval.py`, `tools/approval_floors.py`, `tools/approval_context.py`, `tools/approval_smart.py:74-134`, `tools/skills_guard.py:1-40,595-720,821-849`, `tools/skill_usage.py:1-50,440-500`, `tools/skill_ledger.py:1-30`, `tools/skill_provenance.py`, `hermes_cli/config_defaults.py:1405-1461,1638-1676`.
- State/logging: `hermes_state.py:443,1557-1597`, `hermes_state_sessions.py:397,654,780`, `hermes_state_messages.py:293`, `hermes_state_common.py:239,328-581`, `hermes_logging.py:203-245`, `agent/redact.py:862,1133`, `agent/trajectory.py:37-40`.
- Conventions: root `AGENTS.md` (invariants, rubric, Footprint Ladder), `tools/AGENTS.md`, `agent/AGENTS.md`, `plugins/AGENTS.md`, `tests/conftest.py` (temp `HERMES_HOME`), `tests/plugins/test_disk_cleanup_plugin.py`, `tests/tools/test_skills_tool.py`, `tests/tools/test_skills_tool_discovery_cache.py`.

## Appendix B. Not verified

- Whether any auxiliary "embedding" task exists in core (`agent/AGENTS.md` mentions the word; no call site found).
- Exact behavior of `consume_prepared_guard` (batch pre-approval) and the gateway approval wait loop internals.
- Live latency/cost of the selector call (no model calls were made during this analysis).
- The `"todo"` legacy alias in `model_tools.py:616-619` was reported by a survey and not re-read line by line; the registered tool name `todo_list` was read directly.
