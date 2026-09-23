"""Typed records the router passes between stages, plus the JSON schema the selector LLM must satisfy.

Everything here is plain data (dataclasses + dicts) so it can be traced, snapshotted, and validated
without importing Hermes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "meta-skill-router.v1"

DECISION_NO_SKILL = "NO_SKILL"
DECISION_SELECT = "SELECT_SKILLS"
DECISION_GAP = "CAPABILITY_GAP"
DECISION_PINNED = "PINNED"      # explicit /skill invocation detected; router stands down
DECISION_SKIPPED = "SKIPPED"    # gated out (platform, short message, no catalog, ...)
LLM_DECISIONS = (DECISION_NO_SKILL, DECISION_SELECT, DECISION_GAP)
ALL_DECISIONS = LLM_DECISIONS + (DECISION_PINNED, DECISION_SKIPPED)

TRUST_CORE = "core"
TRUST_APPROVED = "approved"
TRUST_APPROVED_LOCAL = "approved-local"
TRUST_UNTRUSTED = "untrusted"
TRUST_QUARANTINED = "quarantined"


@dataclass
class SkillManifest:
    """Routing view of one skill, derived from SKILL.md frontmatter (section 8.3 of the plan)."""

    id: str
    name: str
    description: str = ""
    version: str = ""
    category: str = ""
    source: str = "local"           # project | local | external | plugin
    path: str = ""                  # SKILL.md path (or plugin skill path)
    skill_dir: str = ""
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    related_skills: List[str] = field(default_factory=list)
    requires_tools: List[str] = field(default_factory=list)
    requires_toolsets: List[str] = field(default_factory=list)
    fallback_for_tools: List[str] = field(default_factory=list)
    fallback_for_toolsets: List[str] = field(default_factory=list)
    session_platforms: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    requires_apps: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    credential_files: List[str] = field(default_factory=list)
    trust: str = TRUST_APPROVED_LOCAL
    provenance: str = "local"
    fingerprint: str = ""           # stat-based; content digests are deferred (plan 8.3)
    disabled: bool = False
    frontmatter: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("frontmatter", None)
        return d

    def search_text(self) -> Dict[str, str]:
        """Field -> text used by retrieval (weights live in retrieval.py)."""
        return {
            "name": f"{self.name} {self.name.replace('-', ' ').replace('_', ' ')}",
            "tags": " ".join(self.tags),
            "triggers": " ".join(self.triggers),
            "description": self.description,
            "category": self.category.replace("/", " ").replace("-", " "),
        }

    def candidate_view(self, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
        """Metadata handed to the selector: never the skill body."""
        view: Dict[str, Any] = {"name": self.name, "description": self.description[:1024], "category": self.category}
        if self.tags:
            view["tags"] = self.tags[:12]
        if self.triggers:
            view["triggers"] = self.triggers[:8]
        if warnings:
            view["warnings"] = warnings
        return view


@dataclass
class TaskIntent:
    text: str
    open_todos: List[str] = field(default_factory=list)
    session_id: str = ""
    turn_id: str = ""
    platform: str = ""
    explicit_skill_names: List[str] = field(default_factory=list)

    @property
    def query(self) -> str:
        return " ".join([self.text, *self.open_todos]).strip()

    @property
    def intent_hash(self) -> str:
        return hashlib.sha256(self.query.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass
class Candidate:
    manifest: SkillManifest
    score: float
    warnings: List[str] = field(default_factory=list)


@dataclass
class Rejection:
    name: str
    reasons: List[str]


@dataclass
class SelectedSkill:
    name: str
    reason: str = ""
    order: int = 0


@dataclass
class RoutingDecision:
    decision: str
    selected: List[SelectedSkill] = field(default_factory=list)
    confidence: str = "low"                 # high | medium | low
    missing_capabilities: List[str] = field(default_factory=list)
    rationale: str = ""
    error: str = ""
    dropped: List[str] = field(default_factory=list)   # LLM picks removed by validation

    def selected_names(self) -> List[str]:
        return [s.name for s in sorted(self.selected, key=lambda s: s.order)]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityGap:
    requested_outcome: str
    missing_capabilities: List[str]
    available_partial_capabilities: List[str] = field(default_factory=list)
    reason: str = ""
    safe_fallbacks: List[str] = field(default_factory=list)
    skill_discovery_allowed: bool = False
    requires_user_action: bool = True
    type: str = "capability-gap.v1"
    status: str = "unresolved"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# JSON schema the selector must satisfy. ``additionalProperties: false`` and explicit enums keep
# the answer parseable by strict providers; validation in selector.py is the real gate.
def selection_json_schema(max_selected: int) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision", "selected", "confidence"],
        "properties": {
            "decision": {"type": "string", "enum": list(LLM_DECISIONS)},
            "selected": {
                "type": "array",
                "maxItems": max(1, int(max_selected)),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "reason"],
                    "properties": {
                        "name": {"type": "string"},
                        "reason": {"type": "string", "maxLength": 200},
                    },
                },
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "missing_capabilities": {"type": "array", "items": {"type": "string", "maxLength": 120}},
            "rationale": {"type": "string", "maxLength": 300},
        },
    }
