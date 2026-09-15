# MiniMax H3 Video Settings

One place for the canvas and the clip length of a MiniMax H3 workflow. Pick an aspect ratio and a
megapixel budget to get `width` and `height` on the model's 32-pixel grid, and a duration in seconds
to get `length` on its 17k+5 frame grid. Wire `video_settings`, the bundle of every other output,
into the **MiniMax H3 Hybrid to Video** nodes' input of the same name, wire the individual outputs
into any INT input, or let the node advertise the bundle.

Turn `advertise_settings` on (it is off by default) and every hybrid node in the same graph takes the
bundle automatically: its `video_settings` socket and its own `width` / `height` / `length` widgets
grey out the moment the switch flips, refuse links, and a hybrid node added later arrives greyed.

## Why

Workflows build these numbers from generic helpers (a resolution selector, a math expression for the
frame grid) and fan them out to every consumer with three or more links, or with Set/Get nodes. This
node keeps the maths in one place and, when advertising, needs no links at all to drive the hybrid
nodes.

## Inputs

| Parameter      | Type    | Description                                                                                          |
|----------------|---------|------------------------------------------------------------------------------------------------------|
| `aspect_ratio` | COMBO   | The eight ratios of ComfyUI's **Resolution Selector**, same labels (default `16:9 (Widescreen)`).     |
| `megapixels`   | FLOAT   | Pixel budget in megapixels of 1024 x 1024 (default 1.0). The stock 1344 x 768 canvas is about 0.98 MP. |
| `duration`     | FLOAT   | Clip length in seconds at 24 fps (default 5.0 = 124 frames). Snapped up to the 17k+5 grid.            |
| `advertise_settings` | BOOLEAN | Drive every hybrid node in this graph (default off); their widgets grey out at once and refuse links. Read by the frontend only. |

## Outputs

| Output           | Type                            | Description                                                                 |
|------------------|---------------------------------|-----------------------------------------------------------------------------|
| `video_settings` | ARISU_MINIMAX_H3_VIDEO_SETTINGS | Every other output in one bundle, output index 0, for the hybrid nodes' `video_settings` input. |
| `width`          | INT                             | Canvas width, a multiple of 32.                                             |
| `height`         | INT                             | Canvas height, a multiple of 32.                                            |
| `length`         | INT                             | Frame count on the 17k+5 grid.                                              |
| `aspect_ratio`   | COMBO                           | Exact ratio label, output index 4.                                          |

The outputs are always available, whether or not the node advertises; consumers pick what they accept.
The hybrid nodes take the bundle and use its canvas and length; the ratio rides along for other
consumers.

## Wiring

```
Video Settings ─ video_settings ─▶ (video_settings) Hybrid to Video    one explicit link, works anywhere
               ├ width / height ─▶ any INT input
               └ length ─────────▶ any INT input

Video Settings (advertise_settings on)   ...   Hybrid to Video           no link: video_settings is injected at queue time
```

## Notes

- Advertising covers the root graph only. Inside a subgraph, wire `video_settings` explicitly; the
  link works everywhere and owns the same hybrid widgets as advertising does.
- Only one settings node per graph advertises at a time, muted or not. Switching a second one on
  hands it the slot and switches the previous one off with a warning. Saved and imported workflows
  retain the toggle; an enabled pasted or duplicated node takes the slot. A loaded workflow with
  several enabled nodes keeps the first in node order.
- Greyed widgets keep their old numbers but they are not used; the bundle always wins. A link into a
  greyed widget is refused, and one that was already there is removed with a notice. While a source
  advertises, the hybrids' `video_settings` socket is greyed too and an explicit wire into it is dropped.
- The greying updates when the switch flips, when a node is added or removed, and when a workflow
  loads, and immediately when a source is muted or bypassed.
- A muted or bypassed source retains its advertising switch but releases owned controls. A partial
  prompt missing an active source is rejected; it does not fall back to local widget values.
- For a two-sampler latent-upscale workflow use **MiniMax H3 Video Settings (Upscale)**, which adds
  the target size.

## Resource Studio integration

The `aspect_ratio` combo output connects to **MiniMax H3 Resource Studio**. Advertising also owns Studio's aspect selector, dropping its wire and applying the effective ratio. Keyframes are auto-cropped when that ratio changes. API exports include the same dependencies as queueing; a missing active source rejects the prompt instead of falling back to local values. Advertising is root-graph only; use explicit wires in subgraphs.
