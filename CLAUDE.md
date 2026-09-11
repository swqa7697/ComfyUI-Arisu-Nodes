# CLAUDE.md — ComfyUI-Arisu-Nodes

ComfyUI custom node pack on the V3 API (`comfy_entrypoint` + `io.Schema`). Python >=3.10 (developed on 3.13), uv-managed, `src` layout. ComfyUI imports the repo-root `__init__.py`. Nodes are grouped by family in `src/arisu_nodes/<family>/`: `core.py` is stdlib-only, `nodes.py` needs ComfyUI's source tree and torch. `README.md` is the human-facing guide; this file is for agents.

## Agent integration

Claude Code reads this file directly; Codex reads the root `AGENTS.md` symlink to it.
Keep that symlink and edit this file for shared project rules. Codex discovers
`.agents/skills/release-pr`, a relative symlink to `.claude/skills/release-pr`;
edit the shared skill there. Invoke it as `/release-pr` in Claude Code or
`$release-pr` in Codex. Both agents use the same ignored `.claude/comfyui-env.md`
and its tracked template; do not create a second set of machine facts for Codex.
Run development commands from this checkout. Personal Codex settings in `.codex/`
are ignored; this project needs no model, credential, or permission overrides.
Agent configuration and skills are excluded from the Registry archive.

## Hard boundary: the ComfyUI install at `$COMFYUI_PATH`

`$COMFYUI_PATH` names a live ComfyUI install on the developer's machine, the one tree this repo must never write to. `make comfyui-path` prints the resolved path; this file never spells it out, and an unset `COMFYUI_PATH` means the live install, never "somewhere safe". Machine facts live in the untracked `.claude/comfyui-env.md` (template `.claude/comfyui-env.example.md`); read it if present, otherwise ask rather than guess. The install is an always-on user systemd unit on the only GPU (restarting it is the owner's test loop) and a uv project alive only because `uv run` syncs inexactly: one `uv sync` there removes every package, and with no `pip` in the `.venv` and a CUDA torch wheel from an index `requirements.txt` omits, a rebuild costs tens of minutes.

Forbidden for the agent, without exception:
- Any uv project command with the working directory under `$COMFYUI_PATH` (`uv sync`, `uv add`, `uv remove`, `uv lock`, `uv run` without `--no-project`); `--active` on any uv command; `UV_PROJECT_ENVIRONMENT` or `VIRTUAL_ENV` pointing at `$COMFYUI_PATH/.venv` (shell, `.env`, script).
- `pip install` or any `uv pip install|uninstall|sync` targeting `$COMFYUI_PATH/.venv/bin/python`.
- Creating, editing, deleting, or `chmod` on anything under `$COMFYUI_PATH` (`.venv/` and `custom_nodes/` included); `git` writes to that checkout; `systemctl --user start|stop|restart`.

The one carve-out is CI: `.github/workflows/comfyui-lane.yml` clones ComfyUI into the runner's temp dir and points `COMFYUI_PATH` there, where `git clone`, `uv venv`, `uv pip install`, and editing `requirements.txt` are fine. Never point that workflow, or `COMFYUI_PATH`, at a developer's install; a local disposable clone unlocks nothing either.

Allowed reads, all leaving `$COMFYUI_PATH` byte-identical: `uv run --no-project --python "$COMFYUI_PATH/.venv/bin/python" --with <pkg> ...` with `PYTHONDONTWRITEBYTECODE=1`, as `scripts/test-comfyui.sh` does; `uv pip freeze -p "$COMFYUI_PATH/.venv/bin/python"`; reading and grepping the source tree; `systemctl --user status`, `journalctl --user -u`, and `curl -s <api_endpoint>/object_info` for the unit and endpoint in `.claude/comfyui-env.md`.

Human-only steps, which the agent may print but never runs: manual E2E (clone a pushed commit into `$COMFYUI_PATH/custom_nodes/`, restart, test in the browser, remove the clone, restart; never symlink the working copy); additive `uv pip install --python "$COMFYUI_PATH/.venv/bin/python" <pkg>`, preceded by a snapshot `uv pip freeze -p <that python> > "$COMFYUI_PATH/venv-snapshot-$(date +%F).txt"` (none exists yet); recovery via `uv pip install --python <that python> -r <snapshot>` with the torch family from `https://download.pytorch.org/whl/<cuXXX>` for the recorded build; and the optional `chmod -R a-w "$COMFYUI_PATH/.venv"` lock, which ComfyUI upgrades and ComfyUI-Manager need lifted.

## Layout

- `__init__.py` — the module ComfyUI imports: `ComfyExtension` subclass + `comfy_entrypoint`.
- `src/arisu_nodes/<family>/core.py` — stdlib-only logic. `nodes.py` — `io.ComfyNode` classes importing `comfy_api` and torch; ends with `NODES: List[Type[io.ComfyNode]]`, which the root `__init__.py` concatenates. `routes.py` (only `common` has one) — aiohttp handlers behind frontend buttons and the browse dialog, registered on `PromptServer.instance.routes` from the extension's `on_load`; validation stays in `core.py`. Families: `minimax_h3` and `common` (live), `anima` (reserved). Every subpackage needs an `__init__.py`: `find_packages` silently drops a directory without one.
- `tests/unit/`, `tests/comfyui/`, `tests/support/`, `tests/web/` — the three lanes and their shared fakes (see Testing); `tests/web/support/` holds the web lane's resolve hook and fakes. `scripts/` — `test-comfyui.sh`, `biome.sh` (the pinned Biome release through `pnpm dlx`), `ensure_deps.sh` (uv, pnpm, node), the stdlib release CLIs (`release_*.py`), and the shell bodies of the make targets, each touching only this checkout.
- `.github/workflows/` — `build-pipeline.yml` (PR gate), `comfyui-lane.yml` (weekly and manual, a throwaway ComfyUI clone on CPU-only torch, never a gate), `publish_node.yml` (`vX.Y.Z` tags only).
- `.claude/` — only `skills/release-pr/SKILL.md` and `comfyui-env.example.md` are tracked. `Makefile` — every dev task (`make help`); refuses to run under `$COMFYUI_PATH`. `tidy.sh` — the formatter chain behind `make tidy`. `biome.json` — the JavaScript formatter and linter config, scoped to `web/js` and `tests/web`. `web/docs/<node_id>/en.md` — node help pages, flat by id (ComfyUI's lookup contract). `web/js/<family>/` — frontend assets, globbed `**/*.js`; served at `/extensions/<pack dir>/js/<family>/`, so a script imports the frontend core with four `../` (`../../../../scripts/app.js`), which `test_pack.py` checks.
- `.comfyignore` — the paths `comfy node publish` leaves out of the registry archive, which is otherwise every git-tracked file; it ships `__init__.py`, `src/`, `web/`, `assets/`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, `LICENSE`, and `example_workflows/`, and nothing else. A new top-level dev-only file or directory has to be added to it (`biome.json` is), or it lands in every ComfyUI-Manager install and in front of the registry's security scan.

## Security and vulnerability prevention

These rules apply to shipped nodes and frontend routes. Consult the [Comfy Registry security standards](https://docs.comfy.org/registry/standards) when changing execution or installation behavior. `AGENTS.md` is a symlink to this file; preserve that single source of truth.

- **Server-owned authorization.** Treat workflow values, linked inputs, query parameters, request bodies and browser bookmarks as untrusted. Image roots come only from the built-in input/output directories and the startup snapshot of administrator-owned `user/__arisu_nodes/config.arisu.jsonc` (`common/paths.py`), resolved through ComfyUI's system-user directory API. Never let an HTTP route, workflow or ComfyUI user setting add roots, choose the configuration file, or supply a base directory. Create a commented empty template exclusively on first extension startup, never overwrite existing files or follow symlinked configuration destinations, and initialize only against temporary directories in tests. JSONC accepts line/block comments without changing quoted strings; reject duplicate keys, trailing commas and malformed content. Ignore the old pack-local allowlist; migration is manual. Initialization errors grant no external roots; configuration changes require restart. Keep the local file out of Git and published artifacts.
- **UI restrictions are not authorization.** Load Image's location widgets are persisted but hidden and socketless; Browse owns UI selection. Preserve selections only when reopening saved workflows or restoring existing tabs/undo history using frontend-owned workflow context. Imports, paste, node/workflow duplication, workflow insertion and unknown contexts clear path/crop/preview and reset root to input before image access; imported IDs and filenames never establish restoration permission. Invalidate pending preview and dialog work on reset or removal. Remove restored location wires with a reselection warning. Direct API and workflow JSON inputs remain untrusted and must pass the same server-side checks. Never relax containment because an input is hidden or cannot be wired in the normal UI. Preview & Save prefixes remain relative to output, independently of configured image-read roots; temporary previews remain beneath temp.
- **Contain every filesystem access.** Reuse `common/core.py`'s path helpers. Reject absolute, home-expanded, drive/UNC, null-byte, alternate-stream and `..` paths before normalization; handle both separators consistently. Resolve base and target with `realpath` and compare with `commonpath`, never string prefixes or `abspath` alone. Apply the same checks to node execution, validation, fingerprinting and routes; linked inputs do not bypass runtime checks. Accept only regular image files, omit escaping symlinks, stop browse ancestors at the selected root, and expose only root IDs plus relative paths. Legacy absolute paths require reselection, not an unrestricted compatibility fallback.
- **Validate before side effects.** Preview references stay beneath temp and save destinations beneath output. Validate the entire preview batch before loading models or writing files. Expand filename placeholders before containment checks, check before directory creation and immediately before opening the final target, and create output files exclusively. Existing files and symlinks are collisions; advance the counter rather than overwrite or follow them.
- **Decode raster content only.** Extensions and MIME guesses are filters, not proof of file contents. Use the shared restricted raster opener for node loading and view rendering; preview saves accept PNG only. Never enable document/vector interpreters for renamed files. Serve decoded PNG/WebP pixels with source metadata removed and `X-Content-Type-Options: nosniff`, not raw files or automatically selected compressed sidecars. Refuse SVG and disguised EPS/WMF. Preserve intended workflow metadata in saved PNGs.
- **Bound HTTP work and sanitize errors.** Require JSON save bodies; enforce the 1 MiB body and 256-preview limits, including streamed bodies. Permit one save worker at a time and keep its guard until the worker finishes, even if the request is cancelled. Keep blocking work off the event loop. Return appropriate 4xx errors for rejected input and generic unexpected-error responses; keep physical paths and decoder/model exception details in server logs. Build DOM labels with text content, never untrusted HTML.
- **Avoid unsafe execution.** Do not introduce `eval`/`exec`, user-controlled shell commands, unsafe deserialization or runtime package installation. Use ComfyUI's supported model-loading APIs and validate selected models against installed names. Keep development installers and release tooling out of shipped runtime code; do not embed credentials or local machine data in source, examples or image metadata.
- **Keep publishing deliberate.** Publish only matching `vX.Y.Z` release tags, use read-only repository permissions, and disable persisted checkout credentials. This project intentionally uses action version tags and `Comfy-Org/publish-node-action@main`; do not replace them with exact commit hashes or a direct `comfy-cli` install/invocation. Pass the Registry secret through the action's token input and use `skip_checkout: 'true'` after the workflow's own checkout.
- **Regressions and review artifacts.** Follow the test-growth ladder below. Cover external-root success and refusals, traversal/encoding variants, file and directory symlinks, unchanged outside sentinels, disguised documents, malformed/oversized requests and worker cancellation at the owning layer. Inspect the prospective Registry archive, including new files and example metadata. Put security reports, manifests and review archives in ignored `.tmp/`, never in new root-level tracked documents; maintain lasting rules here. Distinguish verified fixes from host-level assumptions and pending Registry/browser review.

## Commands

```bash
make install                   # .venv + dev group; installs uv, pnpm, and node if missing; LOCKED=1 adds --locked (CI)
make tidy                      # write mode: ruff format, ruff check --fix, uv-sort, beautysh, mbake, biome check --write
make lint                      # check only: ruff check, ruff format --check, biome ci
make test                      # unit lane, then web lane (test-unit test-web); what the PR gate runs; takes no ARGS
make test-unit ARGS="-k x"     # unit lane alone
make test-web ARGS="--test-name-pattern=x"  # web lane alone, on Node's built-in runner
make test-comfyui ARGS="-v"    # ComfyUI lane on ComfyUI's interpreter; reads $COMFYUI_PATH, writes nothing
make test-count                # selected cases per lane; compare with the budgets below
make build                     # uv build; dist/ is gitignored (make clean / make uninstall remove outputs)
```

Run `make tidy`, then `make lint test`, then `make build`, and commit whatever `make tidy` rewrites: the PR gate runs `make install LOCKED=1`, `make tidy && git diff --exit-code`, `make lint`, `make test` (unit and web lanes), `make build` on 3.10 and 3.13, with Node 24 from `actions/setup-node` and the latest pnpm from `pnpm/action-setup`. Development machines get uv, pnpm, and node together from `scripts/ensure_deps.sh` (pnpm standalone, node via `pnpm env`; npm is never used). The JavaScript tooling has no `package.json`, lockfile, or `node_modules`: `pnpm dlx` runs the Biome version pinned in `scripts/biome.sh`. `pytest` alone deselects the `comfyui` marker via `addopts`; `scripts/test-comfyui.sh` passes `-m comfyui` (`ARGS` is appended word-split).

## Testing

### Lanes and layout

- Every decision, validation, or string-building step that does not need a tensor goes in `core.py`; anything importing `comfy_api` or `torch` lives in `nodes.py` and is tested in `tests/comfyui/` with `pytestmark = pytest.mark.comfyui`. The same split applies to the release CLIs: pure helpers in `scripts/release_common.py`, tested in `tests/unit/test_release_common.py`; git and prompts stay in the CLI `main()`s.
- The unit lane stays ComfyUI-free: nothing under `tests/unit/` imports `comfy_api`, `torch`, or `tests.support.comfy`, and `make test` (unit lane, then web lane) must pass with no ComfyUI install.
- The web lane (`tests/web/`) covers `web/js` on Node's built-in runner (`node --test`, `node:assert/strict`) and needs nothing but Node: no ComfyUI, no `package.json`. Nothing test-related may live under `web/`: ComfyUI globs `**/*.js` there and the browser loads every file. A test file imports the real shipped script once, takes the extension from the fake `app.registerExtension` record, calls `beforeRegisterNodeDef` on a bare `{ prototype: {} }`, and drives the hooks on plain-object doubles; shipped scripts get no exports for tests. Flat `test()` calls, no `describe`: Node's `# tests` count includes subtests, and `make test-count` reads it.
- `tests/web/support/hooks.mjs` is the web lane's conftest: a `module.registerHooks` resolve hook that maps the four-`../` `scripts/app.js` and `scripts/api.js` specifiers to `app.mjs` and `api.mjs`; wiring only, no fakes. The fakes sit beside it, one module per seam (`app.mjs`, `api.mjs`, `litegraph.mjs`).
- One test module per source module, `test_<module>.py` (web lane: `<script>.test.mjs`), inside the family directory. Split a large module by behaviour as `test_<module>_<behaviour>.py` (`<script>_<behaviour>.test.mjs`), never by node count.
- Shared fakes live in `tests/support/`, one module per seam (`comfy.py`). A double used by one file may stay local; the moment a second file needs it, it moves. Never import from another test module. Local `@pytest.fixture`s and driver helpers are fine (`pack` in `test_pack.py`).
- The two `conftest.py` files do `sys.path` wiring, collection control, and the interpreter setup that must land before the lane's modules import (the CPU-mode shim); no fixtures or fakes go there.
- The ComfyUI lane must be green before asking the user to run a manual E2E. Its `GET_SCHEMA()` test is the only early warning that the node will load.
- Fix code, not tests, when a test fails.

### Test growth rules

The suite was pruned from 102 to 28 collected cases on 2026-09-07 (unit 78 → 15, ComfyUI 24 → 13). These rules keep it that way: a new test must earn its place.

- **Regression-first, mandatory decision ladder.** The regression trunks, highest first: `tests/comfyui/test_pack.py` (the pack loads like ComfyUI, the node-id list, the input-id/`execute` contract, help pages); `tests/comfyui/<family>/test_nodes*.py` (execute-level with stubs: conditioning payload, latent geometry, refusals); `tests/unit/<family>/test_core.py` (boundaries and branches no execute test reaches). For `web/js`, `test_pack.py` (every import URL resolves) is the trunk and `tests/web/<family>/<script>.test.mjs` the execute-level layer; there is no lower layer, the scripts have no pure module and none is added. Before writing ANY new test, read the trunk tests for the changed behaviour, then stop at the first step that applies:
  1. Existing regression tests already verify the change → add **nothing**.
  2. They don't, but extending one is a suitable way to verify it → **extend that test only**.
  3. Only when neither holds may a new test be added, at the highest layer that owns the behaviour. A new node is usually step 2 at the pack layer (append to `EXPECTED_NODE_IDS`) plus step 3 for behaviour no stub test covers. A pure helper gets a unit test only for a boundary or branch the execute tests cannot reach.
- **Banned test shapes.** No tests of constants (`*_MODES` tuples, regexes on their own), `io.Schema` defaults, getters, enum values, or test doubles; no "the stub was called with the args the source passes" mirrors; no assertions on help-page or README copy; no `read_text()` substring assertions against `pyproject.toml`, `CHANGELOG.md`, `web/docs`, or source files. Web lane: no tests of the `HYBRID_WIDGETS` / `SETTINGS_KEYS` / `NODE_TYPES` tables, no assertions on toast wording (severity only), no "`fetchApi` was called with what the source passes" mirrors; the JSON body posted to `/arisu/save_image` may be asserted, since it is the contract `core.parse_save_request` validates. Parity between duplicated text (README node table vs schema, docs vs code, changelog vs version) is kept by review, never by tests.
- **Scope floor.** No one-assert micro tests or micro test files. Anything smaller than behaviour worth breaking becomes another step of an existing scenario test, carrying its story as a comment.
- **Parametrize policy.** `@pytest.mark.parametrize` is for small curated tables only; an exhaustive input→output table goes in one loop-bodied test with a per-case message (`assert actual == expected, f"case={case!r}"`). Parametrize does not reduce the collected count: N params collect as N tests.
- **Shared fakes only.** See the layout rule above.
- **Nothing disabled.** No committed `xfail`, `pytest.mark.skip`, `test.skip`, or `test.todo`. Both environment guards live in `tests/comfyui/conftest.py` — `collect_ignore_glob` for no ComfyUI, the CPU-mode shim for no CUDA — and neither one disables a case: the lane runs whole on CPU. Do not add runtime skips to tests, and never make a case conditional on the hardware.
- **Budget (collected cases).** Unit lane ≤ 50, ComfyUI lane ≤ 30, web lane ≤ 20; landed counts 19, 18, and 9 (2026-09-08). These are round ceilings that should never be reached, not targets to fill. Check with `make test-count`. A change that materially grows a count must say why a regression test could not cover it. Nothing enforces this in CI; it holds because you read it.

## Node conventions (V3)

- `node_id` is prefixed `Arisu` and globally unique across a ComfyUI install; category `Arisu Nodes/<Family>` (e.g. `Arisu Nodes/MiniMax H3`).
- `define_schema` and `execute` are both `@classmethod`; input and output ids are unique.
- Never define `NODE_CLASS_MAPPINGS`; ComfyUI checks V1 first and would skip the entrypoint.
- Register every node in its family's `NODES` list (imported by the root `__init__.py`), add `web/docs/<node_id>/en.md`, and extend `EXPECTED_NODE_IDS` in `tests/comfyui/test_pack.py`.
- MiniMax H3 helpers are re-implemented from `comfy_extras/nodes_minimax_h3.py`, never imported from it: its underscore-private names have no stability guarantee. Pure math lives in `minimax_h3/core.py`; the three tensor helpers in `minimax_h3/nodes.py` use only public APIs.

## Code style

- ruff is the only Python formatter and linter; its config lives in `pyproject.toml`: 140 columns, target py310, ruff's default rule set plus the `extend-select` and `ignore` lists there. Keep syntax 3.10-compatible; CI runs 3.10 and 3.13.
- beautysh (4-space indent) formats shell scripts, mbake formats the Makefile, uv-sort sorts pyproject dependency lists. Run all of them only via `make tidy`.
- Biome is the only JavaScript formatter and linter (`web/js`, `tests/web`); its config is `biome.json` (2-space indent, double quotes, semicolons, 140 columns, the recommended preset with `complexity/noArguments` off: the LiteGraph hook wrappers forward `arguments` on purpose) and its version is pinned once, in `scripts/biome.sh`. Run it only via `make tidy` / `make lint`. Its import sorter keeps every import on one single-quoted line, the shape `test_pack.py`'s import regex needs.
- `from __future__ import annotations`, full type hints, Google-style docstrings as in `core.py`.
- Pure functions in `core.py`; side effects (logging, tensors) stay in `nodes.py`.
- YAGNI: build only what is needed now. DRY: extract only when logic has one reason to change. Delete dead code instead of commenting it out.

## Typing conventions

Always use `typing` module annotations. Do not use PEP 604 unions or PEP 585 builtin generics.

- `Optional[X]`, not `X | None`. `Union[X, Y]`, not `X | Y`.
- `List`, `Dict`, `Tuple`, `Set`, `Type`, `Callable`, `Iterable`, `Awaitable`, etc. from `typing`, not the `list` / `dict` builtins or `collections.abc`.
- Preserve generics with `TypeVar` / `ParamSpec` on decorators and wrappers so input types propagate.
- Narrow `Union[Any, ...]` to `Any` (a `Union` containing `Any` collapses).
- Add an explicit return type to every function or method that returns a value (including `Optional[X]`, `Iterator[X]`, and generic returns). Omit `-> None` on procedures; write it only when "returns nothing" is itself part of the contract, such as a callback or override whose annotated signature documents the interface (`pytest_configure` in `tests/conftest.py`).
- ruff cannot enforce the `typing` forms; the `UP006/UP007/UP035/UP045/UP046/UP047` ignores in `pyproject.toml` only stop `ruff check --fix` from rewriting them, so this is a review rule. Overrides of ComfyUI classes use the `typing` forms too (`List[Type[io.ComfyNode]]`); they stay compatible with the base signature.

## Import conventions

All imports go at the top of the file. No inline imports inside functions or methods unless truly necessary; the accepted reasons are:

1. Breaking a genuine circular import that cannot be resolved by restructuring.
2. An optional heavy dependency loaded lazily in a code path that may never execute (rare; document it with a one-line comment).
3. A platform- or feature-gated import behind a runtime check.

If you reach for an inline import for any other reason (avoiding work, hiding a dependency, working around a startup ordering issue), restructure instead. ruff sorts top-level imports via isort (`extend-select = ["I"]`); the first-party roots are `src = [".", "scripts", "src", "tests"]` in `pyproject.toml`, mirroring the `sys.path` wiring in `tests/conftest.py`, so `src.arisu_nodes` and `release_common` sort into the first-party block.

## Git workflow and commits

- Never `git add`, `git commit`, or `git push` unless explicitly asked; ask before planning one. `make release-commit`, `make tag`, and the release PR skill (`/release-pr` in Claude Code, `$release-pr` in Codex) all write to git, so the rule covers them.
- Never commit directly to `main`: non-trivial work goes on a branch with a PR to `main`, and only the PR gate gates a merge (the ComfyUI lane workflow fires from the default branch only, never on a feature branch). Commit directly to `dev` only if the user has confirmed they are a repo admin; otherwise branch off `dev` and open a PR. `make tag` pushing `vX.Y.Z` from `main` is the one exception, and it pushes a tag, not a commit.
- Conventional Commits: `<type>(<scope>): <summary>`, imperative, lowercase, no period, <=72 chars. Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert. Scopes (optional): `nodes`, `core`, `tests`, `ci`, `docs`, `web`. Write commit messages in English. Format commit message bodies as concise bullet points, with an optional short summary above the bullets only when it really helps, e.g. `feat(nodes): add BrightnessGate node` over `- Add mean-brightness gate with above/below modes` and `- Keep threshold clamping in core.py with unit tests`. The one exempt commit is the release commit, whose subject is fixed at `release arisu_nodes: X.Y.Z` by `release_subject` in `scripts/release_common.py`.

## Changelog and versioning

`CHANGELOG.md` follows Keep a Changelog: user-visible changes only, one imperative bullet each under `[Unreleased]` in Added / Changed / Deprecated / Removed / Fixed / Security; skip refactors, formatting, and dependency bumps. `pyproject.toml`'s `version` is the only version file. Release flow, each step refusing when its preconditions fail (documented in `scripts/release_*.py`):
1. `git switch -c release/X.Y.Z` from an up-to-date `main`.
2. `make bump-patch|minor|major` rewrites the version, renames `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` with a new empty `[Unreleased]` above it, and runs `uv lock`; no git writes.
3. `make release-commit [YES=1]` commits `release arisu_nodes: X.Y.Z` and pushes the branch; only `pyproject.toml`, `CHANGELOG.md`, and `uv.lock` may have changed.
4. `/release-pr` (Claude Code) or `$release-pr` (Codex) opens `main <- release/X.Y.Z`; title from the commit, body from the changelog.
5. After the merge, on `main` at `origin/main`: `make tag` creates the annotated tag `vX.Y.Z` behind a rendered CAPTCHA and pushes it, triggering `publish_node.yml` (`REGISTRY_ACCESS_TOKEN`).
