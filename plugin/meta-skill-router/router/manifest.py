"""SKILL.md frontmatter -> :class:`SkillManifest` (plan section 8.3).

Only the head of each file is read (``HEAD_BYTES``, extended once to ``HEAD_BYTES_MAX`` when the
closing fence is not in the first chunk). The body is never loaded here; ``skill_view`` stays the only
loader. Hermes' own parser is used when importable so the two agree on edge cases; a YAML fallback
keeps the module usable in isolation."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .schemas import (
    SkillManifest, TRUST_APPROVED, TRUST_APPROVED_LOCAL, TRUST_CORE, TRUST_QUARANTINED, TRUST_UNTRUSTED,
)

logger = logging.getLogger(__name__)

HEAD_BYTES = 4096
HEAD_BYTES_MAX = 16384
MAX_NAME_LENGTH = 64          # mirrors tools.skills_tool_plugin.MAX_NAME_LENGTH
MAX_DESCRIPTION_LENGTH = 1024  # mirrors tools.skills_tool_plugin.MAX_DESCRIPTION_LENGTH
OVERLAY_FILENAME = "skill.manifest.yaml"

_TRUST_RANK = {TRUST_QUARANTINED: 0, TRUST_UNTRUSTED: 1, TRUST_APPROVED_LOCAL: 2, TRUST_APPROVED: 3, TRUST_CORE: 4}


# ---------------------------------------------------------------------------
# Reading and parsing
# ---------------------------------------------------------------------------

def read_head(path: Path) -> Tuple[str, int]:
    """Return only the frontmatter fence and its byte count; never retain body text."""
    lines: List[bytes] = []
    total = 0
    with open(path, "rb", buffering=0) as fh:
        first = fh.readline(HEAD_BYTES_MAX + 1)
        total += len(first)
        if first.lstrip(b"\xef\xbb\xbf").rstrip(b"\r\n") != b"---":
            return "", total
        lines.append(first)
        while total < HEAD_BYTES_MAX:
            line = fh.readline(HEAD_BYTES_MAX - total + 1)
            if not line:
                break
            total += len(line)
            lines.append(line)
            if line.rstrip(b"\r\n") == b"---":
                return b"".join(lines).decode("utf-8", "replace"), total
    return b"".join(lines).decode("utf-8", "replace"), total


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Hermes' parser when available (same edge cases as skills_list), else a YAML fallback."""
    try:
        from agent.skill_utils import parse_frontmatter as _hermes_parse
        fm, body = _hermes_parse(text)
        return (fm if isinstance(fm, dict) else {}), body
    except ImportError:
        pass
    return _fallback_parse(text)


def _fallback_parse(text: str) -> Tuple[Dict[str, Any], str]:
    stripped = text.lstrip("﻿")
    if not stripped.startswith("---"):
        return {}, text
    end = stripped.find("\n---", 3)
    if end < 0:
        return {}, text
    block = stripped[3:end]
    rest = stripped[end + 4:]
    try:
        import yaml
        loaded = yaml.safe_load(block)
        return (loaded if isinstance(loaded, dict) else {}), rest
    except Exception:
        fm: Dict[str, Any] = {}
        for line in block.splitlines():
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        return fm, rest


def _as_list(value: Any) -> List[str]:
    """Frontmatter lists come as YAML lists, ``"[a, b]"`` strings, or ``"a, b"``."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [p.strip().strip("\"'") for p in s.split(",") if p.strip()]


def _hermes_meta(fm: Dict[str, Any]) -> Dict[str, Any]:
    meta = fm.get("metadata")
    hermes = meta.get("hermes") if isinstance(meta, dict) else None
    return hermes if isinstance(hermes, dict) else {}


def _env_var_names(fm: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    prereq = fm.get("prerequisites")
    if isinstance(prereq, dict):
        names += _as_list(prereq.get("env_vars"))
    for item in fm.get("required_environment_variables") or []:
        if isinstance(item, dict) and item.get("name") and not item.get("optional"):
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return list(dict.fromkeys(names))


def _commands(fm: Dict[str, Any]) -> List[str]:
    prereq = fm.get("prerequisites")
    return _as_list(prereq.get("commands")) if isinstance(prereq, dict) else []


# ---------------------------------------------------------------------------
# Provenance and trust
# ---------------------------------------------------------------------------

def provenance_for(name: str, source: str) -> str:
    """``bundled | hub | agent | plugin | project | external | local`` using Hermes' sidecars when present."""
    if source == "plugin":
        return "plugin"
    if source in ("project", "external"):
        return source
    try:
        from tools import skill_usage
        if skill_usage.is_bundled(name):
            return "bundled"
        if skill_usage.is_hub_installed(name):
            return "hub"
        if skill_usage.is_agent_created(name):
            return "agent"
    except Exception:
        logger.debug("provenance probe unavailable for %s", name, exc_info=True)
    return "local"


def trust_for(provenance: str) -> str:
    return {
        "bundled": TRUST_CORE,
        "hub": TRUST_APPROVED,        # hub installs passed skills_guard at install time
        "plugin": TRUST_APPROVED,     # an enabled plugin is operator-approved code
        "agent": TRUST_APPROVED_LOCAL,
        "project": TRUST_APPROVED_LOCAL,  # trusted project dirs are opt-in and scanned
        "external": TRUST_APPROVED_LOCAL,
        "local": TRUST_APPROVED_LOCAL,
    }.get(provenance, TRUST_UNTRUSTED)


def fingerprint_for(path: Path) -> str:
    try:
        st = os.stat(path)
        raw = f"{path}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        raw = str(path)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def category_for(skill_md: Path, root: Path) -> str:
    """``root/<cat>/<name>/SKILL.md`` -> ``cat``; deeper -> ``a/b``; a top-level ``<name>/SKILL.md`` ->
    ``general`` (the ``skills_list`` rule: a category needs at least three path parts)."""
    try:
        parts = skill_md.relative_to(root).parts
    except ValueError:
        return "general"
    if len(parts) >= 3 and parts[0] == "_org":
        parts = parts[2:]
    if len(parts) <= 2:
        return "general"
    return "/".join(parts[:-2])


def manifest_from_frontmatter(
    fm: Dict[str, Any], _body: str, *, path: Path, source: str, category: str = "", disabled: bool = False,
) -> SkillManifest:
    skill_dir = path.parent
    raw_name = str(fm.get("name") or skill_dir.name).strip()[:MAX_NAME_LENGTH]
    description = str(fm.get("description") or "").strip().strip("'\"")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        description = description[: MAX_DESCRIPTION_LENGTH - 3] + "..."
    hm = _hermes_meta(fm)
    tags = _as_list(hm.get("tags")) or _as_list(fm.get("tags"))
    triggers = _as_list(fm.get("triggers")) or _as_list(hm.get("triggers"))
    related = _as_list(hm.get("related_skills")) or _as_list(fm.get("related_skills"))
    provenance = provenance_for(raw_name, source)
    ident = f"{provenance}:{category}/{raw_name}" if category and category != "general" else f"{provenance}:{raw_name}"
    if source == "plugin":
        ident = f"plugin:{raw_name}"
    return SkillManifest(
        id=ident, name=raw_name, description=description, version=str(fm.get("version") or ""),
        category=category or "general", source=source, path=str(path), skill_dir=str(skill_dir),
        tags=tags, triggers=triggers, related_skills=related,
        requires_tools=_as_list(hm.get("requires_tools")), requires_toolsets=_as_list(hm.get("requires_toolsets")),
        fallback_for_tools=_as_list(hm.get("fallback_for_tools")),
        fallback_for_toolsets=_as_list(hm.get("fallback_for_toolsets")),
        session_platforms=_as_list(hm.get("session_platforms")),
        platforms=_as_list(fm.get("platforms")), environments=_as_list(fm.get("environments")),
        requires_apps=_as_list(fm.get("requires_apps")), env_vars=_env_var_names(fm), commands=_commands(fm),
        credential_files=_as_list(fm.get("required_credential_files")),
        trust=trust_for(provenance), provenance=provenance, fingerprint=fingerprint_for(path),
        disabled=disabled, frontmatter=fm,
    )


def manifest_from_path(path: Path, *, root: Path, source: str, disabled: bool = False) -> Tuple[SkillManifest, int]:
    """Parse one SKILL.md head. Returns ``(manifest, bytes_read)``."""
    text, n = read_head(path)
    fm, body = parse_frontmatter(text)
    manifest = manifest_from_frontmatter(fm, body, path=path, source=source, category=category_for(path, root), disabled=disabled)
    overlay = path.parent / OVERLAY_FILENAME
    if overlay.is_file():
        try:
            apply_overlay(manifest, overlay)
        except Exception:
            logger.debug("overlay ignored for %s", path, exc_info=True)
    return manifest, n


def manifest_from_plugin_entry(entry: Dict[str, Any]) -> SkillManifest:
    """``PluginManager.list_plugin_skill_metadata()`` row -> manifest (name is ``plugin:skill``)."""
    fm = dict(entry.get("frontmatter") or {})
    name = str(entry.get("name") or fm.get("name") or "").strip()
    fm.setdefault("name", name)
    fm.setdefault("description", entry.get("description", ""))
    fake_path = Path(str(entry.get("path") or f"plugin/{name}/SKILL.md"))
    return manifest_from_frontmatter(fm, "", path=fake_path, source="plugin", category="plugin")


def apply_overlay(manifest: SkillManifest, overlay_path: Path) -> SkillManifest:
    """Optional ``skill.manifest.yaml`` next to SKILL.md (this repo's contract). Adds routing metadata;
    never raises trust above what provenance established."""
    import yaml
    data = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return manifest
    routing = data.get("routing") or {}
    if isinstance(routing, dict):
        manifest.tags = list(dict.fromkeys(manifest.tags + _as_list(routing.get("capabilities")) + _as_list(routing.get("tags"))))
        manifest.triggers = list(dict.fromkeys(
            manifest.triggers + _as_list(routing.get("intents")) + _as_list(routing.get("positive_triggers"))))
    reqs = data.get("requirements") or {}
    if isinstance(reqs, dict):
        manifest.requires_tools = list(dict.fromkeys(manifest.requires_tools + _as_list(reqs.get("tools"))))
        manifest.env_vars = list(dict.fromkeys(manifest.env_vars + _as_list(reqs.get("credentials"))))
    identity = data.get("identity") or {}
    if isinstance(identity, dict) and identity.get("version") and not manifest.version:
        manifest.version = str(identity["version"])
    security = data.get("security") or {}
    requested = str(security.get("trust_requirement") or "").strip() if isinstance(security, dict) else ""
    if requested in _TRUST_RANK and _TRUST_RANK[requested] < _TRUST_RANK.get(manifest.trust, 0):
        manifest.trust = requested  # an overlay may only lower trust
    return manifest


def dedupe_first_wins(manifests: Iterable[SkillManifest]) -> List[SkillManifest]:
    """Same rule as skills_list: first occurrence of a name wins (scan order = project > local > external)."""
    seen: set = set()
    out: List[SkillManifest] = []
    for m in manifests:
        if m.name in seen:
            continue
        seen.add(m.name)
        out.append(m)
    return out
