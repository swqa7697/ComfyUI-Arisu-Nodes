SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help
.PHONY: help install uninstall clean build test test-comfyui test-count comfyui-path lint format tidy upgrade bump-major bump-minor bump-patch release-commit tag

# Hard boundary (CLAUDE.md): never run project commands inside the live ComfyUI
# install, including a clone of this repo under its custom_nodes/.
# The default here is the single source of truth; `make comfyui-path` prints what
# it resolves to. The $(if ...) treats COMFYUI_PATH= (set but empty) as unset,
# which would otherwise leave the guard pattern matching every directory.
COMFYUI_PATH := $(if $(strip $(COMFYUI_PATH)),$(COMFYUI_PATH),$(HOME)/apps/comfyui)
COMFYUI_ABS := $(abspath $(COMFYUI_PATH))
ifneq ($(filter $(COMFYUI_ABS)/%,$(CURDIR)/),)
$(error refusing to run inside the live ComfyUI install at $(COMFYUI_ABS); see CLAUDE.md)
endif

# Exported per target, not globally: tests/conftest.py puts COMFYUI_PATH on
# sys.path whenever it is set, and the unit lane must stay ComfyUI-free.
test-comfyui: export COMFYUI_PATH := $(COMFYUI_ABS)

GREEN := \033[0;32m
RED := \033[0;31m
NC := \033[0m
# Recursive (=) so $@ resolves to the target being run at each use site.
INFO = printf "$(GREEN)[$@]$(NC) %s\n"
FAIL = printf "$(RED)[$@]$(NC) %s\n"

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv with the dev group via uv (LOCKED=1 adds --locked, as CI does)
	@LOCKED="$(LOCKED)" bash scripts/install.sh

uninstall: ## Remove .venv, caches, and build outputs (keeps uv.lock)
	@bash scripts/uninstall.sh

clean: ## Remove caches and build outputs (keeps .venv)
	@bash scripts/clean.sh

build: ## Build wheel + sdist into dist/
	@uv build

test: ## Run the unit lane (tests/unit); what CI runs
	@uv run pytest || ([ $$? -eq 5 ] && $(INFO) "no tests collected")

test-comfyui: ## Run the ComfyUI lane on ComfyUI's interpreter, read-only (ARGS="-v -k name")
	@bash scripts/test-comfyui.sh $(ARGS)

test-count: ## Collected tests per lane; compare with the budgets in CLAUDE.md
	@printf 'unit lane:    '; uv run pytest --collect-only -q | tail -1
	@printf 'comfyui lane: '; bash scripts/test-comfyui.sh --collect-only -q 2>/dev/null | tail -1 || $(INFO) "skipped (no ComfyUI install)"

comfyui-path: ## Print the resolved ComfyUI install root (the CLAUDE.md hard boundary)
	@printf '%s\n' '$(COMFYUI_ABS)'

lint: ## Check only: ruff check + ruff format --check
	@uv run ruff check .
	@uv run ruff format --check .

tidy: ## Rewrite in place: ruff format, ruff check --fix, uv-sort, beautysh, mbake
	@bash tidy.sh

format: tidy ## Alias for tidy

upgrade: ## Upgrade deps to latest and raise pyproject.toml minimums
	@$(INFO) "re-resolving uv.lock at latest versions and raising pyproject.toml minimums..."
	@uvx uv-bump --verbose
	@$(INFO) "re-syncing so uv.lock records the new requirements..."
	@uv sync --all-groups
	@$(INFO) "done. review the pyproject.toml / uv.lock diff, then run: make lint test"

# Stdlib-only release CLIs (scripts/release_*.py). --no-project runs them on the
# .venv interpreter (or the .python-version one) without syncing, so nothing
# re-locks or reinstalls the project between the bump and the release commit.
_PY := uv run --quiet --no-project python

bump-major: ## Bump major (X.0.0): pyproject.toml, roll CHANGELOG [Unreleased], uv lock; no git writes
	@$(_PY) scripts/release_bump.py major

bump-minor: ## Bump minor (x.Y.0): pyproject.toml, roll CHANGELOG [Unreleased], uv lock; no git writes
	@$(_PY) scripts/release_bump.py minor

bump-patch: ## Bump patch (x.y.Z): pyproject.toml, roll CHANGELOG [Unreleased], uv lock; no git writes
	@$(_PY) scripts/release_bump.py patch

release-commit: ## On a release branch: commit + push the bump as 'chore: bump version to X.Y.Z' (YES=1 skips the prompt)
	@$(_PY) scripts/release_commit.py $(if $(filter 1 true yes,$(YES)),--yes)

tag: ## On the latest main: annotated tag v<pyproject version> after a CAPTCHA, then push (triggers publish_node.yml)
	@$(_PY) scripts/release_tag.py