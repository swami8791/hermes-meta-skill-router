"""BM25 shortlist behaviour."""

import time


def _index(router_mod, skills_home, hermes):
    cat = router_mod.catalog.SkillCatalog(include_plugin_skills=False)
    return router_mod.retrieval.Index(cat.entries("cli"))


def test_exact_name_mention_ranks_first(router_mod, skills_home, hermes):
    idx = _index(router_mod, skills_home, hermes)
    top = idx.search("use obsidian to store the summary", limit=5)
    assert top and top[0].manifest.name == "obsidian"


def test_unrelated_query_returns_nothing(router_mod, skills_home, hermes):
    idx = _index(router_mod, skills_home, hermes)
    assert idx.search("what is two plus two", limit=5) == []


def test_stemming_matches_inflections(router_mod, skills_home, hermes):
    idx = _index(router_mod, skills_home, hermes)
    names = [c.manifest.name for c in idx.search("find recent papers on transformers", limit=5)]
    assert "arxiv" in names


def test_limit_exclude_and_determinism(router_mod, skills_home, hermes):
    idx = _index(router_mod, skills_home, hermes)
    q = "search papers and take notes in the vault"
    a = idx.search(q, limit=2)
    b = idx.search(q, limit=2)
    assert [c.manifest.name for c in a] == [c.manifest.name for c in b]
    assert len(a) <= 2
    excluded = idx.search(q, limit=5, exclude={"arxiv"})
    assert "arxiv" not in [c.manifest.name for c in excluded]


def test_explicit_mentions_are_whole_words(router_mod, skills_home, hermes):
    idx = _index(router_mod, skills_home, hermes)
    mentions = router_mod.retrieval.explicit_mentions(idx.manifests, "run gmail-triage now, not the notionally similar thing")
    assert mentions == ["gmail-triage"]


def test_retrieval_scales(router_mod, tmp_path):
    S = router_mod.schemas.SkillManifest
    manifests = [S(id=f"x:{i}", name=f"skill-{i}", description=f"Handles topic {i % 97} and area {i % 13} for team {i % 7}.",
                   tags=[f"t{i % 31}", f"area{i % 13}"], category=f"cat{i % 9}", fingerprint=str(i)) for i in range(1000)]
    started = time.perf_counter()
    idx = router_mod.retrieval.Index(manifests)
    build_ms = (time.perf_counter() - started) * 1000
    times = []
    for i in range(50):
        t0 = time.perf_counter()
        idx.search(f"help with topic {i % 97} area {i % 13}", limit=12)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    assert build_ms < 2000
    assert times[int(len(times) * 0.95) - 1] < 100
