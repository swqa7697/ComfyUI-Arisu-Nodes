# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add the `ArisuMiniMaxH3HybridToVideo` node (category `Arisu Nodes/MiniMax H3`): MiniMax H3 conditioning with first/last keyframes and image, video, and audio references in one node, with a `frame_picture_tags` widget choosing how the keyframes are numbered for the prompt.
- Add the `ArisuMiniMaxH3HybridToVideoAdvanced` node (category `Arisu Nodes/MiniMax H3`): the hybrid node with `target_width` / `target_height` inputs and a third `positive (upscaled)` output whose keyframes are encoded at the upscaled size, for two-sampler latent-upscale workflows; reference images are sized for each pass, and keyframes or references already at a size are not resampled or encoded again.
- Add the `ArisuMiniMaxH3ContextLatentResize` node (category `Arisu Nodes/MiniMax H3`, beta): resize a saved MiniMax H3 AV latent to a new resolution for the `context_latent` input of motion-context clip chaining, decoding, lanczos-resizing, and re-encoding the video stream with the H3 video VAE while the audio stream and frame count pass through untouched.
- Add the ComfyUI extension entrypoint exposing the node list and the `./web` directory for frontend assets.
- Add project scaffolding: `src` layout, GPL-3.0-only license, README, ruff configuration, and a uv lockfile.
- Add CI workflows for linting and tests on Python 3.10 and 3.13, and publishing to the Comfy registry on tag.
- Add two test lanes: `tests/unit` runs without ComfyUI (and in CI), `tests/comfyui` loads the pack the way ComfyUI does and runs on ComfyUI's interpreter via `scripts/test-comfyui.sh`.
- Add a `Makefile` (`make help`) wrapping install, tidy, lint, test, and build, and run CI through it.
- Add the release flow: `make bump-patch|minor|major`, `make release-commit`, and a CAPTCHA-gated `make tag`, plus the `/release-pr` Claude skill that opens the release PR.
