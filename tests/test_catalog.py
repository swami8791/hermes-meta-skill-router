"""Catalog: discovery, change detection, read budget, disabled flags, plugin skills."""

import os
import time
from pathlib import Path


def _names(entries):
    return sorted(m.name for m in entries)


def test_catalog_lists_every_fixture_skill_with_disabled_flag(router_mod, skills_home, hermes):
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    entries = cat.entries("cli")
    assert "arxiv" in _names(entries) and "disabled-skill" in _names(entries)
    disabled = {m.name for m in entries if m.disabled}
    assert disabled == {"disabled-skill"}
    assert cat.last_build["files"] == 14
    assert cat.last_build["bytes_read"] <= 14 * router_mod.manifest.HEAD_BYTES


def test_new_skill_is_visible_without_restart(router_mod, skills_home, hermes):
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    assert "brand-new" not in _names(cat.entries("cli"))
    d = skills_home / "research" / "brand-new"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: brand-new\ndescription: Something new.\n---\nbody\n")
    # The category dir mtime changed (child added) -> signature differs -> rebuild.
    future = time.time() + 5
    os.utime(skills_home / "research", (future, future))
    assert "brand-new" in _names(cat.entries("cli"))


def test_catalog_is_cached_between_calls(router_mod, skills_home, hermes, monkeypatch):
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    cat.entries("cli")
    calls = {"n": 0}
    orig = cat._build

    def _spy(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(cat, "_build", _spy)
    cat.entries("cli")
    assert calls["n"] == 0
    cat.entries("cli", force=True)
    assert calls["n"] == 1


def test_plugin_skills_are_included(router_mod, skills_home, hermes, monkeypatch):
    monkeypatch.setattr(router_mod.catalog, "_plugin_skill_entries",
                        lambda: [{"name": "superpowers:writing-plans", "description": "Write plans.", "category": "plugin", "frontmatter": {}}])
    cat = router_mod.catalog.SkillCatalog()
    entries = cat.entries("cli")
    assert "superpowers:writing-plans" in _names(entries)
    assert next(m for m in entries if m.source == "plugin").trust == "approved"


def test_first_wins_dedupe_prefers_earlier_root(router_mod, skills_home, hermes, monkeypatch, tmp_path):
    ext = tmp_path / "ext-skills" / "arxiv"
    ext.mkdir(parents=True)
    (ext / "SKILL.md").write_text("---\nname: arxiv\ndescription: External copy.\n---\nbody\n")
    monkeypatch.setattr(router_mod.catalog, "scan_dirs", lambda: ([], [skills_home, tmp_path / "ext-skills"]))
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    arxiv = [m for m in cat.entries("cli") if m.name == "arxiv"]
    assert len(arxiv) == 1 and arxiv[0].description.startswith("Search arXiv")


def test_project_dirs_go_through_hermes_quarantine_walker(router_mod, skills_home, hermes, monkeypatch, tmp_path):
    proj = tmp_path / "proj" / ".hermes" / "skills" / "proj-skill"
    proj.mkdir(parents=True)
    (proj / "SKILL.md").write_text("---\nname: proj-skill\ndescription: Project local.\n---\nbody\n")
    seen = {}

    def _fake_iter(root):
        seen["root"] = root
        return iter([proj / "SKILL.md"])
    import agent.skill_utils as su
    monkeypatch.setattr(su, "iter_project_skill_files", _fake_iter)
    monkeypatch.setattr(router_mod.catalog, "scan_dirs", lambda: ([proj.parents[0]], [proj.parents[0], skills_home]))
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    entries = cat.entries("cli")
    assert seen["root"] == proj.parents[0]
    assert next(m for m in entries if m.name == "proj-skill").source == "project"


def test_catalog_never_reads_skill_bodies(router_mod, skills_home, hermes):
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    for m in cat.entries("cli"):
        assert "BODYSENTINEL" not in m.description
        assert "BODYSENTINEL" not in " ".join(m.tags)
