"""RouterState persistence, TraceWriter trimming, RouterConfig coercion, directive rendering."""

import json
import time


def test_state_survives_new_instance_and_expires(router_mod, tmp_path):
    S = router_mod.state
    a = S.RouterState(tmp_path)
    a.begin_turn("sess", "sess:t1", mode="active", decision="SELECT_SKILLS", allowed=["arxiv"])
    a.update("sess", lambda t: t.loads.append("arxiv"))
    b = S.RouterState(tmp_path)  # fresh AIAgent per gateway message
    t = b.current("sess")
    assert t.allowed == ["arxiv"] and t.loads == ["arxiv"] and t.reroutes == 0
    data = json.loads((tmp_path / "router-state.json").read_text())
    data["sessions"]["sess"]["started"] = time.time() - S.STATE_TTL_SECONDS - 1
    (tmp_path / "router-state.json").write_text(json.dumps(data))
    assert S.RouterState(tmp_path).current("sess") is None


def test_state_with_callable_dir_and_memory_only(router_mod, tmp_path):
    S = router_mod.state
    st = S.RouterState(lambda: tmp_path / "sub")
    st.begin_turn("s", "t", mode="shadow", decision="NO_SKILL", allowed=[])
    assert (tmp_path / "sub" / "router-state.json").exists()
    mem = S.RouterState(None)
    mem.begin_turn("s", "t", mode="shadow", decision="NO_SKILL", allowed=[])
    assert mem.current("s").turn_id == "t" and mem.end_turn("s") is not None and mem.current("s") is None


def test_state_callable_dir_isolates_profile_switches(router_mod, tmp_path):
    S = router_mod.state
    current = [tmp_path / "profile-a"]
    st = S.RouterState(lambda: current[0])
    st.begin_turn("s", "a:t1", mode="active", decision="SELECT_SKILLS", allowed=["arxiv"])

    current[0] = tmp_path / "profile-b"
    assert st.current("s") is None
    st.begin_turn("s", "b:t1", mode="active", decision="NO_SKILL", allowed=[])

    current[0] = tmp_path / "profile-a"
    assert st.current("s").turn_id == "a:t1"
    assert json.loads((tmp_path / "profile-b" / "router-state.json").read_text())["sessions"]["s"]["turn_id"] == "b:t1"


def test_reroute_reservation_is_bounded(router_mod):
    S = router_mod.state
    st = S.RouterState()
    st.begin_turn("s", "t", mode="active", decision="NO_SKILL", allowed=[])
    turn, reserved = st.reserve_reroute("s", 1)
    assert reserved and turn.reroutes == 1
    turn, reserved = st.reserve_reroute("s", 1)
    assert not reserved and turn.reroutes == 1


def test_trace_trims_oldest_first(router_mod, tmp_path):
    w = router_mod.trace.TraceWriter(tmp_path, max_bytes=64 * 1024)
    for i in range(1500):
        w.write("route.decision", "sess", {"i": i, "pad": "x" * 100})
    path = w.path_for("sess")
    assert path.stat().st_size <= 64 * 1024
    records = w.read("sess", limit=10000)
    assert records[-1]["i"] == 1499 and records[0]["i"] > 0
    assert all(r["schema"] == "meta-skill-router.trace.v1" for r in records)


def test_trace_disabled_returns_record_without_writing(router_mod, tmp_path):
    w = router_mod.trace.TraceWriter(tmp_path, enabled=False)
    rec = w.write("turn.close", "sess", {"a": 1})
    assert rec["kind"] == "turn.close" and not (tmp_path / "traces").exists()


def test_stats_caps_files_and_labels_sample(router_mod, tmp_path, monkeypatch):
    writer = router_mod.trace.TraceWriter(tmp_path)
    writer.write("route.decision", "older", {"decision": {"decision": "NO_SKILL"}})
    time.sleep(0.01)
    writer.write("route.decision", "newer", {"decision": {"decision": "SELECT_SKILLS"}})
    monkeypatch.setattr(router_mod.commands, "STATS_MAX_FILES", 1)

    class _Router:
        trace = writer

    stats = router_mod.commands._stats(_Router())
    assert "routed turns: 1 (recent trace sample)" in stats
    assert "SELECT_SKILLS=1" in stats and "NO_SKILL" not in stats


def test_trace_fallback_redaction(router_mod):
    out = router_mod.trace._fallback_redact("token=abcdefghijk and ghp_ABCDEFGHIJKLMNOP")
    assert "abcdefghijk" not in out and "ABCDEFGHIJKLMNOP" not in out


def test_config_coercion_and_defaults(router_mod):
    C = router_mod.config.RouterConfig
    assert C.load(None).mode == "shadow"
    raw = {"mode": "ACTIVE", "max_candidates": "7", "skip_platforms": "subagent, cron", "trace_enabled": "false",
           "selection_timeout_s": "3.5", "max_selected": -2, "directive_max_chars": "abc"}
    cfg = C.load(lambda k, d: raw.get(k, d))
    assert cfg.mode == "active" and cfg.max_candidates == 7 and cfg.skip_platforms == ["subagent", "cron"]
    assert cfg.trace_enabled is False and cfg.selection_timeout_s == 3.5
    assert cfg.max_selected == 3 and cfg.directive_max_chars == 1500  # invalid -> defaults
    bad = C.load(lambda k, d: "sideways" if k == "mode" else d)
    assert bad.mode == "shadow"
    bad_bools = C.load(lambda k, d: "definitely" if k in {"trace_enabled", "route_aux_task"} else d)
    assert bad_bools.trace_enabled is True and bad_bools.route_aux_task is True


def test_directive_rendering_and_pin_detection(router_mod):
    D, S = router_mod.directive, router_mod.schemas
    dec = S.RoutingDecision(decision="SELECT_SKILLS", confidence="high",
                            selected=[S.SelectedSkill("b", "second", 2), S.SelectedSkill("a", "first", 1)])
    text = D.render(dec, mode="advisory", reroute_budget=2)
    assert "1) a — first; 2) b — second" in text and "at most 2 times" in text
    assert D.render(dec, mode="shadow") is None
    assert D.render(S.RoutingDecision(decision="NO_SKILL"), mode="advisory") is None
    assert D.render(dec, mode="active", max_chars=60).endswith("…") and len(D.render(dec, mode="active", max_chars=60)) <= 60
    assert D.is_pinned('  [IMPORTANT: The user has invoked the "x" skill')
    assert D.is_pinned("[Loaded as part of the \"clean\" skill bundle, ...")
    assert not D.is_pinned("find papers")
    assert D.message_text([{"type": "text", "text": "a"}, {"type": "image_url"}, "b"]) == "a\nb"
    assert D.message_text({"content": "c"}) == "c"


def test_pin_prefix_matches_hermes_constant(router_mod, hermes):
    from agent import skill_commands
    assert router_mod.directive.SKILL_INVOCATION_PREFIX == skill_commands._SKILL_INVOCATION_PREFIX
    assert router_mod.directive.BUNDLE_BLOCK_MARKER == skill_commands._BUNDLE_FIRST_SKILL_BLOCK.lstrip("\n")
