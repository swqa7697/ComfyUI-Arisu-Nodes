# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add Codex project support with shared agent rules, a release PR skill, and a linked ComfyUI environment template.

### Changed

- Preserve Load Image selections when reopening saved workflows or existing tabs, and require Browse reselection after workflow imports, insertion, or node/workflow duplication.

### Security

- Move external image roots to protected `user/__arisu_nodes/config.arisu.jsonc`, support comments, and create an empty template on first startup without overwriting existing files; require manual migration from the old pack-local allowlist.
- Clear imported image selections before previewing and prevent delayed previews or dialog results from restoring stale paths.

## [1.1.1] - 2026-09-10

### Changed

- Select Load Image locations only through Browse in the node UI, preserve hidden selections in workflows, and require reselection when loading legacy wired locations.

### Security

- Contain image loading and browsing within configured roots, preserving external libraries through a local JSON allowlist and requiring reselection of legacy absolute paths.
- Prevent temp-preview and output-path symlink escapes, validate complete save batches before work, and create output files without overwriting existing targets.
- Serve decoded raster previews instead of source files, reject SVG and disguised document formats, and keep internal errors and physical root paths out of HTTP responses.
- Limit save requests to 1 MiB and 256 previews, and keep one save worker active until completion even after client cancellation.

## [1.1.0] - 2026-09-09

### Added

- Add the `ArisuLoadImage` node (category `Arisu Nodes/Common`), **Load Image (Browse)**: load one image from any path on the host, absolute, `~`, or relative to the input directory, with a `browse` button that opens a directory browser (a tree of the home directory and the mounted disks, input and output shortcuts, a list of saved directories kept in the ComfyUI user's settings, thumbnails, an image-name filter) served by two new routes, `/arisu/browse` and `/arisu/view`; the file is read in place, nothing is uploaded or copied, the picked image is shown on the node at its own resolution, the accepted file types match Load Image, and the one output is the `image` batch.
- Add a `crop…` button to **Load Image (Browse)** that opens a crop dialog on the picked image: draw, move and resize a box with the mouse, free or at a preset or custom aspect ratio remembered until another image is picked; the crop is saved with the workflow (a hidden `crop` input), previewed on the node, cut from every frame at run time, and never resized or padded; `/arisu/view` accepts a `crop` parameter.
- Add the `ArisuResizeImage` node (category `Arisu Nodes/Common`), **Resize Image**: resize an image batch to a size by cropping at a chosen anchor, padding with a colour, fitting, or stretching, snapped to a pixel grid, with only `width` and `height` on the node; `resize_method`, `mode`, `pad_color`, `crop_position` and `divisible_by` are edited as drop-downs and fields in a dialog behind a `settings…` button and saved with the workflow; the result is previewed on the node after a run, the outputs are the `image` and a `mask` marking the padding, and the resize runs on the CPU.

### Changed

- Calm the browse dialog: tree rows no longer animate, the image cards rise only on entering a directory, and the tree keeps its scroll position when a folder is expanded.

### Removed

- Remove the experimental `ArisuMiniMaxH3ContextLatentResize` node, **MiniMax H3 Context Latent Resize**, along with its help page.

## [1.0.2] - 2026-09-08

### Changed

- Ship only the runtime files in the Comfy Registry archive, leaving dev tooling and the test suite out of a ComfyUI-Manager install.

## [1.0.1] - 2026-09-08

### Added

- Add the pack icon, shown on the Comfy Registry and in ComfyUI-Manager.

## [1.0.0] - 2026-09-08

### Added

- Add the `ArisuMiniMaxH3HybridToVideo` node (category `Arisu Nodes/MiniMax H3`): MiniMax H3 conditioning with first/last keyframes and image, video, and audio references in one node, with a `frame_picture_tags` widget choosing how the keyframes are numbered for the prompt.
- Add the `ArisuMiniMaxH3HybridToVideoAdvanced` node (category `Arisu Nodes/MiniMax H3`): the hybrid node with `target_width` / `target_height` inputs and a third `positive (upscaled)` output whose keyframes are encoded at the upscaled size, for two-sampler latent-upscale workflows; reference images are sized for each pass, and keyframes or references already at a size are not resampled or encoded again.
- Add the `ArisuMiniMaxH3ContextLatentResize` node (category `Arisu Nodes/MiniMax H3`, beta): resize a saved MiniMax H3 AV latent to a new resolution for the `context_latent` input of motion-context clip chaining, decoding, lanczos-resizing, and re-encoding the video stream with the H3 video VAE while the audio stream and frame count pass through untouched.
- Add the `ArisuMiniMaxH3VideoSettings` and `ArisuMiniMaxH3VideoSettingsUpscale` nodes (category `Arisu Nodes/MiniMax H3`): canvas size from an aspect ratio and a megapixel budget, frame count from a duration in seconds, and for the upscale variant the target size of a latent-upscale pass; with `advertise` switched on (off by default) they drive every hybrid node in the same graph without a link, greying out its size and length widgets immediately and refusing links into them.
- Add the `ArisuPathBuilder` node (category `Arisu Nodes/Common`): join separate text fields into one `/`-separated path for `filename_prefix` inputs, with a `+ field` / `- field` button row that shows up to 16 fields and removes a field's input socket along with the field.
- Add the `ArisuExtractLastImages` node (category `Arisu Nodes/Common`): keep the last N images of a batch, capped at the batch size.
- Add the `ArisuPreviewSaveImage` node (category `Arisu Nodes/Common`): preview an image batch and pass it through unchanged; a run saves nothing, and a `save` button writes the previewed images under ComfyUI's output directory at `path` (Save Image's `filename_prefix` rules) without queueing a run.
- Add the `ArisuPreviewSaveImageUpscale` node (category `Arisu Nodes/Common`): the preview-and-save node with an `upscale_model` combo listing the installed upscale models; the save button upscales the previewed images with the selected model, the way Upscale Image (using Model) does, and `none` saves the original size.
- Add the ComfyUI extension entrypoint exposing the node list and the `./web` directory for frontend assets.
- Add project scaffolding: `src` layout, GPL-3.0-only license, README, ruff configuration, and a uv lockfile.
- Add CI workflows: linting and the unit lane on Python 3.10 and 3.13 for pull requests, the ComfyUI lane weekly against ComfyUI's latest release, and publishing to the Comfy registry on tag.
- Add two test lanes: `tests/unit` runs without ComfyUI, `tests/comfyui` loads the pack the way ComfyUI does and runs on ComfyUI's interpreter via `scripts/test-comfyui.sh`.
- Add a `Makefile` (`make help`) wrapping install, tidy, lint, test, and build, and run CI through it.
- Add `make comfyui-path`, which prints the ComfyUI install root that the ComfyUI lane and the repo's hard boundary resolve to.
- Add the release flow: `make bump-patch|minor|major`, `make release-commit`, and a CAPTCHA-gated `make tag`, plus the `/release-pr` Claude skill that opens the release PR.
