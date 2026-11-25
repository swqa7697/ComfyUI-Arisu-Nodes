# MiniMax H3 Unpack Video Settings

Read individual values from a `video_settings` bundle. Connect **Director Workbench**, **Video Settings**, or **Video Settings (Upscale)** to the input.

## Outputs

| Output | Type | Value |
| --- | --- | --- |
| `width` | INT | Generation canvas width in pixels. |
| `height` | INT | Generation canvas height in pixels. |
| `length` | INT | Generation frame count at 24 fps, already aligned to the H3 `17k+5` grid. |
| `aspect_ratio` | COMBO | The original aspect ratio label. |
| `upscale_factor` | FLOAT | The stored upscale factor, or `1.0` when absent. |
| `target_width` | INT | The stored target width, or the generation canvas width when absent. |
| `target_height` | INT | The stored target height, or the generation canvas height when absent. |

## Wiring

```text
Director Workbench ─ video_settings ─┬─▶ Hybrid to Video.video_settings
                                    └─▶ Unpack Video Settings ─ length ─▶ an INT input
```

Director supplies the selected segment's finalized settings. `length` includes any continuation overlap; it is not the trimmed delivery length or a duration in seconds. For example, a 15-second request produces 362 frames.

Director and plain Video Settings do not carry upscale values. Unpack outputs `1.0` and the canvas dimensions for those sockets. It does not modify the bundle or the Hybrid node's target settings. Connect only the individual outputs you need.

The input needs an explicit connection, which can pass through KJNodes Set/Get. This node does not receive advertised settings automatically.
