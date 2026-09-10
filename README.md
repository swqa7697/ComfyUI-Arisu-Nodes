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

- **Zero runtime dependencies.** Nothing is downloaded, built, or `pip install`ed on your behalf —
  the pack only uses APIs ComfyUI already ships.
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

### External image directories

**Load Image (Browse)** reads from the built-in `input` and `output` roots. To keep images on
another disk or network share, the machine owner can create `arisu_paths.json` beside this pack's
installed `__init__.py`:

```json
{
  "roots": {
    "photos": "/data/photos",
    "references": "/mnt/library/references"
  }
}
```

Use existing absolute directories (on Windows, for example `"D:/Photos"`). Root IDs begin with a
lowercase letter and contain at most 64 lowercase letters, digits, underscores or hyphens;
`input` and `output` are reserved. Filesystem roots such as `/` or `C:/` are refused.
Restart ComfyUI after editing the file, then select a root in the node or browse dialog.
The `path` value is relative to that root, for example `portraits/a.png` under `photos`.
The file is local configuration: keep a backup across reinstalls and do not commit or distribute it.
A missing configuration enables only built-in roots; invalid configuration disables all external
roots and records the reason in the server log until corrected and ComfyUI restarted.

Configuring a directory permits clients of this ComfyUI server to browse it and load its images.
Choose image-library directories you intend to share. Workflows and browser settings cannot add
roots. Absolute paths, `~`, `..` components, and symlinks leaving the selected root are refused.
Older workflows using absolute paths must reselect their images with **Browse**; old absolute
bookmarks are not imported. Existing relative input paths continue to work.

Previews are decoded raster images; SVG is unsupported. Save buttons accept at most 256 previews
per click, with a 1 MiB request limit. One save runs at a time; retry a busy request after it finishes.

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
| [MiniMax H3 Hybrid to Video](web/docs/ArisuMiniMaxH3HybridToVideo/en.md) | MiniMax H3 | Keyframes and image/video/audio references in one conditioning, plus the AV latent. |
| [MiniMax H3 Hybrid to Video (Advanced)](web/docs/ArisuMiniMaxH3HybridToVideoAdvanced/en.md) | MiniMax H3 | The same, plus a `positive (upscaled)` conditioning for two-sampler latent upscaling. |
| [MiniMax H3 Video Settings](web/docs/ArisuMiniMaxH3VideoSettings/en.md) | MiniMax H3 | Canvas from an aspect ratio and a megapixel budget, length from a duration in seconds. |
| [MiniMax H3 Video Settings (Upscale)](web/docs/ArisuMiniMaxH3VideoSettingsUpscale/en.md) | MiniMax H3 | The same, plus the target size of a latent-upscale pass from an upscale factor. |

Categories are `Arisu Nodes/Common` and `Arisu Nodes/MiniMax H3`.

---

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| ComfyUI | >= 0.30.0 | The release that added MiniMax H3 support. Developed against 0.34.5. |
| MiniMax H3 models | — | For the MiniMax H3 nodes only: the same checkpoint, CLIP, video VAE, and audio VAE the stock H3 nodes need. |
| Python | >= 3.10 | The nodes run on ComfyUI's own interpreter; this is the floor for the dev tooling. |
| [uv](https://docs.astral.sh/uv/) | any | Development only. `make install` installs it if missing. |
| [pnpm](https://pnpm.io/) | any | Development only: runs the JavaScript formatter and linter. `make install` installs it if missing. |
| [Node.js](https://nodejs.org/) | >= 22.15 | Development only: the web test lane. `make install` installs it (via pnpm) if missing. |
| GNU make | any | Development only. |

The pack itself declares no Python dependencies.

---

## Usage

A MiniMax H3 workflow with the pack in it:

1. Drop in **MiniMax H3 Video Settings** and set the aspect ratio, megapixels, and duration; switch
   `advertise` on so the hybrid nodes take them.
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

For VS Code, copy [.vscode/settings.example.jsonc](.vscode/settings.example.jsonc) to
`.vscode/settings.json` and replace `/PATH/TO/ComfyUI` so Pylance can resolve `comfy_api` and torch;
the Biome extension then formats the JavaScript from `biome.json`.

---

## License

[GPL-3.0-only](LICENSE).
