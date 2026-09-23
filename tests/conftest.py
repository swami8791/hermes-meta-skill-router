"""Test harness for the meta-skill-router plugin.

* Hermes source is put on ``sys.path`` from ``HERMES_AGENT_SRC`` (or a few default locations). Tests
  that need it use the ``hermes`` fixture, which skips when it is missing.
* Every test gets an isolated ``HERMES_HOME`` (never the real ``~/.hermes``).
* The plugin package is loaded the way Hermes' PluginManager loads directory plugins
  (``hermes_plugins.meta_skill_router`` with relative imports), fresh per test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugin" / "meta-skill-router"
FIXTURE_SKILLS = REPO_ROOT / "tests" / "fixtures" / "skills"
MODULE_NAME = "hermes_plugins.meta_skill_router"


def _find_hermes_src() -> Optional[Path]:
    candidates = [os.environ.get("HERMES_AGENT_SRC", "")]
    candidates += [str(REPO_ROOT / ".hermes-agent"), str(REPO_ROOT.parent / "hermes-agent"),
                   "/home/user/nousresearch/hermes-agent"]
    for c in candidates:
        if c and (Path(c) / "hermes_constants.py").is_file():
            return Path(c)
    return None


HERMES_SRC = _find_hermes_src()
if HERMES_SRC and str(HERMES_SRC) not in sys.path:
    sys.path.insert(0, str(HERMES_SRC))


@pytest.fixture(scope="session")
def hermes():
    if HERMES_SRC is None:
        pytest.skip("hermes-agent source not found; set HERMES_AGENT_SRC")
    return HERMES_SRC


@pytest.fixture(autouse=True)
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    hh = home / ".hermes"
    (hh / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hh))
    monkeypatch.delenv("HERMES_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.chdir(tmp_path)
    # Hermes caches the raw config keyed by path/mtime and the resolved home key; clear what we can.
    for mod, fn in (("agent.skill_utils", "_raw_config_cache_clear"), ("agent.skill_utils", "_external_dirs_cache_clear"),
                    ("hermes_constants", "reset_hermes_home_key_cache")):
        m = sys.modules.get(mod)
        if m is not None and hasattr(m, fn):
            try:
                getattr(m, fn)()
            except Exception:
                pass
    return hh


def write_config(hermes_home: Path, data: Dict[str, Any]) -> Path:
    import yaml
    path = hermes_home / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def skills_home(hermes_home):
    """Copy the fixture skill tree into ``<HERMES_HOME>/skills`` and disable one skill via config."""
    dest = hermes_home / "skills"
    for src in FIXTURE_SKILLS.iterdir():
        shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
    write_config(hermes_home, {"skills": {"disabled": ["disabled-skill"]}})
    return dest


def load_plugin_module():
    """Import the plugin exactly as PluginManager does (fresh each call)."""
    for name in [n for n in list(sys.modules) if n == MODULE_NAME or n.startswith(MODULE_NAME + ".")]:
        del sys.modules[name]
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []  # type: ignore[attr-defined]
        ns.__package__ = "hermes_plugins"
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(MODULE_NAME, PLUGIN_DIR / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN_DIR)])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = MODULE_NAME
    module.__path__ = [str(PLUGIN_DIR)]  # type: ignore[attr-defined]
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugin():
    return load_plugin_module()


@pytest.fixture
def router_mod(plugin):
    """The plugin's ``router`` subpackage modules as a namespace."""
    import importlib
    ns = types.SimpleNamespace()
    for name in ("schemas", "manifest", "catalog", "retrieval", "eligibility", "selector", "state", "trace",
                 "directive", "config", "engine", "hooks", "tool_skill_route", "commands"):
        setattr(ns, name, importlib.import_module(f"{MODULE_NAME}.router.{name}"))
    return ns


class FakeLlmResult:
    def __init__(self, parsed: Any = None, text: str = "") -> None:
        self.parsed = parsed
        self.text = text or (json.dumps(parsed) if parsed is not None else "")
        self.provider = "fake"
        self.model = "fake-model"
        self.agent_id = ""
        self.content_type = "json" if parsed is not None else "text"


class FakeLlm:
    """Stands in for ``ctx.llm``: returns queued answers and records every prompt."""

    def __init__(self, answers: Optional[List[Any]] = None) -> None:
        self.answers = list(answers or [])
        self.calls: List[Dict[str, Any]] = []
        self.raise_exc: Optional[BaseException] = None

    def complete_structured(self, **kwargs: Any) -> FakeLlmResult:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        if not self.answers:
            return FakeLlmResult(parsed={"decision": "NO_SKILL", "selected": [], "confidence": "low"})
        answer = self.answers.pop(0)
        if isinstance(answer, str):
            return FakeLlmResult(parsed=None, text=answer)
        return FakeLlmResult(parsed=answer)

    def prompt_text(self, index: int = -1) -> str:
        call = self.calls[index]
        parts = []
        for block in call.get("input", []):
            parts.append(getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else ""))
        return call.get("instructions", "") + "\n" + "\n".join(parts)


class FakeState:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


class FakeCtx:
    """Minimal PluginContext double recording registrations."""

    def __init__(self, hermes_home: Path, settings: Optional[Dict[str, Any]] = None, llm: Optional[FakeLlm] = None) -> None:
        self.settings = dict(settings or {})
        self.llm = llm or FakeLlm()
        self.state = FakeState(hermes_home / "plugin-data" / "meta-skill-router")
        self.hooks: Dict[str, List[Any]] = {}
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.commands: Dict[str, Dict[str, Any]] = {}
        self.aux_tasks: Dict[str, Dict[str, Any]] = {}
        self.sections: Dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, name: str, toolset: str, schema: Dict[str, Any], handler: Any, **kw: Any) -> None:
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kw}

    def register_command(self, name: str, handler: Any, **kw: Any) -> None:
        self.commands[name] = {"handler": handler, **kw}

    def register_auxiliary_task(self, key: str, **kw: Any) -> None:
        self.aux_tasks[key] = kw

    def register_system_prompt_section(self, id: str, content: Any, **kw: Any) -> None:
        self.sections[id] = content

    def invoke(self, hook: str, **kwargs: Any) -> List[Any]:
        return [cb(**kwargs) for cb in self.hooks.get(hook, [])]


@pytest.fixture
def make_router(plugin, hermes_home):
    """Factory: ``make_router(settings=..., answers=...) -> (router, ctx)``."""
    def _make(settings: Optional[Dict[str, Any]] = None, answers: Optional[List[Any]] = None):
        ctx = FakeCtx(hermes_home, settings=settings, llm=FakeLlm(answers))
        return plugin.build_router(ctx), ctx
    return _make


SELECT_ARXIV = {"decision": "SELECT_SKILLS", "selected": [{"name": "arxiv", "reason": "paper search"}],
                "confidence": "high"}
SELECT_TWO = {"decision": "SELECT_SKILLS",
              "selected": [{"name": "arxiv", "reason": "find papers"}, {"name": "obsidian", "reason": "save notes"}],
              "confidence": "medium"}
NO_SKILL = {"decision": "NO_SKILL", "selected": [], "confidence": "high"}
GAP = {"decision": "CAPABILITY_GAP", "selected": [], "confidence": "medium",
       "missing_capabilities": ["ios.code-signing"]}
