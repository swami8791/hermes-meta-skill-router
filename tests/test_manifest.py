"""Frontmatter -> SkillManifest adapter (plan 8.3)."""

from pathlib import Path

from conftest import FIXTURE_SKILLS


def test_bundled_style_frontmatter_maps_all_routing_fields(router_mod, skills_home):
    m, n = router_mod.manifest.manifest_from_path(skills_home / "productivity" / "notion" / "SKILL.md", root=skills_home, source="local")
    assert m.name == "notion"
    assert m.category == "productivity"
    assert m.description.startswith("Manage Notion pages")
    assert m.version == "1.0.0"
    assert m.tags == ["Notion", "Productivity", "Database", "API"]
    assert m.env_vars == ["NOTION_API_KEY"]
    assert m.platforms == ["linux", "macos", "windows"]
    assert m.trust in ("core", "approved", "approved-local")
    assert m.fingerprint and len(m.fingerprint) == 16
    assert n <= router_mod.manifest.HEAD_BYTES
    assert "BODYSENTINEL" not in m.description


def test_conditions_and_session_platforms(router_mod, skills_home):
    scrape, _ = router_mod.manifest.manifest_from_path(skills_home / "web" / "web-scraping" / "SKILL.md", root=skills_home, source="local")
    assert scrape.requires_tools == ["browser_navigate"]
    offline, _ = router_mod.manifest.manifest_from_path(skills_home / "web" / "offline-search" / "SKILL.md", root=skills_home, source="local")
    assert offline.fallback_for_tools == ["web_search"]
    tg, _ = router_mod.manifest.manifest_from_path(skills_home / "social-media" / "telegram-broadcast" / "SKILL.md", root=skills_home, source="local")
    assert tg.session_platforms == ["telegram"]


def test_overlay_adds_metadata_but_only_lowers_trust(router_mod, skills_home):
    m, _ = router_mod.manifest.manifest_from_path(skills_home / "research" / "overlay-skill" / "SKILL.md", root=skills_home, source="local")
    assert "pricing.comparison" in m.tags
    assert "Compare competitor pricing" in m.triggers
    assert m.requires_tools == ["web_search"]
    assert m.version == "1.0.0"  # frontmatter wins over overlay when present
    assert m.trust == "untrusted"  # overlay lowered it


def test_overlay_cannot_raise_trust(router_mod, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: s\ndescription: x.\n---\nbody\n")
    (d / "skill.manifest.yaml").write_text("security:\n  trust_requirement: core\n")
    m, _ = router_mod.manifest.manifest_from_path(d / "SKILL.md", root=tmp_path, source="external")
    assert m.trust == "approved-local"


def test_category_rules_match_prompt_builder(router_mod, tmp_path):
    cat = router_mod.manifest.category_for
    assert cat(tmp_path / "a" / "b" / "SKILL.md", tmp_path) == "a"
    assert cat(tmp_path / "a" / "x" / "b" / "SKILL.md", tmp_path) == "a/x"
    assert cat(tmp_path / "b" / "SKILL.md", tmp_path) == "general"
    assert cat(tmp_path / "_org" / "org1" / "a" / "b" / "SKILL.md", tmp_path) == "a"


def test_malformed_frontmatter_still_yields_listable_manifest(router_mod, tmp_path):
    d = tmp_path / "weird"
    d.mkdir()
    (d / "SKILL.md").write_text("# No frontmatter here\n\nFirst useful line of the body.\n")
    m, _ = router_mod.manifest.manifest_from_path(d / "SKILL.md", root=tmp_path, source="local")
    assert m.name == "weird"
    assert m.description == "First useful line of the body."


def test_fallback_parser_handles_lists_and_bad_yaml(router_mod):
    fm, body = router_mod.manifest._fallback_parse("---\nname: a\ntags: [x, y]\n---\nbody")
    assert fm["name"] == "a" and body.strip() == "body"
    assert router_mod.manifest._as_list(fm["tags"]) == ["x", "y"]
    fm2, _ = router_mod.manifest._fallback_parse("---\nname: a\ndesc: [unclosed\n---\nbody")
    assert fm2.get("name") == "a"


def test_head_read_extends_when_fence_is_late(router_mod, tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("---\nname: long\ndescription: " + "x" * 5000 + "\n---\nbody\n")
    text, n = router_mod.manifest.read_head(p)
    assert n > router_mod.manifest.HEAD_BYTES
    fm, _ = router_mod.manifest.parse_frontmatter(text)
    assert fm["name"] == "long"


def test_plugin_entry_manifest(router_mod):
    m = router_mod.manifest.manifest_from_plugin_entry(
        {"name": "superpowers:writing-plans", "description": "Write plans.", "category": "plugin",
         "frontmatter": {"metadata": {"hermes": {"tags": ["plans"]}}}})
    assert m.source == "plugin" and m.name == "superpowers:writing-plans" and m.tags == ["plans"]
    assert m.trust == "approved"
