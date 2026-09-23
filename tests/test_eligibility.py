"""Deterministic eligibility rules."""

import sys

import pytest


def _entries(router_mod, skills_home):
    return {m.name: m for m in router_mod.catalog.SkillCatalog(include_plugin_skills=False).entries("cli")}


def test_disabled_and_platform_rejections(router_mod, skills_home, hermes):
    E = router_mod.eligibility
    ms = _entries(router_mod, skills_home)
    ok, reasons, _ = E.evaluate(ms["disabled-skill"], E.PolicyContext(platform="cli"))
    assert not ok and "disabled_in_config" in reasons
    ok, reasons, _ = E.evaluate(ms["shortcuts-runner"], E.PolicyContext(platform="cli"))
    if sys.platform == "darwin":
        assert ok
    else:
        assert not ok and "platform_mismatch" in reasons


def test_tool_conditions_when_tools_known_and_fail_open_when_unknown(router_mod, skills_home, hermes):
    E = router_mod.eligibility
    ms = _entries(router_mod, skills_home)
    known = E.PolicyContext(platform="cli", available_tools={"web_search", "terminal"})
    ok, reasons, _ = E.evaluate(ms["web-scraping"], known)
    assert not ok and reasons == ["requires_tools_missing:browser_navigate"]
    ok, reasons, _ = E.evaluate(ms["offline-search"], known)
    assert not ok and reasons == ["fallback_primary_available"]
    unknown = E.PolicyContext(platform="cli", available_tools=None)
    assert E.evaluate(ms["web-scraping"], unknown)[0]
    assert E.evaluate(ms["offline-search"], unknown)[0]


def test_session_platform_gate(router_mod, skills_home, hermes):
    E = router_mod.eligibility
    ms = _entries(router_mod, skills_home)
    assert E.evaluate(ms["telegram-broadcast"], E.PolicyContext(platform="telegram"))[0]
    ok, reasons, _ = E.evaluate(ms["telegram-broadcast"], E.PolicyContext(platform="cli"))
    assert not ok and "session_platform_mismatch" in reasons
    assert E.evaluate(ms["telegram-broadcast"], E.PolicyContext(platform=""))[0]  # unknown -> open


def test_missing_credentials_warn_but_do_not_reject(router_mod, skills_home, hermes, monkeypatch):
    E = router_mod.eligibility
    ms = _entries(router_mod, skills_home)
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    ok, reasons, warnings = E.evaluate(ms["notion"], E.PolicyContext(platform="cli"))
    assert ok and not reasons and warnings == ["missing_env:NOTION_API_KEY"]
    monkeypatch.setenv("NOTION_API_KEY", "secret-value")
    assert E.evaluate(ms["notion"], E.PolicyContext(platform="cli"))[2] == []


def test_untrusted_rejected_unless_allowed(router_mod, skills_home, hermes):
    E = router_mod.eligibility
    ms = _entries(router_mod, skills_home)
    ok, reasons, _ = E.evaluate(ms["overlay-skill"], E.PolicyContext(platform="cli"))
    assert not ok and "untrusted" in reasons
    assert E.evaluate(ms["overlay-skill"], E.PolicyContext(platform="cli", allow_untrusted=True))[0]


def test_filter_eligible_partitions(router_mod, skills_home, hermes):
    E = router_mod.eligibility
    ms = list(_entries(router_mod, skills_home).values())
    eligible, warnings, rejections = E.filter_eligible(ms, E.PolicyContext(platform="cli"))
    names = {m.name for m in eligible}
    assert "arxiv" in names and "disabled-skill" not in names
    assert {r.name for r in rejections} >= {"disabled-skill", "overlay-skill", "telegram-broadcast"}
    assert "notion" in warnings


def test_available_tools_approximation_uses_static_toolsets(router_mod, hermes):
    tools, sets = router_mod.eligibility.approximate_available_tools("cli")
    assert tools is None or ("skill_view" in tools and "terminal" in tools)
    assert router_mod.eligibility.approximate_available_tools("no-such-platform") == (None, None)
