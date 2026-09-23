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

1. Detect a new trusted skill without router-code changes.
2. Route using metadata before selection.
3. Load full instructions only for selected skills.
4. Pass golden no/one/sequential-multi cases.
5. Reject untrusted or ineligible top matches.
6. Pass typed artifacts between two skills.
7. Perform one bounded reroute.
8. Stop on no progress or exhausted budgets.
9. Return a valid capability gap.
10. Produce a reconstructable, secret-redacted trace.
