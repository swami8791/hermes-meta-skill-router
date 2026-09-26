# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- `ruff.toml` pins the lint rule set (E4, E7, E9, F) so `make lint` gives the same result on
  Ruff 0.15 and 0.16+, whose defaults enable many more rules.

## [0.1.0] - 2026-09-23

### Added
- Integration plan against hermes-agent `2332a64`: current-state map, verified primitives, gap analysis,
  conflicts, integration point, MVP, acceptance criteria (`docs/meta-skill-router-integration-plan.md`).
- `plugin/meta-skill-router`: frontmatter-derived catalog, deterministic eligibility, BM25 shortlist,
  structured LLM selection validated by code, `pre_llm_call` directive injection, active-mode
  `skill_view` gating, `skill_route` bounded reroute, `/route` diagnostics, redacted JSONL traces,
  per-session state, `shadow` / `advisory` / `active` modes.
- Test suite (70 tests) with synthetic skill fixtures and a real `PluginManager` discovery path;
  GitHub Actions workflow pinned to the Hermes commit above.
- Root README, contributing guide, Makefile, MIT license.

### Changed
- `SKILL.md`, `skill.manifest.yaml`, and `references/` now describe the verified Hermes primitives
  (`skills_list`, `skill_view`, `delegate_task`, `todo_list`) and the plugin-based integration.
