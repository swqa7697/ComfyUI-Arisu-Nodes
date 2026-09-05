# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add the `ArisuExample` V3 node (category `Arisu`), a placeholder that inverts an image batch and can log its widget values to the server console.
- Add the ComfyUI extension entrypoint exposing the node list and the `./web` directory for frontend assets.
- Add project scaffolding: `src` layout, GPL-3.0-only license, README, ruff configuration, and a uv lockfile.
- Add CI workflows for linting and tests on Python 3.10 and 3.13, and publishing to the Comfy registry on tag.
- Add two test lanes: `tests/unit` runs without ComfyUI (and in CI), `tests/comfyui` loads the pack the way ComfyUI does and runs on ComfyUI's interpreter via `scripts/test-comfyui.sh`.
- Add a `Makefile` (`make help`) wrapping install, tidy, lint, test, and build, and run CI through it.
- Add the release flow: `make bump-patch|minor|major`, `make release-commit`, and a CAPTCHA-gated `make tag`, plus the `/release-pr` Claude skill that opens the release PR.
