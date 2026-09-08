# MiniMax H3 Video Settings

One place for the canvas and the clip length of a MiniMax H3 workflow. Pick an aspect ratio and a
megapixel budget to get `width` and `height` on the model's 32-pixel grid, and a duration in seconds
to get `length` on its 17k+5 frame grid. Wire the outputs into the **MiniMax H3 Hybrid to Video**
nodes' inputs of the same name, or let the node advertise them.

Turn `advertise` on (it is off by default) and every hybrid node in the same graph takes these
values automatically: its own `width` / `height` / `length` widgets grey out the moment the switch
flips, refuse links, and a hybrid node added later arrives greyed.

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
| `advertise`    | BOOLEAN | Drive every hybrid node in this graph (default off); their widgets grey out at once and refuse links. Read by the frontend only. |

## Outputs

| Output     | Type | Description                          |
|------------|------|--------------------------------------|
| `width`    | INT  | Canvas width, a multiple of 32.       |
| `height`   | INT  | Canvas height, a multiple of 32.      |
| `length`   | INT  | Frame count on the 17k+5 grid.        |

The outputs are always available, whether or not the node advertises.

## Wiring

```
Video Settings ─ width ─────▶ (width) Hybrid to Video           explicit links, work anywhere
               ├ height ────▶ (height) Hybrid to Video
               └ length ────▶ (length) Hybrid to Video, or any INT input

Video Settings (advertise on)   ...   Hybrid to Video           no link: the values are injected at queue time
```

## Notes

- Advertising covers the root graph only. Inside a subgraph, wire the outputs explicitly; the links
  work everywhere.
- Only one settings node per graph advertises at a time, muted or not. Switching a second one on
  hands it the slot and switches the previous one off with a warning; a pasted node that arrives
  switched on is switched off; a loaded workflow with several keeps the first in node order.
- Greyed widgets keep their old numbers but they are not used; the advertised values always win. A
  link into a greyed widget is refused, and one that was already there is removed with a notice.
- The greying updates when the switch flips, when a node is added or removed, and when a workflow
  loads.
- A muted or bypassed settings node does not advertise, but muting has no frontend event: its
  widgets update on the next change above. When a run executes only part of the graph and the
  settings node is not in it, the hybrid nodes fall back to their widgets with a warning.
- For a two-sampler latent-upscale workflow use **MiniMax H3 Video Settings (Upscale)**, which adds
  the target size.
