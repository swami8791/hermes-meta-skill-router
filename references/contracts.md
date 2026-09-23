# Router Contracts

## Skill manifest

Use `skill.manifest.yaml` as the canonical routing contract. Adapt legacy frontmatter into this form.

```yaml
schema_version: "1.0"
identity:
  id: "publisher.skill-name"
  name: "Human-readable name"
  version: "1.0.0"
  description: "Short semantic description"
  purpose: "Outcome this capability produces"
  publisher: "publisher-id"
routing:
  capabilities: ["research.web"]
  intents: ["Research current external information"]
  positive_triggers: ["Current sources are required"]
  negative_triggers: ["All source material was supplied"]
  anti_capabilities: ["authenticated-browser-control"]
interface:
  inputs:
    - {name: "research_question", type: "string", required: true}
  outputs:
    - {name: "evidence_bundle", type: "artifact/evidence-bundle.v1"}
  side_effects: ["external_network_read"]
requirements:
  tools: ["web_search"]
  credentials: []
  platforms: ["hermes"]
  dependencies: []
  incompatible_with: []
execution:
  mode: "inline"
  estimated_tokens: 4000
  estimated_latency_ms: 15000
  timeout_ms: 120000
  idempotency: "safe-to-retry"
  parallel_safe: true
  max_retries: 1
evaluation:
  success_conditions: ["Material claims retain provenance"]
  validators: ["schema", "citation-presence"]
security:
  trust_requirement: "approved"
  permission_scope: ["network.read"]
  data_classification: {maximum_input: "confidential"}
  requires_user_confirmation: []
discovery:
  tags: ["research", "web"]
  deprecated: false
  replacement: null
```

Keep reliability outside the manifest. Missing security metadata makes autonomous execution ineligible.

## Artifact envelope

```json
{
  "schema": "artifact-envelope.v1",
  "artifact_type": "evidence-bundle.v1",
  "producer": {"skill_id": "publisher.web-research", "skill_version": "1.0.0", "run_id": "run_123"},
  "status": "success",
  "data": {},
  "provenance": [],
  "warnings": [],
  "quality": {"schema_valid": true, "confidence": 0.91}
}
```

## Execution plan

```json
{
  "schema": "execution-plan.v1",
  "decision": "SELECT_SKILLS",
  "intent_id": "intent_123",
  "confidence": {"score": 0.88, "evidence": ["retrieval_agreement", "inputs_ready"]},
  "nodes": [{
    "id": "node_1",
    "skill_id": "publisher.web-research",
    "skill_version": "1.0.0",
    "depends_on": [],
    "input_artifacts": [],
    "expected_output": "artifact/evidence-bundle.v1",
    "permission_scope": ["network.read"],
    "timeout_ms": 120000,
    "retry": {"maximum": 1, "idempotent_only": true},
    "success_conditions": ["Output schema validates"]
  }],
  "budgets": {"routing_passes_remaining": 3, "skills_remaining": 7}
}
```

## Capability gap

```json
{
  "type": "capability-gap.v1",
  "status": "unresolved",
  "requested_outcome": "Create a signed iOS archive",
  "missing_capabilities": ["ios.code-signing", "apple-developer-authentication"],
  "available_partial_capabilities": ["ios.project-analysis"],
  "reason": "No trusted eligible skill can sign or upload the application.",
  "safe_fallbacks": ["Produce signing instructions", "Validate the unsigned build"],
  "skill_discovery_allowed": false,
  "requires_user_action": true
}
```

## Completion assessment

```json
{
  "schema": "completion-assessment.v1",
  "status": "needs_capability",
  "completed_criteria": ["competitor data verified"],
  "unmet_criteria": ["comparison workbook created"],
  "routable_gaps": ["Transform verified data into a workbook"],
  "blocked_by": [],
  "progress_score": 0.5
}
```
