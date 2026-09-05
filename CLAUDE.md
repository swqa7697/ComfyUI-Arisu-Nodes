# CLAUDE.md — ComfyUI-Arisu-Nodes

ComfyUI custom node pack on the V3 API (`comfy_entrypoint` + `io.Schema`). Python >=3.10
(developed on 3.13), uv-managed, `src` layout. ComfyUI imports the repo-root `__init__.py`.
`src/arisu_nodes/core.py` is stdlib-only; `src/arisu_nodes/nodes.py` needs ComfyUI's source
tree and torch. `README.md` is the human-facing guide; this file is for agents.

## Hard boundary: the live ComfyUI install at /home/ray/apps/comfyui

Facts (verified on uv 0.12.9):
- It runs as the user systemd unit `comfyui.service`, always on, on the machine's only GPU.
- The checkout is itself a uv project: `pyproject.toml` with no dependency list plus a
  `uv.lock`, started by `~/.local/bin/comfyui-start` running `uv run python main.py` inside it.
  It survives only because `uv run` syncs inexactly. `uv sync` run in that directory removes
  all ~210 installed packages, with no env var or flag involved.
- Its `.venv` has no `pip` module. torch is a `+cu130` build (~20 min to rebuild).

Forbidden for the agent, without exception:
- Any uv project command with the working directory anywhere under `/home/ray/apps/comfyui`:
  `uv sync`, `uv add`, `uv remove`, `uv lock`, or `uv run` without `--no-project`.
- `UV_PROJECT_ENVIRONMENT` or `VIRTUAL_ENV` pointing at that venv, in the shell, a `.env`, or a
  script. `--active` on any uv command.
- `pip install`, `uv pip install`, `uv pip uninstall`, `uv pip sync`, or `uv pip install --exact`
  targeting `/home/ray/apps/comfyui/.venv/bin/python`.
- Creating, editing, deleting, or `chmod` on anything under `/home/ray/apps/comfyui`, including
  `.venv/` and `custom_nodes/`. `git` commands that modify that checkout.
- `systemctl --user start|stop|restart comfyui.service`.

Allowed reads:
- `uv run --no-project --python /home/ray/apps/comfyui/.venv/bin/python --with <pkg> ...` with
  `PYTHONDONTWRITEBYTECODE=1` set, exactly as `scripts/test-comfyui.sh` does.
- `uv pip freeze -p /home/ray/apps/comfyui/.venv/bin/python`.
- Reading and grepping the source tree (`nodes.py` loader, `comfy_api/latest/_io.py`).
- `systemctl --user status comfyui.service`, `journalctl --user -u comfyui.service`,
  `curl -s http://127.0.0.1:8188/object_info`.

Human-only steps. The agent may print these commands but never runs them:
- Manual E2E: clone a pushed commit into `custom_nodes/`, restart the service, test in the
  browser, remove the clone, restart again. Never symlink the working copy.
- Additive dependency install: `uv pip install --python /home/ray/apps/comfyui/.venv/bin/python <pkg>`.
- Baseline snapshot, to be taken before any deliberate write (none exists yet):
  `uv pip freeze -p /home/ray/apps/comfyui/.venv/bin/python > ~/apps/comfyui/venv-snapshot-$(date +%F).txt`
- Recovery from a snapshot. There is no `pip` in that venv, so use
  `uv pip install --python /home/ray/apps/comfyui/.venv/bin/python -r <snapshot>`. The torch
  family must come from `https://download.pytorch.org/whl/cu130`; ComfyUI's `requirements.txt`
  lists bare `torch` and does not record the index.
- `chmod -R a-w /home/ray/apps/comfyui/.venv` is an optional lock the owner chose not to apply.
  ComfyUI upgrades and ComfyUI-Manager both write into that venv, so it needs unlocking for them.

## Layout

- `__init__.py` — the module ComfyUI imports: `ComfyExtension` subclass + `comfy_entrypoint`.
- `src/arisu_nodes/core.py` — stdlib-only logic, unit-tested without ComfyUI.
- `src/arisu_nodes/nodes.py` — `io.ComfyNode` classes; imports `comfy_api` and torch.
- `tests/unit/` — ComfyUI-free lane. `tests/comfyui/` — opt-in lane, marker `comfyui`.
- `tests/conftest.py` — sys.path wiring (repo root, then `scripts/`, then ComfyUI); collects
  the repo root as a plain directory so the entry `__init__.py` is never imported during
  collection. Do not weaken this.
- `scripts/test-comfyui.sh` — runs the ComfyUI lane on ComfyUI's interpreter, writing nothing.
- `scripts/release_common.py`, `release_bump.py`, `release_commit.py`, `release_tag.py` —
  stdlib-only release CLIs behind `make bump-*`, `make release-commit`, `make tag`. The pure
  helpers in `release_common.py` are unit-tested; the git plumbing is not.
- `.claude/skills/release-pr/SKILL.md` — the `/release-pr` skill; the only tracked part of
  `.claude/` (`.gitignore` ignores the rest).
- `Makefile` — entry point for every dev task; `make help` lists targets. Refuses to run from
  a directory under `COMFYUI_PATH` (default `~/apps/comfyui`).
- `tidy.sh` — the write-mode formatter chain behind `make tidy` (ruff, uv-sort, beautysh, mbake).
- `scripts/logger.sh` — shared `log_info/log_ok/log_warn/log_error`; sourced by every script.
- `scripts/install.sh`, `uninstall.sh`, `clean.sh`, `ensure_deps.sh` — bodies of the matching
  make targets; each `cd`s to the repo root and touches only this checkout.
- `web/docs/<node_id>/en.md` — node help pages. `web/js/` — frontend assets.

## Commands

```bash
make install                     # .venv + dev group; LOCKED=1 adds --locked (CI)
make tidy                        # write mode: ruff format, ruff check --fix, uv-sort, beautysh, mbake
make lint                        # check only: ruff check, ruff format --check
make test                        # unit lane; what CI runs
make test-comfyui ARGS="-v"      # ComfyUI lane; reads ~/apps/comfyui, writes nothing
make build                       # uv build; dist/ is gitignored
make clean                       # caches and dist/; `make uninstall` also removes .venv
make bump-patch|minor|major      # rewrite pyproject version, roll CHANGELOG, uv lock; no git writes
make release-commit YES=1        # on a release branch: commit + push the bump; YES=1 skips the prompt
make tag                         # on the latest main: CAPTCHA-gated annotated tag vX.Y.Z + push
```

Run `make tidy`, then `make lint test`, then `make build`. CI runs `make install LOCKED=1`,
`make tidy && git diff --exit-code`, `make lint`, `make test`, `make build` on 3.10 and 3.13,
so whatever `make tidy` rewrites must be committed. `pytest` alone deselects the `comfyui`
marker via `addopts`; `scripts/test-comfyui.sh` passes `-m comfyui` to override it, and `ARGS`
is appended word-split (quote-free flags only).

## Testing rules

- Every decision, validation, or string-building step that does not need a tensor goes in
  `core.py` with a test in `tests/unit/`. Cover the happy path and at least one edge case.
  The same split applies to the release CLIs: pure helpers in `scripts/release_common.py`,
  tested in `tests/unit/test_release_common.py`; git and prompts stay in the CLI `main()`s.
- Anything importing `comfy_api` or `torch` lives in `nodes.py` and is tested in
  `tests/comfyui/` with `pytestmark = pytest.mark.comfyui`. Never import either in `tests/unit/`.
- The ComfyUI lane must be green before asking the user to run a manual E2E. Its
  `GET_SCHEMA()` test is the only early warning that the node will load.
- Fix code, not tests, when a test fails.

## Node conventions (V3)

- `node_id` is prefixed `Arisu` and globally unique across a ComfyUI install; category `Arisu`.
- `define_schema` and `execute` are both `@classmethod`; input and output ids are unique.
- Never define `NODE_CLASS_MAPPINGS`; ComfyUI checks V1 first and would skip the entrypoint.
- Register every node in `get_node_list` in `__init__.py` and add `web/docs/<node_id>/en.md`.

## Code style

- ruff is the only Python formatter and linter; its config lives in `pyproject.toml` (140
  columns, target py310). Keep syntax 3.10-compatible; CI runs 3.10 and 3.13.
- beautysh (4-space indent) formats shell scripts, mbake formats the Makefile, uv-sort sorts
  pyproject dependency lists. Run all of them only via `make tidy`.
- `from __future__ import annotations`, full type hints, Google-style docstrings as in `core.py`.
- Pure functions in `core.py`; side effects (logging, tensors) stay in `nodes.py`.
- YAGNI: build only what is needed now. DRY: extract only when logic has one reason to change.
  Delete dead code instead of commenting it out.

## Git workflow and commits

- Never `git add`, `git commit`, or `git push` unless explicitly asked. Ask before planning one.
  `make release-commit` commits and pushes, `make tag` pushes a tag, and `/release-pr` opens a
  PR, so the same rule covers all three.
- Non-trivial work goes on a branch with a PR to `main`; CI runs on PRs only.
- Conventional Commits: `<type>(<scope>): <summary>`, imperative, lowercase, no period,
  <=72 chars. Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert.
  Scopes: `nodes`, `core`, `tests`, `ci`, `docs`, `web`. Scope is optional.
- Body: optional one-paragraph summary, then concise bullets.

```
feat(nodes): add BrightnessGate node

- Add mean-brightness gate with above/below modes
- Keep threshold clamping in core.py with unit tests
```

```
test(core): cover threshold clamp boundaries
```

## Changelog and versioning

- `CHANGELOG.md` follows Keep a Changelog. Add entries under `[Unreleased]` for user-visible
  changes only, as one imperative bullet each, under Added / Changed / Deprecated / Removed /
  Fixed / Security. Skip refactors, formatting, and dependency bumps.
- Release flow, all on `pyproject.toml`'s `version` (the only version file):
  1. `git switch -c release/X.Y.Z` from an up-to-date `main`.
  2. `make bump-patch|minor|major` rewrites the version, renames `[Unreleased]` to
     `[X.Y.Z] - YYYY-MM-DD` with a new empty `[Unreleased]` above it, and runs `uv lock`. No
     git writes. Refuses if any of the three release files is already modified or
     `[Unreleased]` has no entries.
  3. `make release-commit [YES=1]` commits `chore: bump version to X.Y.Z` and pushes the
     branch. Refuses on `main`, if anything but `pyproject.toml`/`CHANGELOG.md`/`uv.lock`
     changed, if the version equals HEAD's, or if `origin/<branch>` exists and is not HEAD.
  4. `/release-pr` opens `main <- release/X.Y.Z`; title is the release commit subject, body
     comes from the `[X.Y.Z]` changelog section and the diff.
  5. After the merge, on `main` at `origin/main`: `make tag` creates the annotated tag
     `vX.Y.Z` (message: `Release vX.Y.Z` over the changelog section) behind a rendered
     CAPTCHA and pushes it. Refuses off `main`, behind/ahead of origin, if HEAD is already
     tagged, or if the tag exists. The push triggers `.github/workflows/publish_node.yml`
     (only `vX.Y.Z` tags do), which needs the `REGISTRY_ACCESS_TOKEN` secret.
