from router.governance import apply_governance_registry, load_governance_registry
from router.schemas import SkillManifest


def _m(name: str) -> SkillManifest:
    return SkillManifest(id=f"local:{name}", name=name, description="test")


def test_registry_never_creates_phantom_candidates():
    registry = {
        "missing-skill": {
            "capability_id": "missing.capability",
            "aliases": ["ghost"],
            "routing_policy": "allow_if_discovered",
        }
    }
    out = apply_governance_registry([_m("real-skill")], registry)
    assert [m.name for m in out] == ["real-skill"]


def test_alias_can_match_discovered_skill_and_add_metadata():
    registry = {
        "canonical-skill": {
            "capability_id": "example.capability",
            "aliases": ["legacy-skill"],
            "positive_triggers": ["do the specialized thing"],
            "negative_triggers": ["not for generic tasks"],
            "routing_policy": "allow_if_discovered",
        }
    }
    [manifest] = apply_governance_registry([_m("legacy-skill")], registry)
    assert manifest.capability_id == "example.capability"
    assert "canonical-skill" not in manifest.aliases
    assert "legacy-skill" in manifest.aliases
    assert "do the specialized thing" in manifest.triggers
    assert "not for generic tasks" in manifest.negative_triggers
    assert manifest.disabled is False


def test_blocked_policy_disables_only_discovered_match():
    registry = {
        "opaque-skill": {
            "capability_id": "opaque",
            "routing_policy": "blocked_until_audited",
        }
    }
    [manifest] = apply_governance_registry([_m("opaque-skill")], registry)
    assert manifest.disabled is True
    assert manifest.routing_policy == "blocked_until_audited"


def test_default_registry_is_overlay_only():
    registry = load_governance_registry()
    assert "Revenue Cycle" in registry
    assert registry["Revenue Cycle"]["routing_policy"] == "blocked_until_audited"
