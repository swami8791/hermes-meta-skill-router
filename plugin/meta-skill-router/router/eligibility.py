"""Deterministic eligibility filters (plan section 9.1 #5).

Rejections are hard (the skill never reaches the selector); warnings ride along as candidate metadata
(missing credentials: the skill can still be selected, and ``skill_view`` prompts for the secret)."""

from __future__ import annotations

import logging
import sys
from contextlib import suppress
from typing import Dict, List, Optional, Sequence, Tuple

from .schemas import Rejection, SkillManifest, TRUST_QUARANTINED, TRUST_UNTRUSTED

logger = logging.getLogger(__name__)

_PLATFORM_MAP = {"macos": "darwin", "linux": "linux", "windows": "win32"}


class PolicyContext:
    """Read-only view of what the session may use. ``available_tools=None`` means unknown (fail open)."""

    def __init__(self, *, platform: str = "", available_tools: Optional[set] = None,
                 available_toolsets: Optional[set] = None, allow_untrusted: bool = False) -> None:
        self.platform = platform or ""
        self.available_tools = available_tools
        self.available_toolsets = available_toolsets
        self.allow_untrusted = allow_untrusted


def approximate_available_tools(platform: str) -> Tuple[Optional[set], Optional[set]]:
    """Best-effort tool set for *platform* from the static toolset table. The exact per-session set
    is not in the ``pre_llm_call`` payload (plan 6.9); ``None`` when it cannot be derived."""
    if not platform:
        return None, None
    try:
        import toolsets as _ts
        bundle = f"hermes-{platform}" if not platform.startswith("hermes-") else platform
        if bundle not in _ts.TOOLSETS:
            return None, None
        tools = set(_ts.resolve_toolset(bundle, include_registry=False))
        if not tools:
            return None, None
        sets = set()
        with suppress(Exception):
            from model_tools import get_toolset_for_tool
            sets = {get_toolset_for_tool(t) for t in tools} - {None, ""}
        return tools, (sets or None)
    except Exception:
        logger.debug("tool availability approximation failed for %s", platform, exc_info=True)
        return None, None


def _host_platform_ok(m: SkillManifest) -> bool:
    if not m.platforms:
        return True
    wanted = {_PLATFORM_MAP.get(str(p).lower(), str(p).lower()) for p in m.platforms}
    return sys.platform in wanted or any(sys.platform.startswith(w) for w in wanted)


def _hermes_platform_ok(m: SkillManifest) -> bool:
    """Prefer Hermes' own gates (environment/app probes) when importable."""
    try:
        from agent.skill_utils import skill_matches_apps, skill_matches_environment, skill_matches_platform
        fm = m.frontmatter or {"platforms": m.platforms, "environments": m.environments, "requires_apps": m.requires_apps}
        return bool(skill_matches_platform(fm) and skill_matches_environment(fm) and skill_matches_apps(fm))
    except ImportError:
        return _host_platform_ok(m)


def _persisted_env(names: Sequence[str]) -> Dict[str, bool]:
    """Which required env vars are present in the profile .env or the process environment."""
    import os
    env: Dict[str, str] = {}
    with suppress(Exception):
        from agent.secret_scope import load_env_file
        from hermes_constants import get_hermes_home
        env = dict(load_env_file(get_hermes_home() / ".env") or {})
    return {n: bool(env.get(n) or os.environ.get(n)) for n in names}


def evaluate(m: SkillManifest, policy: PolicyContext) -> Tuple[bool, List[str], List[str]]:
    """``(eligible, rejection_reasons, warnings)``."""
    reasons: List[str] = []
    warnings: List[str] = []
    if m.disabled:
        reasons.append("disabled_in_config")
    if m.trust == TRUST_QUARANTINED:
        reasons.append("quarantined")
    if m.trust == TRUST_UNTRUSTED and not policy.allow_untrusted:
        reasons.append("untrusted")
    if not _hermes_platform_ok(m):
        reasons.append("platform_mismatch")
    if m.session_platforms and policy.platform:
        if policy.platform.lower() not in {p.lower() for p in m.session_platforms}:
            reasons.append("session_platform_mismatch")
    tools, sets = policy.available_tools, policy.available_toolsets
    if tools is not None:
        missing = [t for t in m.requires_tools if t not in tools]
        if missing:
            reasons.append("requires_tools_missing:" + ",".join(missing))
        if any(t in tools for t in m.fallback_for_tools):
            reasons.append("fallback_primary_available")
    if sets is not None:
        missing_sets = [s for s in m.requires_toolsets if s not in sets]
        if missing_sets:
            reasons.append("requires_toolsets_missing:" + ",".join(missing_sets))
        if any(s in sets for s in m.fallback_for_toolsets):
            reasons.append("fallback_primary_toolset_available")
    if m.env_vars:
        present = _persisted_env(m.env_vars)
        missing_env = [n for n, ok in present.items() if not ok]
        if missing_env:
            warnings.append("missing_env:" + ",".join(missing_env))
    if m.credential_files:
        warnings.append("credential_files_required")
    return (not reasons), reasons, warnings


def filter_eligible(manifests: Sequence[SkillManifest], policy: PolicyContext) -> Tuple[List[SkillManifest], Dict[str, List[str]], List[Rejection]]:
    """``(eligible, warnings_by_name, rejections)``."""
    eligible: List[SkillManifest] = []
    warnings_by_name: Dict[str, List[str]] = {}
    rejections: List[Rejection] = []
    for m in manifests:
        ok, reasons, warnings = evaluate(m, policy)
        if ok:
            eligible.append(m)
            if warnings:
                warnings_by_name[m.name] = warnings
        else:
            rejections.append(Rejection(name=m.name, reasons=reasons))
    return eligible, warnings_by_name, rejections
