"""The router: catalog -> eligibility -> retrieval -> selection -> validation -> state + trace.

``Router`` is host-agnostic: it takes callables for config, data dir and the LLM facade so tests can
drive it without a PluginContext. ``hooks.py`` binds it to Hermes' hook payloads."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import directive as directive_mod
from .catalog import SkillCatalog
from .config import AUX_TASK_KEY, RouterConfig
from .eligibility import PolicyContext, approximate_available_tools, filter_eligible
from .retrieval import Index, explicit_mentions
from .schemas import (
    Candidate, CapabilityGap, DECISION_GAP, DECISION_NO_SKILL, DECISION_PINNED, DECISION_SELECT, DECISION_SKIPPED,
    RoutingDecision, SelectedSkill, TaskIntent,
)
from .selector import select
from .state import RouterState, TurnState
from .trace import TraceWriter

logger = logging.getLogger(__name__)

PREVIEW_CHARS = 200


@dataclass
class RouteResult:
    decision: RoutingDecision
    candidates: List[Candidate] = field(default_factory=list)
    rejections: List[Dict[str, Any]] = field(default_factory=list)
    directive: Optional[str] = None
    allowed: List[str] = field(default_factory=list)
    skipped_reason: str = ""
    latency_ms: int = 0
    trace: Optional[Dict[str, Any]] = None

    @property
    def context(self) -> Optional[Dict[str, str]]:
        return {"context": self.directive} if self.directive else None


def open_todos_from_history(history: Optional[Sequence[Any]], *, limit: int = 20) -> List[str]:
    """Pending/in-progress items from the newest ``todo_list`` tool result in the history."""
    if not history:
        return []
    for msg in reversed(list(history)):
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or '"todos"' not in content or '"revision"' not in content:
            continue
        try:
            parsed = json.loads(content)
        except ValueError:
            continue
        todos = parsed.get("todos") if isinstance(parsed, dict) else None
        if not isinstance(todos, list):
            continue
        out = [str(t.get("content", ""))[:200] for t in todos
               if isinstance(t, dict) and t.get("status") in ("pending", "in_progress") and t.get("content")]
        return out[:limit]
    return []


class Router:
    def __init__(
        self, *, config_loader: Callable[[], RouterConfig], data_dir: Callable[[], Optional[Path]],
        llm: Callable[[], Any], catalog: Optional[SkillCatalog] = None,
    ) -> None:
        self._config_loader = config_loader
        self._data_dir = data_dir
        self._llm = llm
        self.catalog = catalog or SkillCatalog()
        self.state = RouterState(data_dir)
        self.trace = TraceWriter(data_dir)
        self._index: Optional[Index] = None

    # -- wiring -------------------------------------------------------------
    @property
    def config(self) -> RouterConfig:
        try:
            cfg = self._config_loader()
        except Exception:
            logger.debug("router config load failed; defaults", exc_info=True)
            cfg = RouterConfig()
        self.trace.enabled = cfg.trace_enabled and self._data_dir() is not None
        self.trace.max_bytes = max(64 * 1024, cfg.trace_max_bytes)
        return cfg

    def index_for(self, manifests: Sequence[Any]) -> Index:
        fp = tuple((m.name, m.fingerprint) for m in manifests)
        if self._index is None or self._index.fingerprint != fp:
            self._index = Index(manifests)
        return self._index

    def policy_for(self, platform: str, cfg: RouterConfig) -> PolicyContext:
        tools, sets = approximate_available_tools(platform)
        return PolicyContext(platform=platform, available_tools=tools, available_toolsets=sets,
                             allow_untrusted=cfg.allow_untrusted)

    # -- intent ---------------------------------------------------------------
    def intent_from(self, user_message: Any, history: Optional[Sequence[Any]], *, session_id: str,
                    turn_id: str, platform: str) -> TaskIntent:
        text = directive_mod.message_text(user_message)
        return TaskIntent(text=text, open_todos=open_todos_from_history(history), session_id=session_id,
                          turn_id=turn_id, platform=platform)

    # -- decision -------------------------------------------------------------
    def decide(self, intent: TaskIntent, cfg: RouterConfig, *, exclude: Optional[set] = None,
               purpose: str = "meta-skill-router.select") -> RouteResult:
        started = time.monotonic()
        entries = self.catalog.entries(intent.platform)
        if not entries:
            return RouteResult(decision=RoutingDecision(decision=DECISION_SKIPPED), skipped_reason="no_skills")
        policy = self.policy_for(intent.platform, cfg)
        eligible, warnings_by_name, rejections = filter_eligible(entries, policy)
        intent.explicit_skill_names = explicit_mentions(eligible, intent.text)
        index = self.index_for(eligible)
        candidates = index.search(intent.query, limit=cfg.max_candidates, exclude=exclude)
        for c in candidates:
            c.warnings = warnings_by_name.get(c.manifest.name, [])
        if not candidates:
            decision = RoutingDecision(decision=DECISION_NO_SKILL, confidence="high", rationale="no_lexical_candidates")
        else:
            task = AUX_TASK_KEY if cfg.route_aux_task else None
            decision = select(self._llm(), intent, candidates, max_selected=cfg.max_selected,
                              timeout_s=cfg.selection_timeout_s, task=task, purpose=purpose)
        self._ensure_explicit(decision, intent, cfg)
        allowed = list(dict.fromkeys(decision.selected_names() + intent.explicit_skill_names))
        rej = [{"name": r.name, "reasons": r.reasons} for r in rejections[:20]]
        return RouteResult(decision=decision, candidates=candidates, rejections=rej, allowed=allowed,
                           latency_ms=int((time.monotonic() - started) * 1000))

    @staticmethod
    def _ensure_explicit(decision: RoutingDecision, intent: TaskIntent, cfg: RouterConfig) -> None:
        """A skill the user named is always selectable: promote a NO_SKILL to SELECT when mentioned."""
        if not intent.explicit_skill_names:
            return
        names = decision.selected_names()
        for n in intent.explicit_skill_names:
            if n not in names and len(decision.selected) < cfg.max_skills_per_turn:
                decision.selected.append(SelectedSkill(name=n, reason="named by the user", order=len(decision.selected) + 1))
        if decision.selected and decision.decision != DECISION_SELECT:
            decision.decision = DECISION_SELECT
            decision.confidence = "high" if decision.confidence == "low" else decision.confidence

    # -- turn entry -------------------------------------------------------------
    def route_turn(self, *, user_message: Any, history: Optional[Sequence[Any]], session_id: str, turn_id: str,
                   platform: str) -> RouteResult:
        cfg = self.config
        intent = self.intent_from(user_message, history, session_id=session_id, turn_id=turn_id, platform=platform)
        if platform and platform in cfg.skip_platforms:
            return self._finish_skip(intent, cfg, "platform_skipped")
        if directive_mod.is_pinned(intent.text):
            result = RouteResult(decision=RoutingDecision(decision=DECISION_PINNED, confidence="high"))
            return self._finish(intent, cfg, result)
        if len(intent.text.strip()) < cfg.min_message_chars:
            return self._finish_skip(intent, cfg, "message_too_short")
        try:
            result = self.decide(intent, cfg)
        except Exception as exc:  # never break the turn
            logger.warning("meta-skill-router routing failed: %s", exc, exc_info=True)
            result = RouteResult(decision=RoutingDecision(decision=DECISION_NO_SKILL, error=f"router_error:{type(exc).__name__}"))
        if result.skipped_reason:
            return self._finish_skip(intent, cfg, result.skipped_reason)
        result.directive = directive_mod.render(result.decision, mode=cfg.mode, max_chars=cfg.directive_max_chars,
                                                reroute_budget=cfg.max_reroutes_per_turn)
        return self._finish(intent, cfg, result)

    def _finish_skip(self, intent: TaskIntent, cfg: RouterConfig, reason: str) -> RouteResult:
        result = RouteResult(decision=RoutingDecision(decision=DECISION_SKIPPED), skipped_reason=reason)
        return self._finish(intent, cfg, result)

    def _finish(self, intent: TaskIntent, cfg: RouterConfig, result: RouteResult) -> RouteResult:
        if intent.session_id and result.decision.decision not in (DECISION_SKIPPED,):
            self.state.begin_turn(intent.session_id, intent.turn_id, mode=cfg.mode,
                                  decision=result.decision.decision, allowed=result.allowed)
        result.trace = self.trace.write("route.decision", intent.session_id, {
            "turn_id": intent.turn_id, "platform": intent.platform, "mode": cfg.mode,
            "intent_hash": intent.intent_hash, "intent_preview": intent.text[:PREVIEW_CHARS],
            "open_todos": len(intent.open_todos), "explicit_mentions": intent.explicit_skill_names,
            "decision": result.decision.to_dict(), "allowed": result.allowed,
            "candidates": [{"name": c.manifest.name, "score": c.score, "warnings": c.warnings} for c in result.candidates],
            "rejections": result.rejections, "skipped_reason": result.skipped_reason,
            "directive_chars": len(result.directive or ""), "latency_ms": result.latency_ms,
            "catalog": dict(self.catalog.last_build),
        })
        return result

    # -- reroute --------------------------------------------------------------
    def reroute(self, *, session_id: str, remaining_requirement: str, tried_skills: Optional[Sequence[str]] = None,
                platform: str = "") -> Dict[str, Any]:
        """One bounded reroute for the current turn. Returns a tool-result dict."""
        cfg = self.config
        turn = self.state.current(session_id) if session_id else None
        requirement = (remaining_requirement or "").strip()
        if not requirement:
            return {"success": False, "error": "remaining_requirement is required"}
        if turn is not None and turn.reroutes >= cfg.max_reroutes_per_turn:
            self.trace.write("route.reroute", session_id, {"turn_id": turn.turn_id, "status": "budget_exhausted"})
            return {"success": False, "error": "budget_exhausted",
                    "message": f"Routing budget for this turn is used ({turn.reroutes}/{cfg.max_reroutes_per_turn}). "
                               "Proceed with the skills already loaded or ask the user."}
        exclude = set(tried_skills or []) | (set(turn.loads) | set(turn.allowed) if turn else set())
        intent = TaskIntent(text=requirement, session_id=session_id, turn_id=turn.turn_id if turn else "", platform=platform)
        try:
            result = self.decide(intent, cfg, exclude=exclude, purpose="meta-skill-router.reroute")
        except Exception as exc:
            logger.warning("meta-skill-router reroute failed: %s", exc, exc_info=True)
            return {"success": False, "error": f"router_error:{type(exc).__name__}"}
        payload: Dict[str, Any]
        if result.decision.decision == DECISION_SELECT:
            payload = {"success": True, "decision": DECISION_SELECT,
                       "selected": [{"name": s.name, "reason": s.reason, "order": s.order} for s in result.decision.selected],
                       "next_step": "Load each selected skill with skill_view(name) in order, then continue."}
        elif result.decision.decision == DECISION_GAP or not result.candidates:
            gap = CapabilityGap(requested_outcome=requirement[:300],
                                missing_capabilities=result.decision.missing_capabilities or ["no installed skill matches"],
                                available_partial_capabilities=[c.manifest.name for c in result.candidates[:5]],
                                reason=result.decision.rationale or "No eligible installed skill covers the requirement.",
                                safe_fallbacks=["Use general tools and say what is missing",
                                                "Ask the user whether to search the skills hub: hermes skills search <query>"],
                                skill_discovery_allowed=False, requires_user_action=True)
            payload = {"success": True, "decision": DECISION_GAP, "capability_gap": gap.to_dict()}
        else:
            payload = {"success": True, "decision": DECISION_NO_SKILL,
                       "message": "No additional skill applies; continue with general tools.",
                       "considered": [c.manifest.name for c in result.candidates[:5]]}
        if turn is not None:
            new_allowed = result.decision.selected_names()

            def _apply(t: TurnState) -> None:
                t.reroutes += 1
                t.allowed = list(dict.fromkeys(t.allowed + new_allowed))
            self.state.update(session_id, _apply)
        self.trace.write("route.reroute", session_id, {
            "turn_id": turn.turn_id if turn else "", "requirement_preview": requirement[:PREVIEW_CHARS],
            "decision": result.decision.to_dict(),
            "candidates": [{"name": c.manifest.name, "score": c.score} for c in result.candidates],
            "status": "ok", "latency_ms": result.latency_ms,
        })
        payload["reroutes_remaining"] = max(0, cfg.max_reroutes_per_turn - ((turn.reroutes + 1) if turn else 1))
        return payload

    # -- tool-call observation ------------------------------------------------------
    @staticmethod
    def _skill_name_from_args(args: Dict[str, Any]) -> str:
        raw = str((args or {}).get("name") or "").strip()
        return raw

    @staticmethod
    def _matches(name: str, allowed: Sequence[str]) -> bool:
        if name in allowed:
            return True
        tail = name.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return any(a == tail or a.rsplit("/", 1)[-1].rsplit(":", 1)[-1] == tail for a in allowed)

    def before_skill_view(self, *, args: Dict[str, Any], session_id: str, turn_id: str = "") -> Optional[Dict[str, str]]:
        """``pre_tool_call`` decision for ``skill_view``: a block directive in active mode, else None."""
        cfg = self.config
        turn = self.state.current(session_id) if session_id else None
        name = self._skill_name_from_args(args)
        if turn is None or not name:
            return None
        if turn.decision in (DECISION_PINNED, DECISION_SKIPPED):
            return None
        selected = self._matches(name, turn.allowed) or self._matches(name, turn.loads)
        over_budget = len(turn.loads) >= cfg.max_skills_per_turn and not self._matches(name, turn.loads)
        if cfg.mode != "active" or (selected and not over_budget):
            return None
        if over_budget:
            message = (f"Skill routing: this turn already loaded {len(turn.loads)} skills "
                       f"(limit {cfg.max_skills_per_turn}). Continue with what is loaded.")
        else:
            remaining = max(0, cfg.max_reroutes_per_turn - turn.reroutes)
            message = (f"Skill routing: '{name}' was not selected for this request"
                       + (f" (selected: {', '.join(turn.allowed)})." if turn.allowed else ".")
                       + (f" Call skill_route(remaining_requirement=...) to reroute ({remaining} left)"
                          if remaining else " The reroute budget is used")
                       + ", or continue without it.")
        self.trace.write("skill.load_blocked", session_id, {"turn_id": turn.turn_id, "name": name, "reason": message})
        return {"action": "block", "message": message}

    def after_skill_view(self, *, args: Dict[str, Any], session_id: str, status: Optional[str], turn_id: str = "") -> None:
        name = self._skill_name_from_args(args)
        if not name or not session_id:
            return
        if status and str(status).lower() in ("error", "failed", "cancelled", "blocked"):
            return
        turn = self.state.current(session_id)
        selected = bool(turn and (self._matches(name, turn.allowed)))
        if turn is not None:
            def _apply(t: TurnState) -> None:
                if name not in t.loads:
                    t.loads.append(name)
                if not selected and name not in t.unselected_loads:
                    t.unselected_loads.append(name)
            self.state.update(session_id, _apply)
        self.trace.write("skill.load", session_id, {
            "turn_id": turn.turn_id if turn else turn_id, "name": name, "selected": selected,
            "decision": turn.decision if turn else "", "mode": turn.mode if turn else self.config.mode,
        })

    def close_turn(self, *, session_id: str) -> Optional[TurnState]:
        turn = self.state.end_turn(session_id) if session_id else None
        if turn is not None:
            self.trace.write("turn.close", session_id, {
                "turn_id": turn.turn_id, "decision": turn.decision, "mode": turn.mode, "allowed": turn.allowed,
                "loads": turn.loads, "unselected_loads": turn.unselected_loads, "reroutes": turn.reroutes,
                "duration_ms": int((time.time() - turn.started) * 1000),
            })
        return turn
