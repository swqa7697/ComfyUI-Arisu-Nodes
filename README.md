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


## Installation

Requires **ComfyUI >= 0.30.0**, **Python >= 3.10**, Pillow, and PyAV in ComfyUI's environment.
Use the legacy node renderer (**Nodes 2.0 disabled**) for Resource Studio.

### ComfyUI-Manager

Search for **ComfyUI-Arisu-Nodes** in **Manager → Install Custom Nodes**, install it, and restart ComfyUI.

### Manual

Clone the pack into your ComfyUI installation:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/swqa7697/ComfyUI-Arisu-Nodes.git
```

Ensure Pillow and PyAV are available in ComfyUI's Python environment, then restart ComfyUI.
Find the nodes under **Add Node → Arisu Nodes**.

#### Configuration

The pack creates `user/__arisu_nodes/config.arisu.jsonc` on first startup.
Use this file for the pack's server settings. To add external media directories,
edit `roots` with existing absolute paths (`"D:/Photos"` on Windows), then restart ComfyUI:

```jsonc
{
  // Edit these directories manually, then restart ComfyUI.
  "roots": {
    "photos": "/data/photos",
    "references": "/mnt/library/references"
  },
  // Managed by the Agents settings UI; manual editing is not recommended.
  "workbench": {}
}
```

ComfyUI's `input` and `output` directories are available by default.
Choose only media directories you intend to share with clients of this server.
JSONC supports comments; omit trailing commas.

Manage agent models and reasoning effort through
**Settings → Arisu Nodes → Prompt Workbench → Agents**.
These preferences are saved under `workbench` while preserving comments and other settings.
Credentials are stored in Docker authentication volumes. Each invocation uses fresh CLI state;
only credential refreshes are persisted. Update existing images with **Update CLI** when
Workbench reports an incompatible policy.

#### Optional setup

- **MiniMax H3:** use the checkpoint, CLIP, video VAE, and audio VAE required by the stock H3 nodes.
- **Agent generation:** install Docker with Linux container support and give the ComfyUI process access to its daemon.
  Open **Settings → Arisu Nodes → Prompt Workbench → Agents** to build an agent image, sign in,
  and select a model and reasoning effort. Docker Desktop must use Linux containers on macOS/Windows. Provider accounts and settings are shared by users of the ComfyUI instance.
- **Custom prompt skills:** place each skill folder, including its `SKILL.md` and supporting files, at
  `user/__arisu_nodes/skills/<skill-name>/` under ComfyUI's user directory. The pack creates the `skills`
  directory on startup; administrators manage its contents. Select `custom:<skill-name>` in Prompt Workbench.

Prompt generation uses selected skill text, MCP context metadata, and images attached directly
to the agent’s initial prompt. Prepared images use lossless WebP, with crops applied and the
longer edge capped at 4000 pixels without upscaling. Videos supply up to eight evenly spaced
stills across the selected clip; audio is notes only. Asset IDs and attachment order match
each image to its role and current notes. Image/file-reading tools are disabled. Web search, shell execution, edits, delegation, and interactive questions
are disabled. Results arrive through output streams and require Apply; no prompt file is written.
Mixed video requests asking the agent to code, browse, or change files are rejected. Semantic
injection detection remains probabilistic; tool and filesystem restrictions are separate controls.

Optional developer checks run independently of ComfyUI and ordinary CI:

```bash
make test-workbench-docker
make test-workbench-live ARGS="--auth-volume codex=<codex-volume> --auth-volume grok=<grok-volume>"
```

The live lane sends real, billable requests. Supply existing Workbench auth volumes explicitly;
`--agent codex` or `--agent grok` selects one provider, and `--model provider=model-id` overrides
its discovered default. Borrowed volumes can refresh credentials but are never logged out or
deleted. Test images and fixtures are disposable; use a dedicated test account when available.

## Nodes

Click a node name for its full reference, also available through the node's right-click **Help** menu.

| Node | Category | Summary |
|---|---|---|
| [Path Builder](web/docs/ArisuPathBuilder/en.md) | Common | Build a filename prefix from separate text fields. |
| [Extract Last Images](web/docs/ArisuExtractLastImages/en.md) | Common | Keep the last N images from a batch. |
| [Preview & Save Image](web/docs/ArisuPreviewSaveImage/en.md) | Common | Preview images and save them on demand. |
| [Preview & Save Image (Upscale)](web/docs/ArisuPreviewSaveImageUpscale/en.md) | Common | Upscale previewed images when saving. |
| [Load Image (Browse)](web/docs/ArisuLoadImage/en.md) | Common | Browse and crop images from configured directories. |
| [Resize Image](web/docs/ArisuResizeImage/en.md) | Common | Resize images by cropping, padding, fitting, or stretching. |
| [MiniMax H3 Prompt Workbench](web/docs/ArisuMiniMaxH3PromptWorkbench/en.md) | MiniMax H3 | Edit prompts; review agent activity and output in Generation results, or Apply output directly. |
| [MiniMax H3 Resource Studio](web/docs/ArisuMiniMaxH3ResourceStudio/en.md) | MiniMax H3 | Arrange, crop, and trim keyframes and image, video, or audio references. |
| [MiniMax H3 Hybrid to Video](web/docs/ArisuMiniMaxH3HybridToVideo/en.md) | MiniMax H3 | Combine keyframes and media references into H3 conditioning and an AV latent. |
| [MiniMax H3 Hybrid to Video (Advanced)](web/docs/ArisuMiniMaxH3HybridToVideoAdvanced/en.md) | MiniMax H3 | Add upscaled conditioning for two-pass workflows. |
| [MiniMax H3 Video Settings](web/docs/ArisuMiniMaxH3VideoSettings/en.md) | MiniMax H3 | Set canvas size, aspect ratio, and duration in one bundle. |
| [MiniMax H3 Video Settings (Upscale)](web/docs/ArisuMiniMaxH3VideoSettingsUpscale/en.md) | MiniMax H3 | Include a target size for latent upscaling. |

See [example workflows](example_workflows) for ready-made graphs and the [changelog](CHANGELOG.md) for release notes.

## License

[GPL-3.0-only](LICENSE).
