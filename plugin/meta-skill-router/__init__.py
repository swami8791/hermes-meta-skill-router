"""Hermes Meta-Skill Router plugin.

Registers the per-turn router (``pre_llm_call``), skill_view gating and observation (``pre_tool_call`` /
``post_tool_call``), turn close (``on_session_end``), the ``skill_route`` tool, the ``/route`` command and
an optional static protocol note. See ``README.md`` and ``docs/meta-skill-router-integration-plan.md``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .router.commands import make_handler as make_command_handler
from .router.config import AUX_TASK_KEY, RouterConfig
from .router.directive import PROTOCOL_SECTION
from .router.engine import Router
from .router.hooks import Hooks
from .router.tool_skill_route import SKILL_ROUTE_SCHEMA, make_handler as make_tool_handler

logger = logging.getLogger(__name__)

PLUGIN_NAME = "meta-skill-router"
TOOLSET = "meta_skill_router"

_router: Optional[Router] = None


def _data_dir_for(ctx: Any):
    def _resolve() -> Optional[Path]:
        try:
            state = getattr(ctx, "state", None)
            if state is not None and getattr(state, "data_dir", None) is not None:
                d = Path(state.data_dir)
                d.mkdir(parents=True, exist_ok=True)
                return d
        except Exception:
            pass
        try:
            from plugins.plugin_storage import plugin_data_dir
            return plugin_data_dir(PLUGIN_NAME)
        except Exception:
            return None
    return _resolve


def build_router(ctx: Any) -> Router:
    get_config = getattr(ctx, "get_config", None)
    return Router(
        config_loader=lambda: RouterConfig.load(get_config),
        data_dir=_data_dir_for(ctx),
        llm=lambda: getattr(ctx, "llm", None),
    )


def get_router() -> Optional[Router]:
    return _router


def register(ctx: Any) -> None:
    global _router
    router = build_router(ctx)
    _router = router
    hooks = Hooks(router)
    ctx.register_hook("pre_llm_call", hooks.on_pre_llm_call)
    ctx.register_hook("pre_tool_call", hooks.on_pre_tool_call)
    ctx.register_hook("post_tool_call", hooks.on_post_tool_call)
    ctx.register_hook("on_session_end", hooks.on_session_end)
    try:
        ctx.register_auxiliary_task(AUX_TASK_KEY, display_name="Meta-skill router",
                                    description="skill routing decisions (one structured call per routed turn)")
    except Exception as exc:  # older hosts: fall back to the main-model route
        logger.debug("auxiliary task registration skipped: %s", exc)
    ctx.register_tool(
        name="skill_route", toolset=TOOLSET, schema=SKILL_ROUTE_SCHEMA, handler=make_tool_handler(router),
        description="Re-route the current request to installed skills (one bounded reroute per turn)", emoji="🧭",
    )
    try:
        ctx.register_command("route", handler=make_command_handler(router),
                             description="Meta-skill router diagnostics: dry-run <text> | catalog | stats",
                             args_hint="<dry-run text | catalog | stats>")
    except Exception as exc:
        logger.debug("/route command registration skipped: %s", exc)
    try:
        if router.config.protocol_section:
            ctx.register_system_prompt_section("meta-skill-router.protocol", PROTOCOL_SECTION)
    except Exception as exc:
        logger.debug("protocol section registration skipped: %s", exc)
