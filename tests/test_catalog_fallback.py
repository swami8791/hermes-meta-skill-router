"""Disabled-name resolution must not silently degrade when Hermes' helper cannot be imported."""

import builtins

from conftest import write_config


def test_disabled_names_fall_back_to_config_file(router_mod, hermes_home, monkeypatch):
    write_config(hermes_home, {"skills": {"disabled": ["a", "hermes-agent"], "platform_disabled": {"cli": ["b"]}}})
    real_import = builtins.__import__

    def _broken(name, *args, **kwargs):
        if name == "agent.skill_utils":
            raise ImportError("simulated gateway import failure")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _broken)
    assert router_mod.catalog.disabled_names("cli") == {"a", "b"}
    assert router_mod.catalog.disabled_names(None) == {"a"}


def test_disabled_names_via_hermes(router_mod, hermes, hermes_home):
    write_config(hermes_home, {"skills": {"disabled": ["a"], "platform_disabled": {"telegram": ["c"]}}})
    assert router_mod.catalog.disabled_names("telegram") == {"a", "c"}
