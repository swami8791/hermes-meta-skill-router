# Hermes Integration

## Boundary

Place the router between Hermes intent interpretation and skill execution:

```text
User -> Intent -> router.route() -> ExecutionPlan -> Supervisor
     -> selected skills/tools -> Evaluator -> optional reroute -> Response
```

The router is a core service wrapped by this meta-skill, not prompt text alone.

## Verify before implementation

Inspect the real Hermes codebase and verify:

- Skill registry and discovery
- Skill instruction loading
- Tool execution boundaries
- Permission enforcement
- Task state
- Delegation primitives
- Logging and telemetry
- Actual names and behavior of any skill-listing, skill-viewing, delegation, or todo primitives

Map proposed components to existing code and flag conflicts.

## Stable interfaces

```text
route(task_intent, task_state, policy_context) -> ExecutionPlan
execute_plan(plan, artifact_store, policy_context) -> ExecutionResult
evaluate(result, success_criteria) -> CompletionAssessment
```

Completion states: `complete`, `partially_complete`, `needs_capability`, `blocked`, and `failed`.

## Rollout

1. Catalog: wrap the registry, scan roots, compile manifests, record trust/digests, and build incremental indexes.
2. Routing: add `route()` and intercept implicit selection while preserving valid explicit user pins.
3. Supervision: add `execute_plan()` and route skill loading, tools, delegation, and artifacts through it.
4. Evaluation: add validators and one bounded MVP recovery pass.
5. Activation: deploy in shadow, advisory, then active mode.

## Responsibility split

| Responsibility | Owner |
|---|---|
| Discovery, parsing, trust, digests | Deterministic |
| Retrieval, prerequisites, permissions | Deterministic |
| Interface compatibility and baseline score | Deterministic |
| Intent interpretation and ambiguous comparison | LLM |
| Sequencing proposal | LLM |
| DAG and output validation | Deterministic first |
| Qualitative assessment | LLM when required |
| Budgets and progress checks | Deterministic |
| Gap object | Deterministic |
| Explanation and final synthesis | LLM |

The LLM proposes actions; deterministic code decides whether they are legal and executable.

## Pre-coding prompt

```text
Use the Hermes Meta-Skill Router architecture as the approved direction.

Inspect the existing Hermes codebase and determine exactly how it integrates. Do not implement anything yet.

Produce:
1. A current-state map of discovery, loading, orchestration, execution, permissions, task state, and logging.
2. A gap analysis.
3. Components to reuse, modify, or replace.
4. Verification of assumed skill-listing, viewing, delegation, and task-state primitives.
5. The exact integration point between intent and execution.
6. A file-by-file plan with responsibilities, order, dependencies, tests, and migration risks.
7. The smallest MVP proving dynamic discovery, metadata-only retrieval, semantic selection, deferred full loading, no/one/multiple-skill decisions, one reroute, and logs.
8. Conflicts with the real codebase.
9. Measurable acceptance criteria.

Do not write production code, install packages, change behavior, or invent integration points.
```
