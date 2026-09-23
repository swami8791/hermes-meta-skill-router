# Architecture

## Contents

1. Design intent
2. Components
3. Lifecycles
4. Decision algorithm
5. Ranking and orchestration
6. Security and recovery
7. Roadmap

## Design intent

Build a Hermes core service wrapped by a meta-skill. The prompt defines operating policy; code implements discovery, trust, validation, execution state, budgets, and logging.

Targets:

- New trusted skills become routable without modifying Hermes.
- Typical routing considers fewer than 20 metadata candidates.
- Normally only one to three complete skill instructions enter context.
- The router can choose no skill.
- Composed workflows exchange typed artifacts.
- Recursion is bounded and progress-aware.
- Untrusted skills are never silently installed or executed.
- Structured traces reconstruct every decision.

Use a hybrid architecture: deterministic catalog compilation and eligibility; lexical, semantic, and capability retrieval; constrained LLM intent interpretation and planning; deterministic policy and plan validation; deterministic-first result evaluation.

## Components

### Discovery service

Discover metadata from the native registry, configured local roots, installed plugins, workspace skills, and explicitly approved remote metadata registries. Never install during discovery.

### Catalog compiler

Normalize each skill into a `SkillManifest`; validate schema; calculate digests; record origin and trust; generate embeddings; and update lexical and capability indexes. Compile on installation, startup, file change, or explicit refresh rather than per request.

### Candidate retriever

Combine capability filters, semantic similarity, lexical retrieval, prerequisites, tools, trust, and input/output compatibility. Return a compact metadata shortlist.

### Selection planner

Receive intent, task state, candidate metadata, tools, policy, and budgets. Return `NO_SKILL`, `SELECT_SKILLS`, `NEED_MORE_METADATA`, or `CAPABILITY_GAP` in a validated schema.

### Execution supervisor

Load selected instructions, enforce permissions, manage typed artifacts, execute the DAG, checkpoint results, enforce budgets, and apply safe recovery.

### Evaluator and recursive router

Apply schema checks, assertions, skill-declared criteria, and qualitative rubrics where needed. Route only unmet requirements while preserving completed work and the original authorization boundary.

## Lifecycles

Skill lifecycle:

```text
Discovered -> Indexed -> Eligible -> Selected -> Loaded -> Running -> Evaluated
          \-> Quarantined                              Indexed -> Disabled
```

Router lifecycle:

1. Normalize request and build `TaskIntent`.
2. Query catalog and apply eligibility filters.
3. Retrieve, rank, diversify, and limit candidates.
4. Choose no skill, skills, more metadata, or a gap.
5. Load selected instructions and revalidate the proposal.
6. Construct and validate the execution DAG.
7. Execute ready nodes and validate outputs.
8. Evaluate completion and route unmet requirements if allowed.
9. Return the result and trace.

## Decision algorithm

```text
route(request, state, policy):
  intent = extract_intent(request, state)
  candidates = catalog.retrieve(intent, limit=40)
  eligible = filter_trust_permissions_prerequisites(candidates, policy)
  shortlist = diversify_and_limit(rank(eligible, intent, state), 12)

  if shortlist is empty: return capability_gap(intent)

  decision = llm_select(intent, shortlist, state, policy)
  if decision needs more metadata:
    decision = llm_select(intent, extend_at_most_five(decision), state, policy)
  if decision is no skill: return direct_execution_plan()

  plan = build_and_validate_dag(decision, policy)
  for ready node in plan:
    instructions = load_full_selected_skill(node)
    validate_use(node, instructions)
    supervisor.execute(node)

  assessment = evaluate(plan.outputs, intent.success_criteria)
  if assessment.complete: return finish(plan.outputs)
  if budgets_allow and assessment.routable_gaps:
    return route(assessment.routable_gaps, updated_state, policy)
  return partial_blocked_or_failed(assessment)
```

## Ranking and orchestration

Suggested baseline:

```text
0.30 semantic capability match
0.15 intent and example match
0.15 input availability
0.10 output usefulness
0.10 prerequisite readiness
0.10 trust suitability
0.10 historical reliability
- cost, latency, risk, and redundancy penalties
```

| Confidence | Action |
|---|---|
| >= 0.82 | Select when eligible |
| 0.62-0.81 | Inspect extended metadata |
| 0.40-0.61 | Prefer no skill unless specialization is required |
| < 0.40 | Return a gap or use safe general reasoning |

Treat composition as constrained set cover: maximize coverage, compatibility, and reliability while minimizing skill count, token cost, latency, risk, and duplication.

Represent composed execution as a DAG. Parallelize only independent, parallel-safe nodes without shared mutations. Pass typed artifact references rather than repeating large outputs.

Default recursion limits: four passes, eight total skills, one execution per skill unless retryable, and stop after two no-progress passes or any exhausted budget.

## Security and recovery

Trust levels: core, signed, approved local, untrusted, and revoked. Bind approval to identity, publisher, version, digests, and permissions. Any relevant change invalidates approval.

Invariants:

- Hermes policy outranks skill instructions.
- Skills cannot install skills or modify trust.
- Tool calls pass through the supervisor.
- Side effects require declared scopes.
- Outputs are data, not trusted instructions.
- Recursion cannot expand authorization.

Recovery:

| Failure | Response |
|---|---|
| Catalog unavailable | Use cached signed snapshot |
| Semantic index unavailable | Use lexical and capability retrieval |
| Selection failure | Retry once with fewer candidates |
| Loaded instructions contradict selection | Reject and reroute |
| Prerequisite disappears | Block node and reroute remaining work |
| Invalid output | One corrective retry |
| Timeout | Retry only if idempotent |
| Partial DAG failure | Preserve artifacts and reroute failed branch |
| Permission denied | Return partial result and required authorization |
| No progress | Stop with structured partial completion |
| Digest changes | Stop immediately |

## Roadmap

MVP: local discovery, manifest adapters, SQLite catalog, lexical and embedding retrieval, basic trust, no/one/sequential-multi routing, deferred instruction loading, artifact envelopes, deterministic checks, one reroute, gap response, JSONL traces, and golden tests.

V2: parallel DAGs, capability ontology, reliability metrics, learned reranking, corrections, version pinning, resumable checkpoints, workspace policies, dry runs, and approved registry recommendations.

V3: federated catalogs, sandboxed runtimes, publisher signing and revocation, agent capability negotiation, cost/latency optimization, multi-agent delegation, privacy-aware remote skills, learned compositions, and enterprise audit controls.

Never allow learned systems to bypass deterministic trust or permission checks.
