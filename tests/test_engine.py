"""Golden routing cases through the Router and hook handlers (plan sections 10-11)."""

import json

from conftest import GAP, NO_SKILL, SELECT_ARXIV, SELECT_TWO

PAPERS = "Find three recent arXiv papers about sparse attention and summarize them"
NOTES = "Find recent papers about sparse attention and save a summary note in my vault"
MATH = "what is 2 + 2 please"


def _trace(router, session="s1"):
    return router.trace.read(session)


def _route(router, text, session="s1", turn="s1:t1:abcd", platform="cli", history=None):
    return router.route_turn(user_message=text, history=history, session_id=session, turn_id=turn, platform=platform)


# ---------------------------------------------------------------- shadow mode

def test_shadow_mode_injects_nothing_but_traces(make_router, skills_home, hermes):
    router, ctx = make_router(answers=[SELECT_ARXIV])
    result = _route(router, PAPERS)
    assert result.context is None
    assert result.decision.decision == "SELECT_SKILLS" and result.decision.selected_names() == ["arxiv"]
    rec = _trace(router)[-1]
    assert rec["kind"] == "route.decision" and rec["mode"] == "shadow"
    assert rec["decision"]["selected"][0]["name"] == "arxiv"
    assert rec["directive_chars"] == 0
    assert [c["name"] for c in rec["candidates"]][:1] == ["arxiv"]
    assert len(rec["candidates"]) <= 12
    assert rec["intent_hash"] and rec["latency_ms"] >= 0


def test_no_skill_without_lexical_candidates_skips_the_llm(make_router, skills_home, hermes):
    router, ctx = make_router()
    result = _route(router, MATH)
    assert result.decision.decision == "NO_SKILL" and result.decision.rationale == "no_lexical_candidates"
    assert ctx.llm.calls == []


# ---------------------------------------------------------------- decisions

def test_one_skill_advisory_directive(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[SELECT_ARXIV])
    result = _route(router, PAPERS)
    assert result.context is not None
    text = result.context["context"]
    assert text.startswith("[Skill routing] Decision: SELECT_SKILLS")
    assert "1) arxiv" in text and "skill_view(name)" in text and "skill_route(" in text
    assert "BODYSENTINEL" not in text and len(text) <= 1500


def test_multi_skill_order_is_preserved(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[SELECT_TWO])
    text = _route(router, NOTES).context["context"]
    assert text.index("1) arxiv") < text.index("2) obsidian")
    assert router.state.current("s1").allowed == ["arxiv", "obsidian"]


def test_no_skill_is_silent_in_advisory_and_one_line_in_active(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[NO_SKILL])
    assert _route(router, PAPERS).context is None
    router, _ = make_router(settings={"mode": "active"}, answers=[NO_SKILL])
    text = _route(router, PAPERS).context["context"]
    assert text.startswith("[Skill routing] Decision: NO_SKILL")


def test_capability_gap_directive(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[GAP])
    text = _route(router, "sign the iOS archive with the papers pipeline").context["context"]
    assert "CAPABILITY_GAP" in text and "ios.code-signing" in text and "do not install" in text


def test_directive_is_byte_stable_for_same_decision(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[SELECT_ARXIV, SELECT_ARXIV])
    a = _route(router, PAPERS).context["context"]
    b = _route(router, PAPERS, turn="s1:t2:ef01").context["context"]
    assert a == b


# ---------------------------------------------------------------- gates

def test_explicit_slash_skill_invocation_is_pinned(make_router, skills_home, hermes):
    router, ctx = make_router(settings={"mode": "active"}, answers=[SELECT_ARXIV])
    msg = '[IMPORTANT: The user has invoked the "obsidian" skill, indicating they want you to follow its instructions. The full skill content is loaded below.]\n\n# Obsidian'
    result = _route(router, msg)
    assert result.decision.decision == "PINNED" and result.context is None and ctx.llm.calls == []
    # PINNED turns never block skill_view
    assert router.before_skill_view(args={"name": "gmail-triage"}, session_id="s1") is None


def test_short_message_and_skipped_platform(make_router, skills_home, hermes):
    router, ctx = make_router(answers=[SELECT_ARXIV])
    assert _route(router, "hi there").skipped_reason == "message_too_short"
    assert _route(router, PAPERS, platform="subagent").skipped_reason == "platform_skipped"
    assert ctx.llm.calls == []
    assert router.state.current("s1") is None


def test_explicit_mention_promotes_selection(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[NO_SKILL])
    result = _route(router, "please use gmail-triage on my inbox this morning")
    assert result.decision.decision == "SELECT_SKILLS" and result.decision.selected_names() == ["gmail-triage"]
    assert result.allowed == ["gmail-triage"]


def test_router_fails_open_when_llm_raises(make_router, skills_home, hermes):
    router, ctx = make_router(settings={"mode": "active"})
    ctx.llm.raise_exc = RuntimeError("provider down")
    result = _route(router, PAPERS)
    assert result.decision.decision == "NO_SKILL" and result.decision.error == "selector_error:RuntimeError"
    assert _trace(router)[-1]["decision"]["error"] == "selector_error:RuntimeError"


def test_open_todos_feed_the_intent(router_mod, make_router, skills_home, hermes):
    todo_result = json.dumps({"todos": [{"id": "1", "content": "save summary to obsidian vault", "status": "pending"},
                                        {"id": "2", "content": "done thing", "status": "completed"}], "revision": 3})
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "", "tool_calls": []},
               {"role": "tool", "content": todo_result, "tool_call_id": "x"}]
    assert router_mod.engine.open_todos_from_history(history) == ["save summary to obsidian vault"]
    router, ctx = make_router(answers=[NO_SKILL])
    _route(router, "continue with the next task from my list", history=history)
    assert "obsidian" in ctx.llm.prompt_text()


# ---------------------------------------------------------------- gating and observation

def test_active_mode_blocks_unselected_skill_view_and_allows_selected(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "active"}, answers=[SELECT_ARXIV])
    _route(router, PAPERS)
    assert router.before_skill_view(args={"name": "arxiv"}, session_id="s1") is None
    assert router.before_skill_view(args={"name": "research/arxiv"}, session_id="s1") is None
    namespace_block = router.before_skill_view(args={"name": "other/arxiv"}, session_id="s1")
    assert namespace_block["action"] == "block"
    block = router.before_skill_view(args={"name": "gmail-triage"}, session_id="s1")
    assert block["action"] == "block" and "gmail-triage" in block["message"] and "skill_route" in block["message"]
    assert _trace(router)[-1]["kind"] == "skill.load_blocked"


def test_advisory_mode_never_blocks_but_records_unselected_loads(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "advisory"}, answers=[SELECT_ARXIV])
    _route(router, PAPERS)
    assert router.before_skill_view(args={"name": "gmail-triage"}, session_id="s1") is None
    router.after_skill_view(args={"name": "gmail-triage"}, session_id="s1", status="success")
    router.after_skill_view(args={"name": "arxiv"}, session_id="s1", status="success")
    turn = router.close_turn(session_id="s1")
    assert turn.loads == ["gmail-triage", "arxiv"] and turn.unselected_loads == ["gmail-triage"]
    close = _trace(router)[-1]
    assert close["kind"] == "turn.close" and close["unselected_loads"] == ["gmail-triage"]
    assert router.state.current("s1") is None


def test_skills_per_turn_budget(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "active", "max_skills_per_turn": 1}, answers=[SELECT_TWO])
    _route(router, NOTES)
    router.after_skill_view(args={"name": "arxiv"}, session_id="s1", status="success")
    block = router.before_skill_view(args={"name": "obsidian"}, session_id="s1")
    assert block and "limit 1" in block["message"]
    assert router.before_skill_view(args={"name": "arxiv"}, session_id="s1") is None  # already loaded


def test_category_alias_and_canonical_name_share_one_load_slot(make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "active", "max_skills_per_turn": 1}, answers=[SELECT_ARXIV])
    _route(router, PAPERS)
    router.after_skill_view(args={"name": "research/arxiv"}, session_id="s1", status="success")
    assert router.state.current("s1").loads == ["arxiv"]
    assert router.before_skill_view(args={"name": "arxiv"}, session_id="s1") is None


# ---------------------------------------------------------------- reroute

def test_one_bounded_reroute(make_router, skills_home, hermes):
    router, ctx = make_router(settings={"mode": "active"},
                              answers=[SELECT_ARXIV, {"decision": "SELECT_SKILLS", "selected": [{"name": "obsidian", "reason": "notes"}], "confidence": "high"}])
    _route(router, PAPERS)
    first = router.reroute(session_id="s1", remaining_requirement="save the summary into my obsidian vault")
    assert first["success"] and first["decision"] == "SELECT_SKILLS" and first["selected"][0]["name"] == "obsidian"
    assert first["reroutes_remaining"] == 0
    assert router.before_skill_view(args={"name": "obsidian"}, session_id="s1") is None
    second = router.reroute(session_id="s1", remaining_requirement="anything else")
    assert second["success"] is False and second["error"] == "budget_exhausted"
    assert len(ctx.llm.calls) == 2  # the exhausted call never reached the LLM
    kinds = [r["kind"] for r in _trace(router)]
    assert kinds.count("route.reroute") == 2


def test_reroute_with_no_remaining_candidates_is_a_gap_without_an_llm_call(make_router, skills_home, hermes):
    router, ctx = make_router(settings={"mode": "advisory"}, answers=[SELECT_ARXIV, GAP])
    _route(router, PAPERS)
    out = router.reroute(session_id="s1", remaining_requirement="find papers about sparse attention again")
    assert out["decision"] == "CAPABILITY_GAP"
    gap = out["capability_gap"]
    assert gap["type"] == "capability-gap.v1" and gap["skill_discovery_allowed"] is False
    assert len(ctx.llm.calls) == 1  # arxiv was excluded, nothing else matched: no selector call


def test_reroute_excludes_skills_already_allowed(make_router, skills_home, hermes):
    router, ctx = make_router(settings={"mode": "advisory"}, answers=[SELECT_ARXIV, GAP])
    _route(router, PAPERS)
    router.reroute(session_id="s1", remaining_requirement="find papers and save notes in my vault")
    assert len(ctx.llm.calls) == 2
    second = ctx.llm.prompt_text(1)
    assert '"name": "obsidian"' in second and '"name": "arxiv"' not in second


def test_reroute_requires_text(make_router, skills_home, hermes):
    router, _ = make_router()
    assert router.reroute(session_id="s1", remaining_requirement="  ")["success"] is False


# ---------------------------------------------------------------- hooks facade

def test_hooks_accept_hermes_payload_shapes(router_mod, make_router, skills_home, hermes):
    router, _ = make_router(settings={"mode": "active"}, answers=[SELECT_ARXIV])
    hooks = router_mod.hooks.Hooks(router)
    ctx_out = hooks.on_pre_llm_call(session_id="s9", task_id="t", turn_id="s9:t:1", user_message=[{"type": "text", "text": PAPERS}],
                                    conversation_history=[], is_first_turn=True, model="m", platform="cli", sender_id="")
    assert ctx_out and "arxiv" in ctx_out["context"]
    assert hooks.on_pre_tool_call(tool_name="terminal", args={"command": "ls"}, session_id="s9") is None
    assert hooks.on_pre_tool_call(tool_name="skill_view", args={"name": "notion"}, session_id="s9")["action"] == "block"
    hooks.on_post_tool_call(tool_name="skill_view", args={"name": "arxiv"}, session_id="s9", status="success", duration_ms=3)
    hooks.on_session_end(session_id="s9", completed=True)
    assert router.state.current("s9") is None


# ---------------------------------------------------------------- trace hygiene

def test_trace_redacts_secrets_in_user_text(make_router, skills_home, hermes):
    router, _ = make_router(answers=[NO_SKILL])
    secret = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnop"
    _route(router, f"find papers about attention; my key is {secret}")
    raw = router.trace.path_for("s1").read_text()
    assert secret not in raw
