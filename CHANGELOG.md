# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add the `ArisuExample` V3 node (category `Arisu`), a placeholder that inverts an image batch and can log its widget values to the server console.
- Add the ComfyUI extension entrypoint exposing the node list and the `./web` directory for frontend assets.
- Add project scaffolding: `src` layout, GPL-3.0-only license, README, ruff/mypy/pre-commit configuration, and a uv lockfile.
- Add CI workflows for linting and tests on Python 3.10 and 3.13, backwards-compatibility validation via `node-diff`, and publishing to the Comfy registry on tag.
