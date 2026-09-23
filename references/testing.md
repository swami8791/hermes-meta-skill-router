# Test Strategy

## Unit

- Manifest parsing and schema validation
- Trust classification and digest invalidation
- Prerequisite and permission filtering
- Ranking and confidence bands
- DAG cycle detection and artifact compatibility
- Loop budgets and log redaction

## Golden routing

Cover no skill, exactly one, sequential multiple, parallelizable work, ambiguous candidates, missing prerequisites, untrusted best match, capability gap, negative triggers, and a newly installed skill without router changes.

Each case records required capabilities, eligible and rejected candidates, acceptable plan shapes, forbidden selections, and explanation assertions.

## Integration

- Registry -> catalog -> selection -> execution
- Legacy frontmatter adapter
- Output passed downstream
- Partial DAG recovery
- Rerouting after incomplete output
- Real Hermes registry/loading integration
- Supervisor permission enforcement

## Security

- Injection in skill instructions
- Attempted permission elevation
- Malicious output presented as instructions
- Under-declared side effects
- Digest changes after approval
- Path traversal and symlink abuse
- Secret leakage in traces
- Untrusted installation requests

## Scale and metrics

Test 100, 1,000, 10,000, and 100,000 metadata records. Initial targets: local catalog p95 below 100 ms, shortlist no larger than 12, normally no more than three full skills loaded, router prompt below 8,000 tokens, and incremental updates.

Measure top-1 accuracy, correct no-skill choices, composition accuracy, gap precision, unnecessary selection, routing tokens, completion rate, false positives, reroute count, and overrides.

## MVP acceptance

Measured by `tests/` (run with `HERMES_AGENT_SRC` pointing at the pinned hermes-agent checkout); the
numbered criteria A1–A13 in `docs/meta-skill-router-integration-plan.md` section 11 are the contract.

1. Detect a new trusted skill without router-code changes (`test_catalog.py`).
2. Route using metadata before selection: ≤4 KB read per SKILL.md, bodies never enter the prompt (`test_catalog.py`, `test_selector.py`).
3. Load full instructions only for selected skills: active-mode gating, advisory-mode measurement (`test_engine.py`).
4. Pass golden no/one/sequential-multi/gap/pinned/skipped cases (`test_engine.py`).
5. Reject untrusted or ineligible top matches (`test_eligibility.py`).
6. Typed artifacts between two skills — moved to V2 (`delegate_task.output_schema`).
7. Perform exactly one bounded reroute; the second call is `budget_exhausted` without an LLM call (`test_engine.py`).
8. Stop on exhausted budgets: skills-per-turn and reroutes-per-turn (`test_engine.py`).
9. Return a valid `capability-gap.v1` object (`test_engine.py`).
10. Produce a reconstructable, secret-redacted trace (`test_engine.py`, `test_state_trace_config.py`).
11. Fail open: selector errors and bad JSON yield `NO_SKILL` and the turn continues (`test_selector.py`, `test_engine.py`).
12. Load through Hermes' real PluginManager and dispatch through its hook and registry paths (`test_plugin_registration.py`).
