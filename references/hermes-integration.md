# Hermes Integration

Verified against `NousResearch/hermes-agent` @ `2332a64` (2026-09-23). The full analysis, gap list,
conflicts, and acceptance criteria live in
[`docs/meta-skill-router-integration-plan.md`](../docs/meta-skill-router-integration-plan.md).

## Boundary

The router is a Hermes **plugin**, not a core service. It sits on the sanctioned per-turn seams:

```text
User -> explicit /skill rewrite (untouched) -> AIAgent.run_conversation
     -> build_turn_context: pre_llm_call  ==> router.route_turn()  -> directive appended to the user message
     -> model -> tool round: pre_tool_call ==> skill_view gating (active mode)
                             skill_route   ==> one bounded reroute
                             post_tool_call ==> load observation
     -> on_session_end                    ==> turn close + trace
```

The system prompt is byte-stable per conversation and is never touched. Loading stays on `skill_view`.

## Verified primitives

| Assumed | Actual | Notes |
|---|---|---|
| `skills_list` | `skills_list(category?)` | name + description (≤1,024 chars) + category; no tags, no query |
| `skill_view` | `skill_view(name, file_path?)` | the only loader: readiness/secret capture, dedup stub, usage telemetry, templating |
| `delegate_task` | `delegate_task(tasks=[...], action?)` | needs a live parent agent; top-level runs in the background; not callable from a hook |
| todo | tool `todo_list`, in-memory `TodoStore` | not persisted, not in hook payloads; derivable from the latest `todo_list` tool result |

## Plugin surface used

`register_hook` (`pre_llm_call`, `pre_tool_call`, `post_tool_call`, `on_session_end`), `register_tool`
(`skill_route`, toolset `meta_skill_router`), `register_auxiliary_task` (`meta_skill_router`),
`register_command` (`/route`), optional `register_system_prompt_section` (after memory, frozen per
session), `ctx.llm.complete_structured`, `ctx.get_config`, `ctx.state.data_dir`.

Hermes helpers reused (public, in-tree): `agent.skill_utils.{parse_frontmatter, iter_skill_index_files,
iter_project_skill_files, get_project_skills_dirs, get_all_skills_dirs, get_external_skills_dirs,
get_disabled_skill_names, skill_matches_*}`, `tools.skill_usage.{is_bundled, is_hub_installed,
is_agent_created}`, `agent.redact.redact_sensitive_text`, `toolsets.resolve_toolset`,
`hermes_cli.plugins.get_plugin_manager().list_plugin_skill_metadata()`. Every import degrades gracefully.

## Stable interfaces (plugin)

```text
Router.route_turn(user_message, history, session_id, turn_id, platform) -> RouteResult
Router.reroute(session_id, remaining_requirement, tried_skills?)      -> tool result dict
Router.before_skill_view(args, session_id) -> {"action": "block", "message"} | None
Router.after_skill_view(args, session_id, status) / Router.close_turn(session_id)
```

Decisions: `NO_SKILL`, `SELECT_SKILLS`, `CAPABILITY_GAP`, plus `PINNED` (explicit `/skill`) and
`SKIPPED` (gated out). Completion states from the original design (`complete`, `partially_complete`,
`needs_capability`, `blocked`, `failed`) are the model's own exit reporting; the router does not
evaluate outputs in the MVP.

## Rollout

1. `shadow`: trace decisions, zero prompt bytes. Compare with what the model loaded unaided.
2. `advisory`: inject the directive; measure unselected-load rate.
3. `active`: gate `skill_view` outside the selection; one reroute per turn.
4. Upstream (optional, separate PRs): additive `available_tools` in the `pre_llm_call` payload; a
   config-gated router-aware variant of the skills-index guidance.

## Responsibility split

| Responsibility | Owner |
|---|---|
| Discovery, frontmatter parsing, provenance, fingerprints | Deterministic (plugin) |
| Eligibility, BM25 shortlist, budgets, gating | Deterministic (plugin) |
| Selection among shortlisted candidates | LLM (one structured call, validated by code) |
| Loading, permissions, execution | Hermes (`skill_view`, approval gates, agent loop) |
| Remaining-requirement judgment (reroute trigger) | LLM (the main model, via `skill_route`) |
| Trace | Deterministic (plugin), redacted |
