# Contributing

Thanks for helping. This project is a Hermes plugin, so it inherits Hermes' own contribution rules
(see `AGENTS.md` in [hermes-agent](https://github.com/NousResearch/hermes-agent)). The short version:

## Ground rules

- **Plugins never touch core.** Everything lives under `plugin/meta-skill-router/` and uses only the
  `PluginContext` surface plus public, in-tree Hermes helpers. If a capability is missing, propose an
  additive hook field upstream; do not fork Hermes behaviour here.
- **Prompt caching is sacred.** Nothing may modify the system prompt or past messages. The only
  injection channel is the current turn's user message (via `pre_llm_call`) and tool results.
- **Metadata only.** The router reads the frontmatter head of `SKILL.md`, never the body, and never
  calls `skill_view` itself. Loading stays on Hermes' loader.
- **Fail-open.** A router bug must degrade to `NO_SKILL`, never break a turn. Wrap new code paths
  accordingly and add a test that exercises the failure.
- **No new dependencies.** PyYAML and `snowballstemmer` are already Hermes core dependencies.
- **Behaviour contracts, not snapshots.** Tests assert how inputs relate to outputs (a directive names
  the selected skills in order), not exact strings that would break on wording changes.

## Setup

```bash
git clone https://github.com/NousResearch/hermes-agent ../hermes-agent
git -C ../hermes-agent checkout 2332a6433a14d09d239baa963ca12a4cd8271e2d   # current pin
cd ../hermes-agent && uv sync --frozen --extra dev && cd -
export HERMES_AGENT_SRC=$PWD/../hermes-agent
make test
```

Tests never touch `~/.hermes`; each test gets a temporary `HERMES_HOME`.

## Making a change

1. Open an issue or describe the change in the PR: what decision changes, for which inputs, and why.
2. Add or update tests first. Golden routing cases live in `tests/test_engine.py`; synthetic skills in
   `tests/fixtures/skills/` (keep the `BODYSENTINEL_*` markers so "never reads the body" stays provable).
3. Keep `plugin/meta-skill-router/README.md` and the settings table in the root README in sync with
   `plugin.yaml`'s `config_schema`.
4. If you change a rule documented in `docs/meta-skill-router-integration-plan.md`, add a line to its
   *Implementation status* header rather than rewriting history.
5. Add a `CHANGELOG.md` entry under *Unreleased*.

## Bumping the Hermes pin

Update the SHA in `.github/workflows/tests.yml`, search the repository for references to the old SHA,
run the suite, and note any Hermes API drift in the changelog.
