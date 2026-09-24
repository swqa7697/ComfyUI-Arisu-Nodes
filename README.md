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
Recommend to use with Nodes 2.0 option **disabled**.

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

#### Optional setup

- **Agent generation:** install Docker with Linux container support and give the ComfyUI process access to its daemon.
  Open **Settings → Arisu Nodes → Prompt Workbench → Agents** to build an agent image, sign in,
  and select a model and reasoning effort. Docker Desktop must use Linux containers on macOS/Windows. Provider accounts and settings are shared by users of the ComfyUI instance.
- **Custom prompt skills:** place each skill folder, including its `SKILL.md` and supporting files, at
  `user/__arisu_nodes/skills/<skill-name>/` under ComfyUI's user directory. The pack creates the `skills`
  directory on startup; administrators manage its contents. Select `custom:<skill-name>` in Prompt Workbench.

In Prompt Workbench, choose a skill, connect your contexts, and click **Generate prompt**.
For a first clip, turn off **Motion Context → Enable motion context** to keep the wires
connected and generate without waiting for the video queue. Settings and references use
CPU; enabled motion decoding uses the queued GPU with a separate preparation cache.
**Agent time** shows elapsed generation time in the node and Generation results, excluding queueing
and media preparation. The final duration stays available while the workflow remains open.
Open **Generation results**, review the **Output Prompt** tab, and click **Apply to Workbench**
to replace the finalized prompt. Use Undo to restore the previous text. Workflow edits and
switching between open tabs preserve the running job and its result.

Generation uses your selected skill, context notes, and cropped images. Videos contribute
up to eight stills from the selected clip; audio contributes notes only. Agents are restricted
to prompt generation, with web search, commands, and file editing disabled.

## Nodes

Click a node name for its full reference, also available through the node's right-click **Help** menu.

### Common

| Node                                                                          | Summary                                                     |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| [Path Builder](web/docs/ArisuPathBuilder/en.md)                               | Build a filename prefix from separate text fields.          |
| [Extract Last Images](web/docs/ArisuExtractLastImages/en.md)                  | Keep the last N images from a batch.                        |
| [Preview & Save Image](web/docs/ArisuPreviewSaveImage/en.md)                  | Preview images and save them on demand.                     |
| [Preview & Save Image (Upscale)](web/docs/ArisuPreviewSaveImageUpscale/en.md) | Upscale previewed images when saving.                       |
| [Load Image (Browse)](web/docs/ArisuLoadImage/en.md)                          | Browse and crop images from configured directories.         |
| [Resize Image](web/docs/ArisuResizeImage/en.md)                               | Resize images by cropping, padding, fitting, or stretching. |

### MiniMax H3

| Node                                                                                        | Summary                                                                       |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| [MiniMax H3 Model Loader](web/docs/ArisuMiniMaxH3Loader/en.md)                              | Load H3 natively or experimentally replace an inclusive AdaLN block range.    |
| [MiniMax H3 Prompt Workbench](web/docs/ArisuMiniMaxH3PromptWorkbench/en.md)                 | Write prompts or generate and review drafts with Codex or Grok.               |
| [MiniMax H3 Resource Studio](web/docs/ArisuMiniMaxH3ResourceStudio/en.md)                   | Arrange, crop, and trim keyframes and image, video, or audio references.      |
| [MiniMax H3 Hybrid to Video](web/docs/ArisuMiniMaxH3HybridToVideo/en.md)                    | Combine keyframes and media references into H3 conditioning and an AV latent. |
| [MiniMax H3 Hybrid to Video (Advanced)](web/docs/ArisuMiniMaxH3HybridToVideoAdvanced/en.md) | Add upscaled conditioning for two-pass workflows.                             |
| [MiniMax H3 Video Settings](web/docs/ArisuMiniMaxH3VideoSettings/en.md)                     | Set canvas size, aspect ratio, and duration in one bundle.                    |
| [MiniMax H3 Video Settings (Upscale)](web/docs/ArisuMiniMaxH3VideoSettingsUpscale/en.md)    | Include a target size for latent upscaling.                                   |

See [example workflows](example_workflows) for ready-made graphs and the [changelog](CHANGELOG.md) for release notes.

## License

[GPL-3.0-only](LICENSE).
