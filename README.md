<p align="center">
  <img src="assets/icon.svg" alt="" width="128" height="128" />
</p>

<h1 align="center">ComfyUI-Arisu-Nodes</h1>

<p align="center">
  <strong>A package of useful ComfyUI nodes optimizing user experience.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ComfyUI-%E2%89%A5%200.30.0-1a1a1a" alt="ComfyUI" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-GPL--3.0--only-blue" alt="License" />
  <img src="https://img.shields.io/badge/API-ComfyUI%20V3-8a63d2" alt="ComfyUI V3 API" />
  <a href="https://github.com/swqa7697/ComfyUI-Arisu-Nodes/actions/workflows/comfyui-lane.yml"><img src="https://github.com/swqa7697/ComfyUI-Arisu-Nodes/actions/workflows/comfyui-lane.yml/badge.svg" alt="ComfyUI lane" /></a>
</p>

---

## Overview

Nodes that take the friction out of building and running ComfyUI workflows: fewer helper nodes to
wire, fewer numbers to keep in sync by hand, fewer runs queued just to save one image. Some are
general-purpose utilities, others belong to a model family — today MiniMax H3, with more to come.

- **Explicit agent setup.** Pillow and PyAV are declared dependencies. Prompt Workbench builds standalone agent images only through explicit settings actions; ordinary node execution never installs tools.
- **In-app help.** Right-click a node and open its help for the full input reference; the same
  pages live under [`web/docs/`](web/docs).
- **No `NODE_CLASS_MAPPINGS`, no monkey-patching.** Pure V3 (`comfy_entrypoint` + `io.Schema`)
  registration; nothing in ComfyUI's own modules is patched at import time.
- **Tested before it ships.** Three test lanes: one loads the pack exactly the way ComfyUI's
  loader does and validates every node schema, another drives the frontend scripts on Node's
  built-in test runner.

---

## Installation

### ComfyUI-Manager / comfy-cli

Once a release is published to the [Comfy Registry](https://registry.comfy.org), search for
**ComfyUI-Arisu-Nodes** in ComfyUI-Manager (**Manager → Install Custom Nodes**), or:

```bash
comfy node registry-install arisu_nodes
```

### Manual (git clone)

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/swqa7697/ComfyUI-Arisu-Nodes.git
```

Restart ComfyUI. There is no requirements step — nothing to install into ComfyUI's environment.

After the restart the nodes appear under **Add Node → Arisu Nodes**. If they do not, check
ComfyUI's console for an import error at startup.

### External image and media directories

**Load Image (Browse)** and **MiniMax H3 Resource Studio** read from the built-in `input` and `output` roots. Studio also reads supported video/audio files from these roots. To keep resources on
another disk or network share, edit `user/__arisu_nodes/config.arisu.jsonc` under ComfyUI.
On its first startup after installation, the pack creates a commented template with empty `roots`;
existing files are never overwritten. A custom ComfyUI user-directory setting relocates this folder.
The protected `__arisu_nodes` system directory is outside the public user-data API.

```jsonc
{
  // Image and media libraries shared with clients of this ComfyUI server.
  "roots": {
    "photos": "/data/photos",
    "references": "/mnt/library/references"
  }
}
```

Use existing absolute directories (on Windows, for example `"D:/Photos"`). Root IDs begin with a
lowercase letter and contain at most 64 lowercase letters, digits, underscores or hyphens;
`input` and `output` are reserved. Filesystem roots such as `/` or `C:/` are refused.
Restart ComfyUI after editing the file, then select a root inside the **Browse** dialog.
The `path` value is relative to that root, for example `portraits/a.png` under `photos`.
The file accepts `//` line comments and `/* ... */` block comments, but no trailing commas.
Ordinary JSON also works. This configuration survives pack reinstalls; keep a backup and do not
commit or distribute it. A missing file becomes an empty template. Creation/read errors, invalid
configuration or symlinked configuration destinations disable external roots and record the reason
in the server log until corrected and ComfyUI restarted.

**Migration:** the old pack-local `arisu_paths.json` is no longer read. After the first startup,
manually copy its `roots` entries into the new template, then restart ComfyUI. No entries are
migrated automatically.

Configuring a directory permits clients of this ComfyUI server to browse it and load its images.
Choose image-library directories you intend to share. Workflows and browser settings cannot add
roots. Absolute paths, `~`, `..` components, and symlinks leaving the selected root are refused.
Older workflows using absolute paths must reselect their images with **Browse**; old absolute
bookmarks are not imported.

**Browse** is the only image-selection control in the node UI. A read-only row above it shows
the selected filename; hover over a shortened name to see it in full. Selection resets are silent. The selected `root` and `path`
are hidden, saved with the workflow, and cannot be typed or wired. Loading a workflow with a
linked `path` or `root` removes those links and clears the selection and crop; use **Browse** to
reselect. Reopening a saved ComfyUI workflow, refreshing it, switching existing tabs, and undo/redo
within a workflow preserve selections. Importing JSON/PNG/API-format workflows, pasting or
duplicating nodes, inserting a workflow, and duplicating a workflow clear the image and crop,
reset the root to `input`, and require reselection—even when imported IDs or filenames match.
Unknown restoration contexts also require reselection. Saved Browse bookmarks remain available.
The browser's path display is read-only; navigate with the tree, **up**, the **input dir** and
**output dir** toolbar shortcuts, saved locations and thumbnails. **+ save** lets you name a saved
directory; use its pencil button to rename it, or **✕** to remove it. Names are optional, and
existing bookmarks remain available.

In **ComfyUI Settings → Arisu Nodes → LoadImage**, **Load Image (Browse): default location** chooses
where Browse starts when no image is selected. Choose `input` (the default), `output`, a
configured root, or a saved bookmark, listed by name; renaming a bookmark keeps the choice. A
selected image keeps its existing location. An unavailable root falls back to `input`, and a
bookmark that was removed or no longer opens resets the choice to `input` with a warning. Direct
API execution keeps its validated root-relative inputs; hiding controls does not grant filesystem
access.

Previews stream the original file, as Load Image's do; only Browse thumbnails are resized. Accepted
types are static PNG, JPEG, WebP, BMP and AVIF images; animated files are not listed. Save buttons accept at most 256 previews
per click, with a 1 MiB request limit. One save runs at a time; retry a busy request after it finishes.
Both Preview & Save nodes interpret their editable or wired `path` as a filename prefix relative
to ComfyUI's output directory: `shots/a` saves beneath `output/shots/`. Absolute paths are refused,
even when they name a location inside output. Configured image roots do not change the save
location. Temporary previews continue to use ComfyUI's temp directory.

---

## Nodes

Every node the pack registers. Its reference page has the inputs, outputs, and edge cases;
ComfyUI serves the same page in-app from a node's right-click **Help**.

| Node | Category | What it does |
|---|---|---|
| [Path Builder](web/docs/ArisuPathBuilder/en.md) | Common | Join separate text fields into one `/`-separated path for `filename_prefix` inputs. |
| [Extract Last Images](web/docs/ArisuExtractLastImages/en.md) | Common | Keep the last N images of a batch, for example a decoded clip's ending frame. |
| [Preview & Save Image](web/docs/ArisuPreviewSaveImage/en.md) | Common | Preview and pass through; save to the output directory on a button click, without a run. |
| [Preview & Save Image (Upscale)](web/docs/ArisuPreviewSaveImageUpscale/en.md) | Common | The same, upscaling the images with the selected model as they are saved. |
| [Load Image (Browse)](web/docs/ArisuLoadImage/en.md) | Common | Browse images in configured directories, including external disks or shares, and optionally crop them; nothing is uploaded. |
| [Resize Image](web/docs/ArisuResizeImage/en.md) | Common | Crop, pad, fit or stretch an image batch to a size on a pixel grid, with the options in a dialog and the result previewed on the node. |
| [MiniMax H3 Prompt Workbench](web/docs/ArisuMiniMaxH3PromptWorkbench/en.md) | MiniMax H3 | Edit prompt text, or prepare selected context for a Docker agent and review its draft before applying. |
| [MiniMax H3 Resource Studio](web/docs/ArisuMiniMaxH3ResourceStudio/en.md) | MiniMax H3 | Browse, crop, trim, mute, and arrange keyframes and mixed references in one resource bundle. |
| [MiniMax H3 Hybrid to Video](web/docs/ArisuMiniMaxH3HybridToVideo/en.md) | MiniMax H3 | Keyframes and image/video/audio references in one conditioning, plus the AV latent; each keyframe's crop, pad or stretch fit in a dialog. |
| [MiniMax H3 Hybrid to Video (Advanced)](web/docs/ArisuMiniMaxH3HybridToVideoAdvanced/en.md) | MiniMax H3 | The same, plus a `positive (upscaled)` conditioning for two-sampler latent upscaling. |
| [MiniMax H3 Video Settings](web/docs/ArisuMiniMaxH3VideoSettings/en.md) | MiniMax H3 | Canvas from an aspect ratio and a megapixel budget, length from a duration in seconds; one `video_settings` bundle for the hybrid nodes. |
| [MiniMax H3 Video Settings (Upscale)](web/docs/ArisuMiniMaxH3VideoSettingsUpscale/en.md) | MiniMax H3 | The same, plus the target size of a latent-upscale pass from an upscale factor, carried in the bundle. |

Categories are `Arisu Nodes/Common` and `Arisu Nodes/MiniMax H3`.

---

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| ComfyUI | >= 0.30.0 | The release that added MiniMax H3 support. Developed against 0.34.5. |
| MiniMax H3 models | — | For conditioning and motion decoding; Prompt Workbench text editing needs no models: the same checkpoint, CLIP, video VAE, and audio VAE the stock H3 nodes need. |
| Python | >= 3.10 | The nodes run on ComfyUI's own interpreter; this is the floor for the dev tooling. |
| [Pillow](https://python-pillow.org/) | any (AVIF needs >= 11.2) | Declared image dependency; AVIF decoding depends on the installed Pillow version. |
| [PyAV](https://pyav.org/) | supplied by ComfyUI | Declared media dependency without an additional version constraint. Uses its bundled codecs; no FFmpeg command-line executable is needed. |
| Docker | Linux containers, x86_64 or aarch64 | Optional: Workbench generation only. Install Docker separately and give the ComfyUI server process access to its local daemon. |
| [uv](https://docs.astral.sh/uv/) | any | Development only. `make install` installs it if missing. |
| [pnpm](https://pnpm.io/) | any | Development only: runs the JavaScript formatter and linter. `make install` installs it if missing. |
| [Node.js](https://nodejs.org/) | >= 22.15 | Development only: the web test lane. `make install` installs it (via pnpm) if missing. |
| GNU make | any | Development only. |

Resource Studio targets the legacy node renderer (Nodes 2.0 disabled), against ComfyUI frontend 1.51.10. Browser compatibility and available encoders depend on the installation.

---

## Usage

**Resource Studio:** select optional first/last keyframes and browse a mixed reference list. Keyframes auto-crop to the effective aspect ratio; click their canvas to select or replace an image and their crop icon to edit it. Click a reference name to open its crop or clip editor, and drag its handle to reorder; a line marks where the card will land. The clip editor is a timeline with a ruler, in/out brackets and a playhead: drag them or use Space, I, O and the arrow keys, lock a duration or pick a preset, and audio opens without a preview. **Browse**, beside the Media references heading, opens at the final reference’s folder in the current list order, or the configured default location for an empty list, highlighting every file already in the list and showing poster stills for videos and waveform tiles for audio. Video rows show a still from the clip start and audio rows a waveform marker. Each row lists its dimensions, or its clip length beside the source length, then video resolution or audio sample rate, and file size. Apply commits edits, while Mute retains them without sending the resource to Hybrid. The node resizes freely; wheel and middle-button drags over the panel zoom and pan the canvas, and a plain wheel over an overflowing reference list scrolls the list. Connect `resources` to either Hybrid variant or enable root-graph advertising. Video Settings can advertise its aspect ratio to Studio too. Taking ownership drops competing wires; releasing ownership restores empty sockets, and Undo can restore the earlier graph.

Studio stores source descriptions. Hybrid decodes originals and performs generation resizing; video selections are sampled at 24 fps and aligned down to H3's frame grid. Playback uses originals when possible and on-demand VP9/Opus proxies otherwise, with one conversion worker, a 2 GiB cache, a ten-minute deadline, and thirty-minute idle expiry. Proxies retain display dimensions and never become generation inputs. Saved workflows retain selections; imports and duplicates require reselection.


### Prompt Workbench

**Finalized prompt** is an editable string output. A normal workflow run returns it unchanged.
**Generate prompt** explicitly prepares the accepted Video Settings and Resource Studio bundles,
then runs Codex or Grok Build in Docker. Review the editable draft and choose **Apply** for one
undoable replacement, or **Discard** to retain your text.

The two-column editor follows the ComfyUI theme and stacks at narrow widths. **Reference notes**
follow active Studio references across reordering; replacing a source does not transfer its notes.
Keyframes have no notes. Prepared inputs reflect applied crops, selected video/audio intervals,
muted references, and each video's audio switch. Advertisers take precedence over explicit wires.

Connect **H3 Motion Context Load Latent** from Motion Context to `context_latent` and a **Load VAE**
node to `vae`. Both connections enable motion controls. Loader index **0** produces `None` for the
first clip, so no VAE is evaluated. Saved contexts use the phase-aligned tail for **5, 22, 39, or 56**
video frames, with at most 12 ordered stills. Audio length **0–240** is descriptive metadata;
**0** means follow video context. Lengths use frames at 24 fps; audio latents are not decoded.
Unsupported latent producers are refused before they can run.

Open **ComfyUI Settings → Arisu Nodes → Prompt Workbench → Agents** to build/update an image, perform
device-code login/logout, choose an account-supported model and low/medium/high effort, inspect
status/logs, or completely remove a provider. The node's **Setup** button opens this same panel.
Enable **Show Agents shortcut** in the same settings section to add an Arisu-icon **Agents**
button to the ComfyUI menu. The shortcut is hidden by default.
Without usable Docker, generation controls are disabled and finalized text remains editable.

Both images use **`python:3.13-slim-trixie`** with **Python 3.13** for the wrapper and MCP server.
Explicit build/update actions run the official Codex and Grok installers in a disposable Docker
build stage; failed validation retains the previous image. Installer dependencies stay out of the
final images. Authentication lives in a separate provider Docker volume and survives updates.
Complete removal asks for destructive-action confirmation and deletes only that installation's
owned provider images, containers, and authentication volume.

Accounts and settings are **shared by trusted users of the ComfyUI instance**. There is no additional
Workbench login or per-user agent session. Agent generation uses the provider's network service and
account usage. Credentials are kept outside workflows. Containers run unprivileged with a read-only
root filesystem and staged-input mounts, limited scratch/resources, and no GPU, Docker socket,
host networking, or ComfyUI installation mount. Codex uses automatic execution review; Grok uses
`permission_mode = "auto"`. An incompatible CLI must be updated before generation.

Two bundled skills write MiniMax H3 prompts from Workbench MCP context: **`bundled:with-ref`**
(default; Ref2VA / Hybrid) and **`bundled:no-ref`** (T2VA / I2VA / FL2VA / L2VA). They share one MCP
(`get_context` + `read_image`): keyframes stay separate from references, video is inspected as ordered
stills, audio is listed with notes only, and Motion Context is on only when `motion.present` is true.
Startup creates an empty `user/__arisu_nodes/skills/` directory if missing and preserves existing
skills. To add a custom skill, place a directory containing `SKILL.md` under the administrator-owned
`user/__arisu_nodes/skills/<name>/`; it appears as `custom:<name>`. Symlinked/escaping skills are not
loaded. Only the selected skill and the job's prepared media are mounted read-only. MCP serves the job
manifest and listed images.

One generation runs at a time, with a ten-minute deadline; builds have a thirty-minute deadline.
Cancellation waits for this job's workers and container to exit and does not interrupt unrelated
queued work. Context changes, node removal, and workflow closure invalidate pending drafts.
Prepared media is cached under ComfyUI temp, bounded to 2 GiB, and expires after 30 idle minutes.

Agent management uses **Codex / Grok Build tabs**, with the remaining space devoted to colored
build and login logs. Click a device-login URL to open it in your browser. During generation,
a running indicator and **Agent activity** button let you inspect provider-exposed analysis,
reference/tool calls, and text results. Both views follow new output automatically; scroll up to
pause, then use **Resume auto-scroll** to return to the latest output.

Only the current operation is kept in memory, until the next operation or server shutdown;
there is no separate log container or history browser. Output is paged without message clipping.
The 16 MiB operation output budget stops excessive output with an error instead of dropping older
lines. This is a readable CLI event view, so content depends on what the provider exposes.
Use **Update CLI** once for existing images to pick up the expanded event renderer.


A MiniMax H3 workflow with the pack in it:

1. Drop in **MiniMax H3 Video Settings** and set the aspect ratio, megapixels, and duration; switch
   `advertise_settings` on so the hybrid nodes take its `video_settings` bundle, or wire that output
   into each hybrid node.
2. Replace the stock conditioning node with **MiniMax H3 Hybrid to Video**. Feed it `clip` and
   `vae` from your H3 loaders, plus `audio_vae` if any audio reference is connected.
3. Connect keyframes (`first_frame` / `last_frame`) and references (`ref_image_*`, `ref_video_*`,
   `ref_audio_*`) in any combination — every one is optional. **Load Image (Browse)** feeds them
   from any folder on the machine, without copying files into `input/`.
4. Send `positive` to the sampler's positive input and `latent` to its latent input.
5. End on **Preview & Save Image** instead of **Save Image**, and click **save** on the results
   worth keeping. **Path Builder** feeds its `path`; **Extract Last Images** grabs the ending frame
   of a decoded clip for a preview or the next clip's keyframe.

Reference order in the prompt is fixed: images, then videos (each soundtrack's `<Audio j>` right
before its `<Video k>`), then standalone audio. Ordinals are 1-based per type.

For a two-sampler latent upscale, use **MiniMax H3 Hybrid to Video (Advanced)** with the
**(Upscale)** settings node: drive sampler 1 with `positive` and `latent`, and give sampler 2's
guider `positive (upscaled)`.

---

## Project structure

```
ComfyUI-Arisu-Nodes/
├── __init__.py                  # the module ComfyUI imports: ComfyExtension + comfy_entrypoint
├── src/arisu_nodes/
│   ├── common/
│   │   ├── core.py              # stdlib-only logic (path join, batch tail, request checks, directory listing)
│   │   ├── nodes.py             # io.ComfyNode classes; needs comfy_api + torch
│   │   └── routes.py            # HTTP routes behind the frontend buttons; registered from on_load
│   ├── minimax_h3/
│   │   ├── core.py              # stdlib-only logic (geometry, frame grids); no torch
│   │   └── nodes.py             # io.ComfyNode classes; needs comfy_api + torch
│   └── anima/                   # reserved
├── web/
│   ├── docs/<node_id>/en.md     # in-app node help pages
│   └── js/<family>/*.js         # frontend scripts: node widgets, buttons, and dialogs
├── tests/
│   ├── unit/                    # ComfyUI-free lane; runs on the project venv alone
│   ├── comfyui/                 # loads the pack like ComfyUI; needs its interpreter
│   ├── web/                     # drives web/js on Node's built-in runner; fakes in web/support/
│   └── support/                 # shared fakes for the ComfyUI lane
├── biome.json                   # JavaScript formatter + linter config (web/js, tests/web)
├── scripts/                     # make target bodies + release CLIs
├── .github/workflows/           # PR gate, weekly ComfyUI lane, registry publish
└── Makefile                     # every dev task; `make help` lists them
```

---

## Development

```bash
git clone https://github.com/swqa7697/ComfyUI-Arisu-Nodes.git
cd ComfyUI-Arisu-Nodes
make install          # creates .venv with the dev group; installs uv, pnpm, and node if missing
make tidy             # format everything in place
make lint test        # what CI checks
make test-comfyui     # the ComfyUI lane, read-only against your install
make build            # wheel + sdist into dist/
```

| Target | Description |
|---|---|
| `make help` | List every target. |
| `make install` | Create `.venv` with the dev group; installs uv, pnpm, and node if missing. `LOCKED=1` adds `--locked`, as CI does. |
| `make uninstall` | Remove `.venv`, caches, and build outputs (keeps `uv.lock`). |
| `make clean` | Remove caches and build outputs (keeps `.venv`). |
| `make tidy` / `make format` | Rewrite in place: ruff format, `ruff check --fix`, uv-sort, beautysh, mbake, Biome. |
| `make lint` | Check only: `ruff check`, `ruff format --check`, `biome ci`. |
| `make test` | The unit lane, then the web lane (`make test-unit test-web`). This is what the PR gate runs. |
| `make test-unit` | The unit lane (`tests/unit`) alone. `ARGS="-k name"` passes flags through. |
| `make test-web` | The web lane (`tests/web`) alone, on Node's built-in runner. `ARGS="--test-name-pattern=name"` passes flags through. |
| `make test-comfyui` | The ComfyUI lane on ComfyUI's interpreter. `ARGS="-v -k name"` passes flags through. |
| `make browser-install` | Install browser tooling and refresh the latest stable ComfyUI frontend in an isolated local environment. |
| `make test-browser` | Run Chromium rendering and interaction scenarios; accepts pytest flags through `ARGS`. |
| `make inspect-browser` | Open the fixture frontend in Chromium for interactive inspection. |
| `make test-count` | Selected test cases per lane, to compare with the budgets in `CLAUDE.md`. |
| `make comfyui-path` | Print the resolved ComfyUI install root the ComfyUI lane uses. |
| `make build` | Build wheel + sdist into `dist/`. |
| `make upgrade` | Re-resolve dependencies at latest and raise the `pyproject.toml` minimums. |
| `make bump-patch\|minor\|major` | Rewrite the version, roll `CHANGELOG.md`, `uv lock`. No git writes. |
| `make release-commit` | On a release branch: commit and push the bump. `YES=1` skips the prompt. |
| `make tag` | On the latest `main`: CAPTCHA-gated annotated tag `vX.Y.Z`, pushed. |

The unit lane needs nothing but the project venv; the web lane needs only Node (no `package.json`,
no `node_modules`); the ComfyUI lane runs on ComfyUI's own interpreter and **writes nothing** into
that install, reading `COMFYUI_PATH` (default `~/apps/comfyui`). [CLAUDE.md](CLAUDE.md) has the
rest: the `core.py` / `nodes.py` split every node follows, the rules that keep the test suite
small, the steps for adding a node, and the release flow. Release history is in
[CHANGELOG.md](CHANGELOG.md).


### Local browser inspection

```bash
make browser-install
make test-browser                       # or ARGS="-k resource_studio"
make inspect-browser                    # requires a graphical desktop
```

All browser tooling and generated files stay beneath `.tmp/browser/` (environments, binaries,
results, logs, and scratch checks).

This optional lane loads the **latest stable ComfyUI frontend**, the real extension scripts,
and synthetic API/media fixtures. `browser-install` refreshes the frontend on each invocation;
tests use that installed version without downloading updates. The frontend lives outside
`uv.lock` in `.tmp/browser/env/`; Chromium lives in `.tmp/browser/binaries/`. Ordinary
`make install` and `make test` do not install or run browser tooling. Linux needs Chromium's
system libraries; if launch reports missing libraries, install the named packages with your
system package manager, then rerun setup. Setup does not install operating-system packages.

Resource Studio and Prompt Workbench each have one browser journey covering 1440×900 and
1024×768, using the default appearance and legacy node renderer (Nodes 2.0 disabled). Tests
exercise selection, crop/clip editing, scrolling/resizing, canvas navigation, simulated prompt
generation, review/Apply, and unavailable-agent states. They assert behavior and layout bounds,
not pixel baselines. A frontend update that breaks these contracts fails visibly; no downgrade
or renderer fallback occurs.

Screenshots, Playwright traces, and diagnostics appear in `.tmp/browser/results/<scenario>/`, with
frontend/browser versions, viewport, API requests, and errors. Files in that scenario directory
are replaced on rerun. Inspect the PNGs to evaluate appearance; a green test alone is not a
usability review. Frontend 1.52.7 emits a known `ComfyApp graph accessed before initialization`
console diagnostic from its own setting store; that exact message/source is recorded separately.
Other console errors, JavaScript exceptions, unexpected routes, and external connections fail.

`inspect-browser` opens Studio; use ComfyUI's node search to add Prompt Workbench. Reload after
editing extension scripts. All settings and API actions stay in the fixture server's memory;
no live ComfyUI service, model, GPU, Docker daemon, or agent account is used. Closing the browser
or pressing Ctrl+C stops the server. Browser dependencies, media, and diagnostics are development
only and excluded from Registry publishing.

Node-definition fixtures are checked against `GET_NODE_INFO_V1()` in the existing ComfyUI pack
regression (`make test-comfyui ARGS="-k test_pack_loads_like_comfyui"`). When a covered schema
changes, update its fixture alongside it, retaining the portable `custom_nodes.arisu` module name.

For an agent-driven UI improvement loop, invoke `$ui-optimize` in Codex or `/ui-optimize` in
Claude Code. The [shared skill](.claude/skills/ui-optimize/SKILL.md) compares real browser
screenshots, makes focused UI changes, and reruns interaction checks. Before/after images stay
under `.tmp/browser/reviews/<task>/` so scenario reruns do not overwrite the baseline.

### Optional Docker smoke check

From this development checkout, after `make install` and with Docker available:

```bash
uv run --no-sync python scripts/smoke-workbench.py
```

This builds both official standalone agents with temporary fixtures and fresh authentication volumes.
It verifies Auto capability, native skill discovery, MCP initialization/context/image access and
unlisted-image refusal, unprivileged read-only mounts, and readable current-session logs, then removes its
owned containers, images, volumes, and fixtures. It does not use an existing account or modify ComfyUI.

Device login, account model discovery, and real prompt generation need the provider's configured
account. After the ComfyUI lane passes, the owner can test those in the browser with a first clip
and a saved motion context, then review Apply/Discard and cancellation using their own VAE/GPU.

### Claude Code and Codex

Open this checkout in either agent. Claude Code reads [CLAUDE.md](CLAUDE.md);
Codex reads [AGENTS.md](AGENTS.md), which links to the same project rules.
Both use the same Make targets and ComfyUI safety boundaries.

For local ComfyUI checks, copy [.claude/comfyui-env.example.md](.claude/comfyui-env.example.md)
to `.claude/comfyui-env.md` and fill in your machine facts. This ignored file is shared
by both agents. Keep the checkout outside the live ComfyUI install; agent work must
never modify that install or restart its service. Environments without ComfyUI can
run `make install`, `make tidy`, `make lint test`, and `make build` in this checkout.

After pushing a release branch through the documented release flow, invoke
`/release-pr` in Claude Code or `$release-pr` in Codex to open its release PR.
The skill requires `git` and authenticated GitHub CLI (`gh`). Codex discovers it
through `.agents/skills/release-pr`, a symlink to the shared Claude skill; use
`/skills` to find it, or restart Codex if it has not appeared. See the
[official Codex skill documentation](https://learn.chatgpt.com/docs/build-skills)
for discovery and invocation details. No project-specific Codex configuration is
required; personal `.codex/` settings stay ignored. Agent files are excluded from
Registry publishing.

For VS Code, copy [.vscode/settings.example.jsonc](.vscode/settings.example.jsonc) to
`.vscode/settings.json` and replace `/PATH/TO/ComfyUI` so Pylance can resolve `comfy_api` and torch;
the Biome extension then formats the JavaScript from `biome.json`.

---

## License

[GPL-3.0-only](LICENSE).
