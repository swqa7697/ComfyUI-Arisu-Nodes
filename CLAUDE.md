# CLAUDE.md — ComfyUI-Arisu-Nodes

ComfyUI custom node pack on the V3 API (`comfy_entrypoint` + `io.Schema`). Python >=3.10
(developed on 3.13), uv-managed, `src` layout. ComfyUI imports the repo-root `__init__.py`.
Nodes are grouped by family in `src/arisu_nodes/<family>/`: `core.py` is stdlib-only,
`nodes.py` needs ComfyUI's source tree and torch. `README.md` is the human-facing guide; this file is for agents.

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

Every rule above is scoped to that path. The ComfyUI lane has a second execution context, the
throwaway clone `.github/workflows/comfyui-lane.yml` builds on a CI runner, where `git clone`,
`uv venv`, `uv pip install`, and editing `requirements.txt` are all fine: `COMFYUI_PATH` points
at the clone, nothing is shared with this machine, and the runner is discarded. Never point that
workflow, or `COMFYUI_PATH`, at `/home/ray/apps/comfyui`.

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
- `src/arisu_nodes/<family>/core.py` — stdlib-only logic, unit-tested without ComfyUI.
- `src/arisu_nodes/<family>/nodes.py` — `io.ComfyNode` classes; imports `comfy_api` and torch;
  ends with `NODES: List[Type[io.ComfyNode]]`, which the root `__init__.py` concatenates.
  Families: `minimax_h3` (live), `common` and `anima` (reserved, empty `__init__.py` only).
  Every subpackage needs an `__init__.py`: `packages.find` uses `find_packages`, so a directory
  without one silently drops out of the wheel. Use `.gitkeep` only in non-Python dirs (`web/js/`).
- `tests/unit/<family>/` — ComfyUI-free lane. `tests/comfyui/<family>/` plus
  `tests/comfyui/test_pack.py` (loads the pack like ComfyUI, asserts the node-id list) — opt-in
  lane, marker `comfyui`. Test subdirectories carry an `__init__.py` so basenames may repeat.
  One test module per source module (`test_core.py`, `test_nodes.py`); a module split by
  behaviour is `test_<module>_<behaviour>.py` (`test_nodes_context_resize.py`).
- `tests/support/` — shared fakes for the ComfyUI lane, one module per seam (`comfy.py`: stub
  CLIP and VAEs, tensor builders). It imports torch, so only `tests/comfyui/` may import it.
- `tests/conftest.py` — sys.path wiring (repo root, then `scripts/`, then ComfyUI); collects
  the repo root as a plain directory so the entry `__init__.py` is never imported during
  collection. Do not weaken this.
- `tests/comfyui/conftest.py` — the lane's environment gate: `collect_ignore_glob` when
  `comfy_api` is missing, plus `comfy.cli_args.args.cpu = True` when torch reports no CUDA, set
  before `comfy.model_management` imports and probes VRAM. ComfyUI takes CPU mode only from
  `--cpu` and `cli_args` parses an empty argv off `main.py`, so there is nothing else to set; the
  write is in-memory only.
- `scripts/test-comfyui.sh` — runs the ComfyUI lane on ComfyUI's interpreter, writing nothing.
- `scripts/release_common.py`, `release_bump.py`, `release_commit.py`, `release_tag.py` —
  stdlib-only release CLIs behind `make bump-*`, `make release-commit`, `make tag`. The pure
  helpers in `release_common.py` are unit-tested; the git plumbing is not.
- `.github/workflows/build-pipeline.yml` — the PR gate. `comfyui-lane.yml` — the ComfyUI lane
  weekly and on manual dispatch, against a throwaway clone of ComfyUI's latest tag on CPU-only
  torch; never a gate. `publish_node.yml` — vendored from Comfy-Org, fires on `vX.Y.Z` tags only.
- `.claude/skills/release-pr/SKILL.md` — the `/release-pr` skill; the only tracked part of
  `.claude/` (`.gitignore` ignores the rest).
- `Makefile` — entry point for every dev task; `make help` lists targets. Refuses to run from
  a directory under `COMFYUI_PATH` (default `~/apps/comfyui`).
- `tidy.sh` — the write-mode formatter chain behind `make tidy` (ruff, uv-sort, beautysh, mbake).
- `scripts/logger.sh` — shared `log_info/log_ok/log_warn/log_error`; sourced by every script.
- `scripts/install.sh`, `uninstall.sh`, `clean.sh`, `ensure_deps.sh` — bodies of the matching
  make targets; each `cd`s to the repo root and touches only this checkout.
- `web/docs/<node_id>/en.md` — node help pages, flat by id (ComfyUI's lookup contract).
  `web/js/<family>/` — frontend assets; the server globs `**/*.js` recursively.

## Commands

```bash
make install                     # .venv + dev group; LOCKED=1 adds --locked (CI)
make tidy                        # write mode: ruff format, ruff check --fix, uv-sort, beautysh, mbake
make lint                        # check only: ruff check, ruff format --check
make test                        # unit lane; what the PR gate runs
make test-comfyui ARGS="-v"      # ComfyUI lane; reads $COMFYUI_PATH, writes nothing
make test-count                  # collected cases per lane; compare with the budgets below
make build                       # uv build; dist/ is gitignored
make clean                       # caches and dist/; `make uninstall` also removes .venv
make bump-patch|minor|major      # rewrite pyproject version, roll CHANGELOG, uv lock; no git writes
make release-commit YES=1        # on a release branch: commit + push the bump; YES=1 skips the prompt
make tag                         # on the latest main: CAPTCHA-gated annotated tag vX.Y.Z + push
```

Run `make tidy`, then `make lint test`, then `make build`. The PR gate runs `make install
LOCKED=1`, `make tidy && git diff --exit-code`, `make lint`, `make test`, `make build` on 3.10
and 3.13, so whatever `make tidy` rewrites must be committed. A second workflow runs
`make test-comfyui` weekly and on demand on 3.13 against a fresh clone of ComfyUI's latest tag
with CPU-only torch; it gates nothing, and a red run means this pack or that release changed.
`pytest` alone deselects the `comfyui` marker via `addopts`; `scripts/test-comfyui.sh` passes
`-m comfyui` to override it, and `ARGS` is appended word-split (quote-free flags only).

## Testing

### Lanes and layout

- Every decision, validation, or string-building step that does not need a tensor goes in
  `core.py`; anything importing `comfy_api` or `torch` lives in `nodes.py` and is tested in
  `tests/comfyui/` with `pytestmark = pytest.mark.comfyui`. The same split applies to the
  release CLIs: pure helpers in `scripts/release_common.py`, tested in
  `tests/unit/test_release_common.py`; git and prompts stay in the CLI `main()`s.
- The unit lane stays ComfyUI-free: nothing under `tests/unit/` imports `comfy_api`, `torch`,
  or `tests.support.comfy`, and `make test` must pass with no ComfyUI install.
- One test module per source module, `test_<module>.py`, inside the family directory. Split a
  large module by behaviour as `test_<module>_<behaviour>.py`, never by node count.
- Shared fakes live in `tests/support/`, one module per seam (`comfy.py`). A double used by one
  file may stay local; the moment a second file needs it, it moves. Never import from another
  test module. Local `@pytest.fixture`s and driver helpers are fine (`pack` in `test_pack.py`).
- The two `conftest.py` files do `sys.path` wiring, collection control, and the interpreter
  setup that must land before the lane's modules import (the CPU-mode shim); no fixtures or
  fakes go there.
- The ComfyUI lane must be green before asking the user to run a manual E2E. Its
  `GET_SCHEMA()` test is the only early warning that the node will load.
- Fix code, not tests, when a test fails.

### Test growth rules

The suite was pruned from 102 to 28 collected cases on 2026-09-07 (unit 78 → 15, ComfyUI
24 → 13). These rules keep it that way: a new test must earn its place.

- **Regression-first, mandatory decision ladder.** The regression trunks, highest first:
  `tests/comfyui/test_pack.py` (the pack loads like ComfyUI, the node-id list, the
  input-id/`execute` contract, help pages); `tests/comfyui/<family>/test_nodes*.py`
  (execute-level with stubs: conditioning payload, latent geometry, refusals);
  `tests/unit/<family>/test_core.py` (boundaries and branches no execute test reaches). Before
  writing ANY new test, read the trunk tests for the changed behaviour, then stop at the first
  step that applies:
  1. Existing regression tests already verify the change → add **nothing**.
  2. They don't, but extending one is a suitable way to verify it → **extend that test only**.
  3. Only when neither holds may a new test be added, at the highest layer that owns the
     behaviour. A new node is usually step 2 at the pack layer (append to `EXPECTED_NODE_IDS`)
     plus step 3 for behaviour no stub test covers. A pure helper gets a unit test only for a
     boundary or branch the execute tests cannot reach.
- **Banned test shapes.** No tests of constants (`*_MODES` tuples, regexes on their own),
  `io.Schema` defaults, getters, enum values, or test doubles; no "the stub was called with the
  args the source passes" mirrors; no assertions on help-page or README copy; no `read_text()`
  substring assertions against `pyproject.toml`, `CHANGELOG.md`, `web/docs`, or source files.
  Parity between duplicated text (README node table vs schema, docs vs code, changelog vs
  version) is kept by review, never by tests.
- **Scope floor.** No one-assert micro tests or micro test files. Anything smaller than
  behaviour worth breaking becomes another step of an existing scenario test, carrying its story
  as a comment.
- **Parametrize policy.** `@pytest.mark.parametrize` is for small curated tables only; an
  exhaustive input→output table goes in one loop-bodied test with a per-case message
  (`assert actual == expected, f"case={case!r}"`). Parametrize does not reduce the collected
  count: N params collect as N tests.
- **Shared fakes only.** See the layout rule above.
- **Nothing disabled.** No committed `xfail` or `pytest.mark.skip`. Both environment guards live in
  `tests/comfyui/conftest.py` — `collect_ignore_glob` for no ComfyUI, the CPU-mode shim for no
  CUDA — and neither one disables a case: the lane runs whole on CPU. Do not add runtime skips
  to tests, and never make a case conditional on the hardware.
- **Budget (collected cases).** Unit lane ≤ 50, ComfyUI lane ≤ 30; landed counts 15 and 13.
  These are round ceilings that should never be reached, not targets to fill. Check with
  `make test-count`. A change that materially grows a count must say why a regression test could
  not cover it. Nothing enforces this in CI; it holds because you read it.

## Node conventions (V3)

- `node_id` is prefixed `Arisu` and globally unique across a ComfyUI install; category
  `Arisu Nodes/<Family>` (e.g. `Arisu Nodes/MiniMax H3`).
- `define_schema` and `execute` are both `@classmethod`; input and output ids are unique.
- Never define `NODE_CLASS_MAPPINGS`; ComfyUI checks V1 first and would skip the entrypoint.
- Register every node in its family's `NODES` list (imported by the root `__init__.py`), add
  `web/docs/<node_id>/en.md`, and extend `EXPECTED_NODE_IDS` in `tests/comfyui/test_pack.py`.
- MiniMax H3 helpers are re-implemented from `comfy_extras/nodes_minimax_h3.py`, never imported
  from it: its underscore-private names have no stability guarantee. Pure math lives in
  `minimax_h3/core.py`; the three tensor helpers in `minimax_h3/nodes.py` use only public APIs.

## Code style

- ruff is the only Python formatter and linter; its config lives in `pyproject.toml`: 140
  columns, target py310, ruff's default rule set plus the `extend-select` and `ignore` lists
  there. Keep syntax 3.10-compatible; CI runs 3.10 and 3.13.
- beautysh (4-space indent) formats shell scripts, mbake formats the Makefile, uv-sort sorts
  pyproject dependency lists. Run all of them only via `make tidy`.
- `from __future__ import annotations`, full type hints, Google-style docstrings as in `core.py`.
- Pure functions in `core.py`; side effects (logging, tensors) stay in `nodes.py`.
- YAGNI: build only what is needed now. DRY: extract only when logic has one reason to change.
  Delete dead code instead of commenting it out.

## Typing conventions

Always use `typing` module annotations. Do not use PEP 604 unions or PEP 585 builtin generics.

- `Optional[X]`, not `X | None`. `Union[X, Y]`, not `X | Y`.
- `List`, `Dict`, `Tuple`, `Set`, `Type`, `Callable`, `Iterable`, `Awaitable`, etc. from
  `typing`, not the `list` / `dict` builtins or `collections.abc`.
- Preserve generics with `TypeVar` / `ParamSpec` on decorators and wrappers so input types
  propagate.
- Narrow `Union[Any, ...]` to `Any` (a `Union` containing `Any` collapses).
- Add an explicit return type to every function or method that returns a value (including
  `Optional[X]`, `Iterator[X]`, and generic returns). Omit `-> None` on procedures; write it
  only when "returns nothing" is itself part of the contract, such as a callback or override
  whose annotated signature documents the interface (`pytest_configure` in `tests/conftest.py`).
- ruff cannot enforce the `typing` forms; the `UP006/UP007/UP035/UP045/UP046/UP047` ignores in
  `pyproject.toml` only stop `ruff check --fix` from rewriting them, so this is a review rule.
  Overrides of ComfyUI classes use the `typing` forms too (`List[Type[io.ComfyNode]]`); they
  stay compatible with the base signature.

## Import conventions

All imports go at the top of the file. No inline imports inside functions or methods unless
truly necessary; the accepted reasons are:

1. Breaking a genuine circular import that cannot be resolved by restructuring.
2. An optional heavy dependency loaded lazily in a code path that may never execute (rare;
   document it with a one-line comment).
3. A platform- or feature-gated import behind a runtime check.

If you reach for an inline import for any other reason (avoiding work, hiding a dependency,
working around a startup ordering issue), restructure instead. ruff sorts top-level imports via
isort (`extend-select = ["I"]`); the first-party roots are `src = [".", "scripts", "src",
"tests"]` in `pyproject.toml`, mirroring the `sys.path` wiring in `tests/conftest.py`, so
`src.arisu_nodes` and `release_common` sort into the first-party block.

## Git workflow and commits

- Never `git add`, `git commit`, or `git push` unless explicitly asked. Ask before planning one.
  `make release-commit` commits and pushes, `make tag` pushes a tag, and `/release-pr` opens a
  PR, so the same rule covers all three.
- Non-trivial work goes on a branch with a PR to `main`. Only the PR gate gates a merge; the
  ComfyUI lane workflow runs on a weekly schedule and on manual dispatch, and GitHub fires both
  of those from the default branch only, so it is never a signal on a feature branch.
- Never commit directly to `main`. Never commit directly to `dev` either, unless the user
  has confirmed they are an admin of the repo; otherwise branch off `dev` and open a PR.
  `make tag` pushing `vX.Y.Z` from `main` is the one exception, and it pushes a tag, not a
  commit.
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
