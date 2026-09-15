# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add an optional Agents menu shortcut to open shared agent management, hidden by default.
- Create the custom `user/__arisu_nodes/skills/` directory on startup when missing.
- Add MiniMax H3 Prompt Workbench with editable finalized text, selected resource and motion-context preparation, Docker-isolated Codex/Grok agents, shared settings, and draft review before Apply.
- Add MiniMax H3 Resource Studio with keyframe cropping, mixed references, clip editing, and original-source Hybrid processing.
- Add aspect-ratio outputs to both MiniMax H3 Video Settings nodes.
- Add a `video_settings` bundle output to both MiniMax H3 Video Settings nodes and an optional `video_settings` input to both Hybrid to Video nodes; a wired bundle overrides width, height and length (and the target size from the Upscale variant) and greys those widgets as advertising does.
- Add inline names and renaming for saved Load Image browse paths.
- Add a ComfyUI setting for the default Load Image browse location when no image is selected: a root or a saved path by name, reset to `input` with a warning when a chosen saved path is gone.
- Add a keyframes settings dialog to both MiniMax H3 Hybrid to Video nodes: resize method, crop, pad or stretch, pad colour and crop position in a first frame and a last frame section, on the model's 32-pixel canvas grid.

### Changed

- Prioritize Prompt Workbench writing fields, align its controls with Resource Studio, and refine focus, reference rows, and crop, clip, review, and agent dialogs.

- Refresh the Arisu icon and add a light variant for the Agents shortcut.
- Remove custom light-mode color overrides from Prompt Workbench, Resource Studio, and the clip editor, keeping functional colors consistent while inheriting ComfyUI styling.
- Replace Resource Studio replace buttons with keyframe canvas selection, and open Browse references at the final reference’s folder in list order.
- Move Resource Studio’s Browse beside the Media references heading, hide zero counters, and show clip-start stills for video references and a waveform marker for audio.
- Stack Resource Studio keyframes in a left column beside the media reference list, with taller reference rows and larger thumbnails.
- Show dimensions or clip and source lengths, video resolution or audio sample rate, and file size on Resource Studio reference rows, reloading them after a workflow opens.
- Limit Resource Studio clip times to one decimal, removing the clip editor's free-precision snapping.
- Remove the Resource Studio height cap so the node grows freely, and pass wheel zoom and middle-button canvas drags through its panel, scrolling an overflowing reference list instead.
- Coordinate MiniMax H3 settings and resource advertising across queueing and API exports, rejecting missing sources and conflicting resource inputs.
- Inject advertised MiniMax H3 settings into the hybrid nodes' `video_settings` input as one link instead of one per widget; API-format exports carry that link, and a muted or missing wired settings node rejects the prompt.
- Place the `video_settings` bundle at output 0 of both MiniMax H3 Video Settings nodes, moving every other output down one slot; saved wires into those outputs need re-wiring, and the example workflow is updated.
- Move the Load Image input and output directory shortcuts beside up in the browse toolbar to free sidebar space.
- Rename the MiniMax H3 Video Settings `advertise` switch to `advertise_settings` and the Resource Studio switch to `advertise_resources`; saved workflows keep the flag by position, API-format exports must use the new key.
- Auto-crop Resource Studio keyframes from a wired aspect ratio when the upstream Video Settings selector is readable, and drop the auto-crop notification.
- Remove the custom aspect ratio from crop dialogs: a saved crop that matches no preset opens as Free and constrains nothing, and `21:9` joins the presets.
- Highlight every reference already in the list when browsing Resource Studio references, and show poster stills for videos and waveform tiles for audio in mixed Browse, outlined in their kind colour.
- Show a loading indicator on Browse tiles until their thumbnail or poster arrives, keep loaded tiles while filtering, and queue media requests behind the busy workers instead of refusing them.
- Center-crop the first keyframe of the MiniMax H3 Hybrid nodes to the canvas by default instead of stretching it; API-format exports must supply the eight `first_frame_*` / `last_frame_*` keys.
- Enlarge Resource Studio icon buttons and reference-row text, and colour each mute button in its resource kind.
- Show an insertion line while dragging a Resource Studio reference and drop it above or below the row under the pointer.
- Rebuild the Resource Studio clip editor as a timeline with a ruler, draggable in/out brackets and playhead, a keyboard-driven transport row, a duration lock with presets, and a compact preview-free audio dialog.

### Fixed

- Keep the Agents toolbar shortcut visible after refresh and place it before the Manager section.

- Keep ComfyUI Settings open while interacting with Prompt Workbench agent management and removal confirmation.
- Place Prompt Workbench agent settings under the existing Arisu Nodes settings tab.
- Preserve MiniMax H3 Hybrid to Video dimensions when reopening workflows with resource advertising, and fit height without changing width when resource ownership changes.
- Persist each image’s applied crop ratio across Load Image and Resource Studio workflow reloads, including Free, and discard draft ratio changes on cancellation without inferring from crop dimensions.
- Fix Resource Studio keyframe and reference creation in browsers without `crypto.randomUUID`, including HTTP connections.
- Restore each Arisu node's saved dimensions when reopening a workflow, including manually minimized nodes.

## [1.1.2] - 2026-09-11

### Added

- Show the selected Load Image filename above Browse, with the full name available on hover.
- Add Codex project support with shared agent rules, a release PR skill, and a linked ComfyUI environment template.

### Changed

- Accept only PNG, JPEG, WebP, BMP and AVIF in Load Image (Browse); TIFF, GIF, SVG and other types are no longer listed or loaded.
- Render cropped Load Image previews as full-size WebP; Browse thumbnails remain the only resized previews.
- Handle static images only in Load Image (Browse): Browse no longer lists animated PNG, WebP or AVIF files, and the output is always one image.
- Show the browse dialog's current path as read-only text; navigate with the tree, up, roots, saved locations and thumbnails.
- Clear Load Image selections silently, including when removing legacy location wires.
- Preserve Load Image selections when reopening saved workflows or existing tabs, and require Browse reselection after workflow imports, insertion, or node/workflow duplication.

### Fixed

- Speed up Load Image (Browse) previews and the crop dialog by streaming the original file, as Load Image does, instead of re-encoding it as PNG.

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
