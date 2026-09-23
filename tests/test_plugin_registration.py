"""Plugin surface: register(ctx) wiring, the skill_route tool handler, the /route command, and the real
Hermes PluginManager discovery + hook dispatch path."""

import json
import shutil

import yaml

from conftest import FakeCtx, FakeLlm, PLUGIN_DIR, SELECT_ARXIV, write_config

PAPERS = "Find three recent arXiv papers about sparse attention and summarize them"


def test_plugin_schema_exposes_security_and_routing_switches():
    schema = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text())["config_schema"]
    assert schema["allow_untrusted"]["default"] is False
    assert schema["route_aux_task"]["default"] is True


def test_register_wires_hooks_tool_command_and_aux_task(plugin, hermes_home):
    ctx = FakeCtx(hermes_home, settings={"mode": "advisory", "protocol_section": True}, llm=FakeLlm([SELECT_ARXIV]))
    plugin.register(ctx)
    assert set(ctx.hooks) == {"pre_llm_call", "pre_tool_call", "post_tool_call", "on_session_end"}
    assert ctx.tools["skill_route"]["toolset"] == "meta_skill_router"
    assert ctx.tools["skill_route"]["schema"]["parameters"]["required"] == ["remaining_requirement"]
    assert "route" in ctx.commands and "meta_skill_router" in ctx.aux_tasks
    assert "meta-skill-router.protocol" in ctx.sections and "skill_route" in ctx.sections["meta-skill-router.protocol"]
    assert plugin.get_router() is not None


def test_skill_route_tool_handler_returns_json(plugin, skills_home, hermes, hermes_home):
    ctx = FakeCtx(hermes_home, settings={"mode": "active"}, llm=FakeLlm([SELECT_ARXIV, SELECT_ARXIV]))
    plugin.register(ctx)
    out = ctx.invoke("pre_llm_call", session_id="s1", task_id="t", turn_id="s1:t:1", user_message=PAPERS,
                     conversation_history=[], is_first_turn=True, model="m", platform="cli")
    assert out[0] and "arxiv" in out[0]["context"]
    handler = ctx.tools["skill_route"]["handler"]
    payload = json.loads(handler({"remaining_requirement": "find papers about attention", "tried_skills": "x,y"}, session_id="s1", task_id="t"))
    assert payload["success"] and payload["decision"] in ("SELECT_SKILLS", "NO_SKILL", "CAPABILITY_GAP")
    again = json.loads(handler({"remaining_requirement": "more"}, session_id="s1"))
    assert again["error"] == "budget_exhausted"
    assert json.loads(handler({}, session_id="s1"))["success"] is False


def test_route_command_dry_run_catalog_stats(plugin, skills_home, hermes, hermes_home):
    ctx = FakeCtx(hermes_home, settings={"mode": "shadow"}, llm=FakeLlm([SELECT_ARXIV, SELECT_ARXIV]))
    plugin.register(ctx)
    handler = ctx.commands["route"]["handler"]
    assert handler("").startswith("Usage")
    dry = json.loads(handler("dry-run " + PAPERS))
    assert dry["decision"]["selected"][0]["name"] == "arxiv"
    assert "arxiv" in handler("catalog")
    ctx.invoke("pre_llm_call", session_id="s2", turn_id="s2:t:1", user_message=PAPERS, conversation_history=[], platform="cli")
    stats = handler("stats")
    assert "routed turns: 1" in stats and "SELECT_SKILLS=1" in stats


def test_real_plugin_manager_discovers_and_dispatches(hermes, hermes_home, skills_home, monkeypatch):
    """Load through Hermes' own PluginManager from <HERMES_HOME>/plugins and dispatch the real hooks."""
    dest = hermes_home / "plugins" / "meta-skill-router"
    shutil.copytree(PLUGIN_DIR, dest)
    write_config(hermes_home, {"skills": {"disabled": ["disabled-skill"]},
                               "plugins": {"enabled": ["meta-skill-router"],
                                           "entries": {"meta-skill-router": {"settings": {"mode": "active"}}}}})
    import agent.plugin_llm as plugin_llm
    from conftest import FakeLlmResult
    calls = []

    def _fake_structured(self, **kwargs):
        calls.append(kwargs)
        return FakeLlmResult(parsed=SELECT_ARXIV)
    monkeypatch.setattr(plugin_llm.PluginLlm, "complete_structured", _fake_structured)
    monkeypatch.setenv("HERMES_SAFE_MODE", "0")

    from hermes_cli import plugins as pmod
    pmod.reset_plugin_manager() if hasattr(pmod, "reset_plugin_manager") else None
    mgr = pmod.PluginManager()
    mgr.discover_and_load(force=True)
    loaded = {k: p for k, p in mgr._plugins.items()}
    assert "meta-skill-router" in loaded, sorted(loaded)
    assert not loaded["meta-skill-router"].error, loaded["meta-skill-router"].error
    assert mgr.has_hook("pre_llm_call") if hasattr(mgr, "has_hook") else True

    results = mgr.invoke_hook("pre_llm_call", session_id="sess-real", task_id="t", turn_id="sess-real:t:1",
                              user_message=PAPERS, conversation_history=[], is_first_turn=True, model="m", platform="cli")
    contexts = [r for r in results if isinstance(r, dict) and r.get("context")]
    assert contexts and "arxiv" in contexts[0]["context"]
    assert calls and calls[0].get("task") == "meta_skill_router"

    blocked = [r for r in mgr.invoke_hook("pre_tool_call", tool_name="skill_view", args={"name": "notion"},
                                          session_id="sess-real", turn_id="sess-real:t:1") if isinstance(r, dict)]
    assert blocked and blocked[0]["action"] == "block"
    allowed = mgr.invoke_hook("pre_tool_call", tool_name="skill_view", args={"name": "arxiv"}, session_id="sess-real")
    assert all(r is None for r in allowed)

    from tools.registry import registry
    entry = registry.get_entry("skill_route", scope=mgr.scope_key) if "scope" in registry.get_entry.__code__.co_varnames else registry.get_entry("skill_route")
    assert entry is not None
    out = json.loads(registry.dispatch("skill_route", {"remaining_requirement": "save notes to obsidian"},
                                       scope=mgr.scope_key, session_id="sess-real"))
    assert out["success"] is True
    mgr.invoke_hook("on_session_end", session_id="sess-real", completed=True)
    traces = list((hermes_home / "plugin-data").rglob("sess-real.jsonl"))
    assert traces, "trace file missing"
    kinds = [json.loads(line)["kind"] for line in traces[0].read_text().splitlines()]
    assert kinds[0] == "route.decision" and "turn.close" in kinds
    mgr.unload() if hasattr(mgr, "unload") else None
