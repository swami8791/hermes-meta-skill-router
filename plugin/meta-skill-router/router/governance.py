"""Overlay-only capability governance for dynamically discovered skills.

The registry never creates candidates. It may only annotate or restrict a SkillManifest
that the normal Hermes catalog already discovered.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .schemas import SkillManifest

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry" / "capability_registry.json"
BLOCKING_POLICIES = {"exclude", "blocked", "blocked_until_audited"}


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def load_governance_registry(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load the overlay registry. Invalid/missing data fails open as an empty registry."""
    registry_path = path or DEFAULT_REGISTRY_PATH
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("meta-skill-router: governance registry unreadable", exc_info=True)
        return {}
    if not isinstance(data, dict) or data.get("mode") != "overlay_only":
        return {}
    skills = data.get("skills")
    return skills if isinstance(skills, dict) else {}


def apply_governance(manifest: SkillManifest, entry: Dict[str, Any]) -> SkillManifest:
    """Apply one registry entry without widening trust or inventing prerequisites."""
    manifest.capability_id = str(entry.get("capability_id") or "").strip()
    manifest.aliases = list(dict.fromkeys(manifest.aliases + _as_list(entry.get("aliases"))))
    manifest.negative_triggers = list(
        dict.fromkeys(manifest.negative_triggers + _as_list(entry.get("negative_triggers")))
    )
    manifest.routing_policy = str(entry.get("routing_policy") or "allow_if_discovered").strip()

    positives = _as_list(entry.get("positive_triggers"))
    manifest.triggers = list(dict.fromkeys(manifest.triggers + positives))

    if manifest.routing_policy in BLOCKING_POLICIES:
        manifest.disabled = True
    return manifest


def apply_governance_registry(
    manifests: Iterable[SkillManifest],
    registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[SkillManifest]:
    """Overlay governance onto discovered manifests only; never create phantom candidates."""
    entries = load_governance_registry() if registry is None else registry
    if not entries:
        return list(manifests)

    index: Dict[str, Dict[str, Any]] = {}
    for canonical_name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        index.setdefault(str(canonical_name), entry)
        for alias in _as_list(entry.get("aliases")):
            index.setdefault(alias, entry)

    out: List[SkillManifest] = []
    for manifest in manifests:
        entry = index.get(manifest.name)
        out.append(apply_governance(manifest, entry) if entry else manifest)
    return out
