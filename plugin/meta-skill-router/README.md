# meta-skill-router (Hermes plugin)

Routes each turn to the smallest set of installed skills. Design and rationale:
[`docs/meta-skill-router-integration-plan.md`](../../docs/meta-skill-router-integration-plan.md).

## What it does per turn

1. `pre_llm_call`: builds a metadata-only catalog of installed skills (frontmatter head of each
   `SKILL.md`, never the body), filters eligibility deterministically (disabled, platform, session
   platform, `requires_tools`, trust), shortlists at most 12 candidates with BM25, asks the configured
   auxiliary model for one structured decision (`NO_SKILL`, `SELECT_SKILLS`, `CAPABILITY_GAP`),
   validates it (only shortlist names, capped count), and traces the result.
2. In `advisory` or `active` mode it appends a short `[Skill routing]` directive to the user message
   naming the skills to load with `skill_view`, in order. Nothing touches the system prompt.
3. `pre_tool_call` (active mode only): `skill_view` for a skill outside the selection is blocked with a
   message that points at `skill_route`. Explicit `/skill` invocations are never gated.
4. `skill_route(remaining_requirement=...)`: one bounded reroute per turn; returns the next skills to
   load, a `capability-gap.v1` object, or `budget_exhausted`.
5. `post_tool_call` / `on_session_end`: records which skills were loaded (selected or not) and closes
   the turn in the trace.

## Install

```bash
cp -r plugin/meta-skill-router ~/.hermes/plugins/meta-skill-router
```

Then enable it and pick a mode in `config.yaml`:

```yaml
plugins:
  enabled: [meta-skill-router]
  entries:
    meta-skill-router:
      settings:
        mode: shadow        # shadow | advisory | active
```

Enable the `meta_skill_router` toolset for platforms that should expose `skill_route` (it is a normal
plugin toolset; `hermes tools` lists it).

## Modes

| Mode | Prompt bytes added | `skill_view` gating | Use |
|---|---|---|---|
| `shadow` (default) | 0 | none | collect decision traces and compare with what the model loaded on its own |
| `advisory` | directive only for `SELECT_SKILLS` / `CAPABILITY_GAP` | none | prove the model follows routing; measure unselected loads |
| `active` | directive, plus one line for `NO_SKILL` | blocks unselected loads beyond the reroute budget | enforce "load only selected" |

## Settings

`mode`, `max_candidates` (12), `max_selected` (3), `max_skills_per_turn` (5), `max_reroutes_per_turn`
(1), `skip_platforms` (`[subagent]`), `min_message_chars` (12), `selection_timeout_s` (8),
`directive_max_chars` (1500), `trace_enabled` (true), `trace_max_bytes` (5 MiB), `protocol_section`
(false), `allow_untrusted` (false), `route_aux_task` (true). By default the selector runs through the auxiliary task `meta_skill_router`
(`auxiliary.meta_skill_router.*` in `config.yaml`) so a cheaper model can be pinned.

## Traces

`<HERMES_HOME>/plugin-data/meta-skill-router/traces/<session_id>.jsonl`, one record per event
(`route.decision`, `route.reroute`, `skill.load`, `skill.load_blocked`, `turn.close`). Every string
passes through Hermes' secret redaction. `/route stats` summarises them; `/route dry-run <text>` shows
a decision without a turn; `/route catalog` lists what the router sees.

## Guarantees

- Fail-open: any router error, selector timeout, or bad JSON yields `NO_SKILL` and the turn proceeds.
- The router never reads a skill body, never calls `skill_view` itself, never installs anything, and
  never widens permissions; loading stays on `skill_view` (dedup, readiness prompts, usage telemetry).
- The directive is deterministic for a given decision, so retries in a turn send identical bytes.

## Tests

```bash
HERMES_AGENT_SRC=/path/to/hermes-agent python -m pytest -q
```
