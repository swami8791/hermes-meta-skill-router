"""Hermes hook handlers bound to a :class:`Router`. Every handler accepts ``**kwargs`` (payloads are
additive) and never raises into the agent loop."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .engine import Router

logger = logging.getLogger(__name__)

SKILL_VIEW = "skill_view"


class Hooks:
    def __init__(self, router: Router) -> None:
        self.router = router

    def on_pre_llm_call(self, *, session_id: str = "", task_id: str = "", turn_id: str = "", user_message: Any = None,
                        conversation_history: Any = None, is_first_turn: bool = False, model: str = "",
                        platform: str = "", **_: Any) -> Optional[Dict[str, str]]:
        try:
            result = self.router.route_turn(user_message=user_message, history=conversation_history,
                                            session_id=session_id or "", turn_id=turn_id or task_id or "",
                                            platform=platform or "")
            return result.context
        except Exception:
            logger.warning("meta-skill-router pre_llm_call failed", exc_info=True)
            return None

    def on_pre_tool_call(self, *, tool_name: str = "", args: Any = None, session_id: str = "", turn_id: str = "",
                         **_: Any) -> Optional[Dict[str, str]]:
        if tool_name != SKILL_VIEW:
            return None
        try:
            return self.router.before_skill_view(args=args if isinstance(args, dict) else {},
                                                 session_id=session_id or "", turn_id=turn_id or "")
        except Exception:
            logger.warning("meta-skill-router pre_tool_call failed", exc_info=True)
            return None

    def on_post_tool_call(self, *, tool_name: str = "", args: Any = None, session_id: str = "", turn_id: str = "",
                          status: Optional[str] = None, **_: Any) -> None:
        if tool_name != SKILL_VIEW:
            return None
        try:
            self.router.after_skill_view(args=args if isinstance(args, dict) else {}, session_id=session_id or "",
                                         status=status, turn_id=turn_id or "")
        except Exception:
            logger.warning("meta-skill-router post_tool_call failed", exc_info=True)
        return None

    def on_session_end(self, *, session_id: str = "", **_: Any) -> None:
        try:
            self.router.close_turn(session_id=session_id or "")
        except Exception:
            logger.warning("meta-skill-router on_session_end failed", exc_info=True)
        return None
