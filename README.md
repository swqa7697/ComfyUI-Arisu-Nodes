<h1 align="center">ComfyUI-Arisu-Nodes</h1>

<p align="center">
  <strong>ComfyUI nodes that put back together what the stock nodes split apart.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ComfyUI-%E2%89%A5%200.30.0-1a1a1a" alt="ComfyUI" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-GPL--3.0--only-blue" alt="License" />
  <img src="https://img.shields.io/badge/API-ComfyUI%20V3-8a63d2" alt="ComfyUI V3 API" />
</p>

---

## Overview

A small, dependency-free node pack built on ComfyUI's V3 node API. Each node fills a gap where
ComfyUI's stock nodes force you to choose between two features that the underlying model already
supports together.

- **Zero runtime dependencies.** Nothing is downloaded, built, or `pip install`ed on your behalf —
  the pack only uses APIs ComfyUI already ships.
- **In-app help.** Right-click any node and pick **🛟 Node Help** for its full reference page.
- **No `NODE_CLASS_MAPPINGS`, no monkey-patching.** Pure V3 (`comfy_entrypoint` + `io.Schema`)
  registration; nothing in ComfyUI's own modules is patched at import time.
- **Tested before it ships.** Two test lanes, one of which loads the pack exactly the way
  ComfyUI's loader does and validates every node schema.

---

## Nodes

### MiniMax H3 Hybrid to Video

`ArisuMiniMaxH3HybridToVideo` — category **Arisu Nodes/MiniMax H3** ·
[full reference](web/docs/ArisuMiniMaxH3HybridToVideo/en.md)

First/last keyframes **and** image/video/audio references in one conditioning. ComfyUI's stock
**MiniMax H3 Image to Video** and **MiniMax H3 Reference to Video** each build their own AV latent
and set only their own conditioning key, so they cannot be chained. The H3 model already packs
keyframes and references together, so this node sets both keys on one conditioning and returns one
latent.

| Input | Notes |
|---|---|
| `clip`, `vae` | The H3 text encoder (Qwen3-VL) and video VAE. |
| `audio_vae` | Optional; required only when an audio input is connected. |
| `prompt` | Refer to references with the usual `<Picture i>` / `<Video k>` / `<Audio j>` tags. |
| `width`, `height` | Canvas in pixels, multiples of 32 (default 1344 × 768). |
| `length` | Frames at 24 fps, snapped up to the model's 17k+5 grid (default 124 ≈ 5 s). |
| `ref_image_size` | `match` scales references to the generation's pixel area; `max` caps the short edge at 2048 px for identity fidelity, at a real speed cost. |
| `frame_picture_tags` | Whether keyframes take `<Picture>` ordinals `after_refs` (default), `before_refs`, or `none`. |
| `first_frame`, `last_frame` | Optional keyframes pinned at frame 0 and the last frame. |
| `ref_image_1..9` | Reference images, `<Picture i>`. |
| `ref_video_1..3` | Reference clips as 24 fps frame batches, `<Video k>`. |
| `ref_video_audio_1..3` | Soundtrack of the same-numbered reference video. |
| `ref_audio_1..3` | Standalone reference audio, `<Audio j>`. |

Outputs `positive` (CONDITIONING) and `latent` (LATENT). Chain **Add Guide for MiniMax H3** after it
to anchor more frames, and pair the model with **ModelSamplingMiniMaxH3** as you would with the
stock nodes.

---

### MiniMax H3 Hybrid to Video (Advanced)

`ArisuMiniMaxH3HybridToVideoAdvanced` — category **Arisu Nodes/MiniMax H3** ·
[full reference](web/docs/ArisuMiniMaxH3HybridToVideoAdvanced/en.md)

The hybrid node for two-sampler latent-upscale workflows. In `sampler 1 → latent upscaler →
sampler 2`, the first-pass keyframe latents are on the wrong grid for sampler 2, which fails with
`shape mismatch: value tensor of shape [N, 96] cannot be broadcast to indexing result of shape [M, 96]`.
This node re-encodes the original pixel keyframes at the upscaled size, so the second pass gets
sharp anchors instead of resampled latents.

| Input | Notes |
|---|---|
| everything above | Same inputs and behaviour as **MiniMax H3 Hybrid to Video**. |
| `target_width`, `target_height` | Size of the upscaled video, multiples of 32 (default 2688 × 1536). Must equal the latent upscaler's output. |

Outputs `positive` and `latent` exactly like the hybrid node, plus `positive (upscaled)` for the
second guider. Keyframes and reference images are sized for each pass (`ref_image_size = match`
uses that pass's pixel area) and are resized or encoded again only when the size differs; when the
target equals the generation size the two conditionings are the same object.

---

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| ComfyUI | >= 0.30.0 | The release that added MiniMax H3 support. Developed against 0.34.5. |
| MiniMax H3 models | — | Same checkpoint, CLIP, video VAE, and audio VAE the stock H3 nodes need. |
| Python | >= 3.10 | The nodes run on ComfyUI's own interpreter; this is the floor for the dev tooling. |
| [uv](https://docs.astral.sh/uv/) | any | Development only. `make install` installs it if missing. |
| GNU make | any | Development only. |

The pack itself declares no Python dependencies.

---

## Installation

### Manual (git clone)

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/swqa7697/ComfyUI-Arisu-Nodes.git
```

Restart ComfyUI. There is no requirements step — nothing to install into ComfyUI's environment.

### ComfyUI-Manager / comfy-cli

Once a release is published to the [Comfy Registry](https://registry.comfy.org), search for
**ComfyUI-Arisu-Nodes** in ComfyUI-Manager (**Manager → Install Custom Nodes**), or:

```bash
comfy node registry-install arisu_nodes
```

### Verify

After the restart, the nodes appear under **Add Node → Arisu Nodes**. If they do not, check
ComfyUI's console for an import error at startup.

---

## Usage

The hybrid node is a drop-in replacement for the stock conditioning node in ComfyUI's MiniMax H3
workflow: delete **MiniMax H3 Image to Video** or **MiniMax H3 Reference to Video**, drop in
**MiniMax H3 Hybrid to Video**, and reconnect.

1. Feed it `clip` and `vae` from your H3 loaders, plus `audio_vae` if you use any audio reference.
2. Connect keyframes (`first_frame` / `last_frame`) and references (`ref_image_*`, `ref_video_*`,
   `ref_audio_*`) in any combination — every one is optional.
3. Send `positive` to the sampler's positive input and `latent` to its latent input.

Reference order in the prompt is fixed: images, then videos (each soundtrack's `<Audio j>` right
before its `<Video k>`), then standalone audio. Ordinals are 1-based per type.

For a two-sampler latent upscale, use **MiniMax H3 Hybrid to Video (Advanced)** instead: set
`target_width` / `target_height` to the upscaler's output size, drive sampler 1 with `positive` and
`latent`, and give sampler 2's guider `positive (upscaled)`.

---

## Project structure

```
ComfyUI-Arisu-Nodes/
├── __init__.py                  # the module ComfyUI imports: ComfyExtension + comfy_entrypoint
├── src/arisu_nodes/
│   ├── minimax_h3/
│   │   ├── core.py              # stdlib-only logic (geometry, frame grids); no torch
│   │   └── nodes.py             # io.ComfyNode classes; needs comfy_api + torch
│   ├── common/                  # reserved
│   └── anima/                   # reserved
├── web/
│   ├── docs/<node_id>/en.md     # in-app node help pages
│   └── js/<family>/             # frontend assets
├── tests/
│   ├── unit/                    # ComfyUI-free lane; what CI runs
│   └── comfyui/                 # loads the pack like ComfyUI; needs its interpreter
├── scripts/                     # make target bodies + release CLIs
└── Makefile                     # every dev task; `make help` lists them
```

---

## Development

```bash
git clone https://github.com/swqa7697/ComfyUI-Arisu-Nodes.git
cd ComfyUI-Arisu-Nodes
make install          # creates .venv with the dev group
make tidy             # format everything in place
make lint test        # what CI checks
make test-comfyui     # the ComfyUI lane, read-only against your install
make build            # wheel + sdist into dist/
```

### Make targets

| Target | Description |
|---|---|
| `make help` | List every target. |
| `make install` | Create `.venv` with the dev group. `LOCKED=1` adds `--locked`, as CI does. |
| `make uninstall` | Remove `.venv`, caches, and build outputs (keeps `uv.lock`). |
| `make clean` | Remove caches and build outputs (keeps `.venv`). |
| `make tidy` / `make format` | Rewrite in place: ruff format, `ruff check --fix`, uv-sort, beautysh, mbake. |
| `make lint` | Check only: `ruff check` + `ruff format --check`. |
| `make test` | The unit lane (`tests/unit`). This is what CI runs. |
| `make test-comfyui` | The ComfyUI lane on ComfyUI's interpreter. `ARGS="-v -k name"` passes flags through. |
| `make build` | Build wheel + sdist into `dist/`. |
| `make upgrade` | Re-resolve dependencies at latest and raise the `pyproject.toml` minimums. |
| `make bump-patch\|minor\|major` | Rewrite the version, roll `CHANGELOG.md`, `uv lock`. No git writes. |
| `make release-commit` | On a release branch: commit and push the bump. `YES=1` skips the prompt. |
| `make tag` | On the latest `main`: CAPTCHA-gated annotated tag `vX.Y.Z`, pushed. |

### Test lanes

Two pytest lanes, both configured in `pyproject.toml`:

- **`tests/unit/`** needs nothing but the project venv. `make test` runs it; a bare `uv run pytest`
  deselects the other lane via `addopts`.
- **`tests/comfyui/`** imports the pack the way ComfyUI's loader does and exercises `GET_SCHEMA()`,
  so it needs ComfyUI's interpreter and source tree. `make test-comfyui` wraps
  `scripts/test-comfyui.sh`, which reads `COMFYUI_PATH` (default `~/apps/comfyui`), layers an
  ephemeral pytest on that install's Python, and **writes nothing** into it.

Anything that does not need a tensor belongs in `core.py` with a unit test; anything importing
`comfy_api` or torch belongs in `nodes.py` with a test in the ComfyUI lane.

### Adding a node

1. Pure logic in `src/arisu_nodes/<family>/core.py`, with tests in `tests/unit/<family>/`.
2. The `io.ComfyNode` class in `nodes.py`, registered in that family's `NODES` list.
3. A help page at `web/docs/<node_id>/en.md`.
4. The new id appended to `EXPECTED_NODE_IDS` in `tests/comfyui/test_pack.py`.
5. A `CHANGELOG.md` entry under `[Unreleased]` if it is user-visible.

### VS Code

Copy [.vscode/settings.example.jsonc](.vscode/settings.example.jsonc) to `.vscode/settings.json`
and replace `/PATH/TO/ComfyUI` so Pylance can resolve `comfy_api` and torch.

---

## Releasing

```bash
git switch -c release/0.2.0    # from an up-to-date main
make bump-minor                # version + CHANGELOG + uv.lock; no git writes
make release-commit            # guarded commit and push
# open the main <- release/0.2.0 PR and merge it
git switch main && git pull
make tag                       # CAPTCHA-gated v0.2.0 -> publishes to the registry
```

Each step refuses to run out of order: `make bump-*` needs a non-empty `[Unreleased]` section,
`make release-commit` refuses on `main` or with unrelated files staged, and `make tag` refuses
unless you are on the latest `main` with an untagged HEAD. Pushing the tag triggers
[`publish_node.yml`](.github/workflows/publish_node.yml), which needs a `REGISTRY_ACCESS_TOKEN`
repository secret.

See [CHANGELOG.md](CHANGELOG.md) for release history.

---

## Troubleshooting

<details>
<summary>The nodes do not appear after restarting ComfyUI</summary>

Check ComfyUI's startup console for an import error from `ComfyUI-Arisu-Nodes`. The most common
causes are a ComfyUI older than 0.30.0 (no MiniMax H3, and an older V3 API) and a clone placed
somewhere other than `ComfyUI/custom_nodes/`. Do not symlink a working copy into `custom_nodes/` —
clone it.
</details>

<details>
<summary><code>encoding reference audio needs the audio_vae input</code></summary>

A `ref_audio_*` or `ref_video_audio_*` input is connected but `audio_vae` is not. Connect the H3
audio VAE, or disconnect the audio reference.
</details>

<details>
<summary><code>MiniMax H3 reference videos need at least 5 frames</code></summary>

Reference clips are cropped to the target duration and then down to the 17k+5 frame grid, which
needs at least 5 frames (~0.2 s at 24 fps). Feed a longer clip.
</details>

<details>
<summary>Generation got much slower after adding reference images</summary>

Reference tokens ride through every sampling step. `ref_image_size = max` encodes each reference at
up to a 2048 px short edge, which can be several times slower than `match`. Use `max` only when you
need the identity fidelity.
</details>

<details>
<summary><code>make test-comfyui</code> says there is no interpreter</summary>

The script looks for `$COMFYUI_PATH/.venv/bin/python`, defaulting to `~/apps/comfyui`. Point it at
your install: `make test-comfyui COMFYUI_PATH=/path/to/ComfyUI`.
</details>

<details>
<summary>Prompt tags refer to the wrong image</summary>

The text encoder numbers `<Picture N>` items in the order it sees them. `frame_picture_tags`
decides whether the keyframes come before or after the reference images, or stay invisible to the
prompt — see the [node reference](web/docs/ArisuMiniMaxH3HybridToVideo/en.md#frame_picture_tags).
</details>

---

## Contributing

Branch off `dev`, make the change, then run `make tidy && make lint test` — CI runs `make tidy` and
fails on any diff, so formatting must be committed. Open a PR against `main`. Commits follow
[Conventional Commits](https://www.conventionalcommits.org/) (`feat(nodes): ...`, scopes: `nodes`,
`core`, `tests`, `ci`, `docs`, `web`). Project conventions live in [CLAUDE.md](CLAUDE.md).

## License

[GPL-3.0-only](LICENSE).
