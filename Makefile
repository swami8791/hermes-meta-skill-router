HERMES_HOME ?= $(HOME)/.hermes
PLUGIN_SRC  := plugin/meta-skill-router
PLUGIN_DST  := $(HERMES_HOME)/plugins/meta-skill-router
PYTHON      ?= python3

.PHONY: help install uninstall test lint clean

help:
	@echo "make install    copy the plugin to $(PLUGIN_DST)"
	@echo "make uninstall  remove it"
	@echo "make test       run the suite (needs HERMES_AGENT_SRC or a sibling ../hermes-agent checkout)"
	@echo "make clean      remove caches"

install:
	@mkdir -p "$(HERMES_HOME)/plugins"
	@rm -rf "$(PLUGIN_DST)"
	@cp -R "$(PLUGIN_SRC)" "$(PLUGIN_DST)"
	@find "$(PLUGIN_DST)" -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "installed -> $(PLUGIN_DST)"
	@echo "enable with: plugins.enabled: [meta-skill-router] in $(HERMES_HOME)/config.yaml"

uninstall:
	@rm -rf "$(PLUGIN_DST)"
	@echo "removed $(PLUGIN_DST)"

test:
	$(PYTHON) -m pytest -q

clean:
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@rm -rf .pytest_cache
