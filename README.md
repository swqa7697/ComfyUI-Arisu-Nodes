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

---

## Nodes

### MiniMax H3 Hybrid to Video

`ArisuMiniMaxH3HybridToVideo` · [reference](web/docs/ArisuMiniMaxH3HybridToVideo/en.md)

First/last keyframes **and** image, video, and audio references in one conditioning. ComfyUI's
stock **MiniMax H3 Image to Video** and **MiniMax H3 Reference to Video** each build their own AV
latent and set only their own conditioning key, so they cannot be chained — you pick one or the
other. The H3 model already packs keyframes and references together, so this node sets both keys on
one conditioning and returns one latent. Every keyframe and reference input is optional: connect
what the shot needs and refer to it in the prompt with the usual `<Picture i>` / `<Video k>` /
`<Audio j>` tags.

It is a drop-in replacement for either stock node — delete it, drop this one in, reconnect. The
**(Advanced)** variant adds `target_width` / `target_height` and a third `positive (upscaled)`
output for two-sampler latent upscaling, where it re-encodes the original pixel keyframes at the
upscaled size instead of handing the second sampler resampled first-pass latents.

### MiniMax H3 Video Settings

`ArisuMiniMaxH3VideoSettings` · [reference](web/docs/ArisuMiniMaxH3VideoSettings/en.md)

One place for the canvas and the clip length, so the numbers stop being retyped into every node. An
aspect ratio and a megapixel budget give `width` and `height` on H3's 32-pixel grid; a duration in
seconds gives `length` on its 17k+5 frame grid. The **(Upscale)** variant adds `upscale_factor` and
derives the target size for an upscale pass.

Wire the outputs wherever you want them, or switch on `advertise`: every MiniMax H3 hybrid node in
the root graph then takes the values without a link, and their size and length widgets grey out at
once. Advertising is off by default and only one settings node per graph holds the slot; inside a
subgraph, wire the outputs explicitly.

### Preview & Save Image

`ArisuPreviewSaveImage` · [reference](web/docs/ArisuPreviewSaveImage/en.md)

Preview an image batch, pass it through unchanged, and save it only when you click **save**. A run
writes nothing but the preview, the way **Preview Image** does; the button posts the preview to a
route the pack registers on ComfyUI's server, which writes the images under the output directory at
`path`. Nothing is queued, so keeping a good result costs no second run and the results you do not
want never reach `output/`. The **(Upscale)** variant runs the selected upscale model inside that
save, so the upscale happens once, on the images worth keeping.

`path` follows **Save Image**'s `filename_prefix` rules and can be fed from **Path Builder**; saved
files get a counter suffix, so a second click never overwrites the first.

### Load Image (Browse)

`ArisuLoadImage` · [reference](web/docs/ArisuLoadImage/en.md)

Load one image from any path on the machine running ComfyUI. **Load Image** lists only the top level
of `input/`, and the one way to use another file is an upload that copies it there. This node holds a
path instead, and its **browse** button opens a directory browser with a tree of your home directory
and mounted disks, thumbnails, and an image-name filter: start in `input/`, walk anywhere the ComfyUI
process can read, click an image, and the node shows it at its real size. The **crop…** button opens
a crop dialog on it: drag a box, move it, resize it by its handles, freeform or at an aspect ratio;
the crop is kept with the workflow, shown in the preview, and never resized or padded.
The file is read in place at run time; nothing is uploaded or copied. Same file types and `image`
output as **Load Image**; there is no `mask` output.

### All nodes

| Node | Category | What it does |
|---|---|---|
| [MiniMax H3 Hybrid to Video](web/docs/ArisuMiniMaxH3HybridToVideo/en.md) | MiniMax H3 | Keyframes and image/video/audio references in one conditioning, plus the AV latent. |
| [MiniMax H3 Hybrid to Video (Advanced)](web/docs/ArisuMiniMaxH3HybridToVideoAdvanced/en.md) | MiniMax H3 | The same, plus a `positive (upscaled)` conditioning for two-sampler latent upscaling. |
| [MiniMax H3 Context Latent Resize](web/docs/ArisuMiniMaxH3ContextLatentResize/en.md) *(experimental)* | MiniMax H3 | Resize a saved H3 AV latent so a motion-context clip chain can change resolution at a join. |
| [MiniMax H3 Video Settings](web/docs/ArisuMiniMaxH3VideoSettings/en.md) | MiniMax H3 | Canvas from an aspect ratio and a megapixel budget, length from a duration in seconds. |
| [MiniMax H3 Video Settings (Upscale)](web/docs/ArisuMiniMaxH3VideoSettingsUpscale/en.md) | MiniMax H3 | The same, plus the target size of a latent-upscale pass from an upscale factor. |
| [Path Builder](web/docs/ArisuPathBuilder/en.md) | Common | Join separate text fields into one `/`-separated path for `filename_prefix` inputs. |
| [Extract Last Images](web/docs/ArisuExtractLastImages/en.md) | Common | Keep the last N images of a batch, for example a decoded clip's ending frame. |
| [Preview & Save Image](web/docs/ArisuPreviewSaveImage/en.md) | Common | Preview and pass through; save to the output directory on a button click, without a run. |
| [Preview & Save Image (Upscale)](web/docs/ArisuPreviewSaveImageUpscale/en.md) | Common | The same, upscaling the images with the selected model as they are saved. |
| [Load Image (Browse)](web/docs/ArisuLoadImage/en.md) | Common | Load one image from any host path, picked in a directory browser with thumbnails and cropped in a dialog if you like; nothing is uploaded. |

Categories are `Arisu Nodes/MiniMax H3` and `Arisu Nodes/Common`. Every node's inputs, outputs, and
edge cases are documented on its reference page, which ComfyUI also serves in-app.

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
│   ├── minimax_h3/
│   │   ├── core.py              # stdlib-only logic (geometry, frame grids); no torch
│   │   └── nodes.py             # io.ComfyNode classes; needs comfy_api + torch
│   ├── common/
│   │   ├── core.py              # stdlib-only logic (path join, batch tail, request checks, directory listing)
│   │   ├── nodes.py             # Path Builder, Extract Last Images, Preview & Save Image, Load Image (Browse)
│   │   └── routes.py            # the save button's and the browse dialog's HTTP routes; registered from on_load
│   └── anima/                   # reserved
├── web/
│   ├── docs/<node_id>/en.md     # in-app node help pages
│   └── js/<family>/*.js         # frontend scripts (Path Builder, save and browse buttons, settings advertising)
├── tests/
│   ├── unit/                    # ComfyUI-free lane; what the PR gate runs
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
that install, reading `COMFYUI_PATH` (default `~/apps/comfyui`). [CLAUDE.md](CLAUDE.md) has the rest: the `core.py` / `nodes.py` split every node
follows, the rules that keep the test suite small, the steps for adding a node, and the release
flow. Release history is in [CHANGELOG.md](CHANGELOG.md).

For VS Code, copy [.vscode/settings.example.jsonc](.vscode/settings.example.jsonc) to
`.vscode/settings.json` and replace `/PATH/TO/ComfyUI` so Pylance can resolve `comfy_api` and torch;
the Biome extension then formats the JavaScript from `biome.json`.

---

## License

[GPL-3.0-only](LICENSE).
