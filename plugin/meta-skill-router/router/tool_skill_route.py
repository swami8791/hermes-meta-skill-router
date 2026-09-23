"""``skill_route`` tool: the model's one bounded reroute per turn (plan 9.1 #12)."""

from __future__ import annotations

import json
from typing import Any, Dict

from .engine import Router

SKILL_ROUTE_SCHEMA: Dict[str, Any] = {
    "name": "skill_route",
    "description": (
        "Re-route the CURRENT request to installed skills when a requirement is still unmet after the "
        "skills you were told to load. Pass the remaining requirement in plain language. Returns the skills to "
        "load next (call skill_view for each), a capability gap when nothing installed applies, or "
        "budget_exhausted when this turn's reroute allowance is used. Never installs anything."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "remaining_requirement": {
                "type": "string",
                "description": "What still needs to be done that the loaded skills do not cover.",
            },
            "tried_skills": {
                "type": "array", "items": {"type": "string"},
                "description": "Optional: skill names already tried for this requirement.",
            },
        },
        "required": ["remaining_requirement"],
    },
}


def make_handler(router: Router):
    def handler(args: Dict[str, Any], **kw: Any) -> str:
        tried = args.get("tried_skills")
        if isinstance(tried, str):
            tried = [t.strip() for t in tried.split(",") if t.strip()]
        try:
            payload = router.reroute(
                session_id=str(kw.get("session_id") or ""), remaining_requirement=str(args.get("remaining_requirement") or ""),
                tried_skills=tried if isinstance(tried, list) else None, platform=str(kw.get("platform") or ""),
            )
        except Exception as exc:
            payload = {"success": False, "error": f"skill_route failed: {type(exc).__name__}"}
        return json.dumps(payload, ensure_ascii=False)
    return handler
