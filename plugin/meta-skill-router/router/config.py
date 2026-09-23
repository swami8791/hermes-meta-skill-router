"""Settings with defaults, read through ``ctx.get_config`` (``plugins.entries.meta-skill-router.settings``).

Invalid values fall back to defaults with a warning; the router must never fail closed on config."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

MODES = ("shadow", "advisory", "active")
AUX_TASK_KEY = "meta_skill_router"


@dataclass
class RouterConfig:
    mode: str = "shadow"
    max_candidates: int = 12
    max_selected: int = 3
    max_skills_per_turn: int = 5
    max_reroutes_per_turn: int = 1
    skip_platforms: List[str] = field(default_factory=lambda: ["subagent"])
    min_message_chars: int = 12
    selection_timeout_s: float = 8.0
    directive_max_chars: int = 1500
    trace_enabled: bool = True
    trace_max_bytes: int = 5 * 1024 * 1024
    protocol_section: bool = False
    allow_untrusted: bool = False
    route_aux_task: bool = True   # pass task=meta_skill_router to ctx.llm (requires registration)

    @classmethod
    def load(cls, get: Optional[Callable[[str, Any], Any]]) -> "RouterConfig":
        cfg = cls()
        if get is None:
            return cfg
        for f in fields(cls):
            default = getattr(cfg, f.name)
            try:
                raw = get(f.name, default)
            except Exception:
                raw = default
            setattr(cfg, f.name, _coerce(f.name, raw, default))
        return cfg


def _coerce(name: str, raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    try:
        if name == "mode":
            value = str(raw).strip().lower()
            if value not in MODES:
                raise ValueError(value)
            return value
        if isinstance(default, bool):
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            value = int(raw)
            if value < 0:
                raise ValueError(value)
            return value
        if isinstance(default, float):
            value = float(raw)
            if value <= 0:
                raise ValueError(value)
            return value
        if isinstance(default, list):
            if isinstance(raw, str):
                return [p.strip() for p in raw.split(",") if p.strip()]
            return [str(v).strip() for v in raw if str(v).strip()]
        return raw
    except (TypeError, ValueError):
        logger.warning("meta-skill-router: invalid setting %s=%r; using default %r", name, raw, default)
        return default
