"""Skill catalog: every routable skill's metadata, rebuilt only when the skill directories change.

Sources, in first-wins order (same precedence as ``skills_list``): trusted project dirs (through Hermes'
quarantine chokepoint), the profile skills dir, ``skills.create_dir`` / ``skills.external_dirs``, and
plugin-registered skills. The change signature is the stat rule ``tools/skills_tool.py`` uses (each
scan dir plus its immediate children), so adding a skill inside a category is noticed."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .manifest import dedupe_first_wins, manifest_from_path, manifest_from_plugin_entry
from .schemas import SkillManifest

logger = logging.getLogger(__name__)

TTL_SECONDS = 30.0  # bounds staleness from in-place SKILL.md edits (mirrors skills_tool)


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home()


def scan_dirs() -> Tuple[List[Path], List[Path]]:
    """``(project_dirs, all_dirs)`` using Hermes' public resolvers; degrades to ``<HERMES_HOME>/skills``."""
    project: List[Path] = []
    others: List[Path] = []
    with suppress(Exception):
        from agent.skill_utils import get_project_skills_dirs
        project = [Path(p) for p in get_project_skills_dirs()]
    try:
        from agent.skill_utils import get_all_skills_dirs
        others = [Path(p) for p in get_all_skills_dirs()]
    except Exception:
        with suppress(Exception):
            others = [_hermes_home() / "skills"]
    all_dirs = project + [d for d in others if d not in project]
    return project, [d for d in all_dirs if d.exists()]


ESSENTIAL_SKILLS = {"hermes-agent"}  # mirrors agent.skill_utils.ESSENTIAL_SKILLS


def _as_set(value: Any) -> set:
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    try:
        return {str(v).strip() for v in value if str(v).strip()}
    except TypeError:
        return set()


def disabled_names(platform: Optional[str] = None) -> set:
    """``skills.disabled`` ∪ ``skills.platform_disabled.<platform>`` via Hermes; falls back to reading
    ``<HERMES_HOME>/config.yaml`` directly when Hermes' helper cannot be imported (its import chain
    pulls the gateway package)."""
    try:
        from agent.skill_utils import get_disabled_skill_names
        return set(get_disabled_skill_names(platform or None))
    except Exception:
        logger.debug("get_disabled_skill_names unavailable; reading config.yaml directly", exc_info=True)
    try:
        import yaml
        cfg = yaml.safe_load((_hermes_home() / "config.yaml").read_text(encoding="utf-8")) or {}
        skills = cfg.get("skills") if isinstance(cfg, dict) else None
        if not isinstance(skills, dict):
            return set()
        disabled = _as_set(skills.get("disabled"))
        per_platform = skills.get("platform_disabled") or {}
        if platform and isinstance(per_platform, dict):
            disabled |= _as_set(per_platform.get(platform))
        return disabled - ESSENTIAL_SKILLS
    except Exception:
        return set()


def scan_signature(dirs: Iterable[Path], disabled: Iterable[str], platform: str) -> tuple:
    sig = []
    for d in dirs:
        try:
            m = d.stat().st_mtime
        except OSError:
            continue
        with suppress(OSError), os.scandir(d) as it:
            for entry in it:
                with suppress(OSError):
                    if entry.is_dir(follow_symlinks=False):
                        m = max(m, entry.stat(follow_symlinks=False).st_mtime)
        sig.append((str(d), m))
    return tuple(sig), frozenset(disabled), platform


def _iter_skill_files(root: Path, *, project: bool):
    """Hermes' walkers (quarantine-aware for project dirs); a plain walk if they are unavailable."""
    try:
        if project:
            from agent.skill_utils import iter_project_skill_files
            yield from iter_project_skill_files(root)
        else:
            from agent.skill_utils import iter_skill_index_files
            yield from iter_skill_index_files(root, "SKILL.md")
        return
    except ImportError:
        pass
    excluded = {".git", ".hub", ".archive", ".curator_backups", ".locks", "venv", "node_modules", "__pycache__",
                "references", "templates", "assets", "scripts"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in excluded)
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"


def _plugin_skill_entries() -> List[Dict[str, Any]]:
    try:
        from hermes_cli.plugins import get_plugin_manager
        return list(get_plugin_manager().list_plugin_skill_metadata())
    except Exception:
        logger.debug("plugin skill listing unavailable", exc_info=True)
        return []


class SkillCatalog:
    """Thread-safe, signature-cached catalog. ``entries()`` returns manifests (disabled ones included,
    flagged) so eligibility can explain rejections."""

    def __init__(self, *, ttl_seconds: float = TTL_SECONDS, include_plugin_skills: bool = True) -> None:
        self._ttl = ttl_seconds
        self._include_plugins = include_plugin_skills
        self._lock = threading.Lock()
        self._entries: List[SkillManifest] = []
        self._signature: Optional[tuple] = None
        self._built_at = 0.0
        self.last_build: Dict[str, Any] = {}

    def entries(self, platform: str = "", *, force: bool = False) -> List[SkillManifest]:
        project_dirs, all_dirs = scan_dirs()
        disabled = disabled_names(platform)
        signature = scan_signature(all_dirs, disabled, platform)
        now = time.monotonic()
        with self._lock:
            fresh = (not force and self._signature == signature and (now - self._built_at) < self._ttl)
            if fresh:
                return list(self._entries)
            self._entries = self._build(project_dirs, all_dirs, disabled)
            self._signature, self._built_at = signature, now
            return list(self._entries)

    def by_name(self, name: str, platform: str = "") -> Optional[SkillManifest]:
        for m in self.entries(platform):
            if m.name == name or m.id == name:
                return m
        return None

    def names(self, platform: str = "") -> List[str]:
        return [m.name for m in self.entries(platform)]

    def _build(self, project_dirs: List[Path], all_dirs: List[Path], disabled: set) -> List[SkillManifest]:
        started = time.monotonic()
        found: List[SkillManifest] = []
        bytes_read = 0
        files = 0
        external: set = set()
        with suppress(Exception):
            from agent.skill_utils import get_external_skills_dirs
            external = {Path(p) for p in get_external_skills_dirs()}
        for root in all_dirs:
            is_project = root in project_dirs
            source = "project" if is_project else ("external" if root in external else "local")
            for skill_md in _iter_skill_files(root, project=is_project):
                files += 1
                try:
                    manifest, n = manifest_from_path(Path(skill_md), root=root, source=source)
                except Exception:
                    logger.debug("skipping unparseable skill %s", skill_md, exc_info=True)
                    continue
                bytes_read += n
                manifest.disabled = manifest.name in disabled
                found.append(manifest)
        if self._include_plugins:
            for entry in _plugin_skill_entries():
                with suppress(Exception):
                    m = manifest_from_plugin_entry(entry)
                    m.disabled = m.name in disabled
                    found.append(m)
        entries = dedupe_first_wins(found)
        self.last_build = {
            "files": files, "bytes_read": bytes_read, "entries": len(entries),
            "duration_ms": int((time.monotonic() - started) * 1000), "dirs": [str(d) for d in all_dirs],
        }
        logger.debug("meta-skill-router catalog built: %s", self.last_build)
        return entries
