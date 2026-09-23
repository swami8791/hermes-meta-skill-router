"""Directive rendering (plan 8.5) and explicit-pin detection.

The directive is deterministic for a given decision so retries within a turn send identical bytes,
carries no skill bodies or secrets, and stays far below Hermes' hook-context spill cap."""

from __future__ import annotations

from typing import Any, List, Optional

from .schemas import DECISION_GAP, DECISION_NO_SKILL, DECISION_SELECT, RoutingDecision

# Literal prefixes Hermes' slash-skill scaffolding writes into the user message
# (``agent/skill_commands.py``: ``_SKILL_INVOCATION_PREFIX`` / ``_BUNDLE_FIRST_SKILL_BLOCK``).
SKILL_INVOCATION_PREFIX = "[IMPORTANT: The user has invoked the "
BUNDLE_BLOCK_MARKER = "[Loaded as part of the "
AUTO_LOAD_MARKER = "skill is auto-loaded via config (skills.auto_load)"


def message_text(user_message: Any) -> str:
    """Text of a user message that may be a string or a multimodal list of parts."""
    if isinstance(user_message, str):
        return user_message
    if isinstance(user_message, list):
        parts: List[str] = []
        for p in user_message:
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                parts.append(p["text"])
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    if isinstance(user_message, dict) and isinstance(user_message.get("content"), (str, list)):
        return message_text(user_message["content"])
    return "" if user_message is None else str(user_message)


def is_pinned(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith(SKILL_INVOCATION_PREFIX) or BUNDLE_BLOCK_MARKER in stripped[:400]


def render(decision: RoutingDecision, *, mode: str, max_chars: int = 1500, reroute_budget: int = 1) -> Optional[str]:
    """Directive text for advisory/active modes, ``None`` when nothing should be injected."""
    if mode not in ("advisory", "active"):
        return None
    if decision.decision == DECISION_SELECT and decision.selected:
        lines = [f"[Skill routing] Decision: SELECT_SKILLS (confidence {decision.confidence})."]
        items = []
        for s in sorted(decision.selected, key=lambda s: s.order):
            reason = f" — {s.reason}" if s.reason else ""
            items.append(f"{s.order}) {s.name}{reason}")
        lines.append("Load in this order with skill_view(name) before acting: " + "; ".join(items) + ".")
        tail = "Do not load other skills for this request."
        if reroute_budget > 0:
            tail += (" If a requirement remains unmet after these, call skill_route(remaining_requirement=...) "
                     f"at most {reroute_budget} time{'s' if reroute_budget != 1 else ''}.")
        lines.append(tail)
    elif decision.decision == DECISION_GAP:
        missing = ", ".join(decision.missing_capabilities) or "an unlisted capability"
        lines = [f"[Skill routing] Decision: CAPABILITY_GAP. No installed skill covers: {missing}.",
                 "Proceed with general tools where safe, say what is missing, and do not install anything."]
    elif decision.decision == DECISION_NO_SKILL and mode == "active":
        lines = ["[Skill routing] Decision: NO_SKILL. No installed skill applies; proceed with general tools "
                 "without calling skill_view. If a requirement turns out to need a skill, call skill_route once."]
    else:
        return None
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


PROTOCOL_SECTION = (
    "## Skill routing protocol\n"
    "A router may prepend a \"[Skill routing]\" note to a user message naming which installed skills to "
    "load with skill_view(name) for that request, in order. Follow it: load only the named skills, and use "
    "skill_route(remaining_requirement=...) once if the request still needs a capability those skills do "
    "not cover. Explicit /skill invocations by the user are never overridden by the router."
)
