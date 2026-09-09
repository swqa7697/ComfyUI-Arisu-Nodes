# Resize Image

Resize an image batch to `width` × `height`: stretched, fitted, padded or cropped to the size and
snapped to a pixel grid, with the result shown on the node. Everything but the size lives behind the
**settings…** button.

## Why

**Upscale Image** stretches to a size or centre-crops to it, and that is all: filling a canvas
means computing offsets by hand for **Pad Image for Outpainting**, cropping off-centre means a
**Crop Image** in front, hitting the pixel grid a model wants means doing the arithmetic yourself,
and seeing the result means hanging a **Preview Image** off the node. This node does all of it in
one step and shows what came out. The options that rarely change are in a dialog, so the node stays
two fields tall.

## Inputs

| Parameter         | Type   | Description                                                                                                                                                                                   |
|-------------------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `image`           | IMAGE  | The batch to resize; every image gets the same geometry.                                                                                                                                      |
| `width`           | INT    | The output width in pixels (default 512). `0` takes it from the image: the image's own width in `stretch` and `crop`, the width that keeps the aspect ratio in the fit and pad modes.          |
| `height`          | INT    | The output height, likewise.                                                                                                                                                                  |
| `mask`            | MASK   | Optional. Follows the image through the crop, the scale and the pad. A 64×64 mask on an image of another size is ComfyUI's "no mask" placeholder and counts as none; another size is fitted to the image first. |
| `settings…`       | button | Open the dialog that edits the five settings below. **reset** puts them back to their defaults.                                                                                               |
| `upscale_method`  | combo  | Settings dialog. `nearest-exact`, `bilinear`, `area`, `bicubic` or `lanczos` (default); lanczos is the sharpest for photos, nearest-exact keeps hard edges.                                    |
| `keep_proportion` | combo  | Settings dialog. How the size is reached; the modes are described below (default `stretch`).                                                                                                  |
| `pad_color`       | STRING | Settings dialog. The `pad` mode's fill (default `0, 0, 0`): `r, g, b` in 0-255, or in 0.0-1.0 when a part has a decimal point; `#rrggbb`; one grey value; or a colour name such as `white`. The dialog has a colour picker beside it. |
| `crop_position`   | combo  | Settings dialog. Where the image stays (default `center`): the region kept in `crop`, and the side the image sits on in the pad modes, so `top` puts the padding at the bottom.               |
| `divisible_by`    | INT    | Settings dialog. Round the output size down to a multiple of this (default 2); `0` or `1` for none.                                                                                           |

The `keep_proportion` modes:

- `stretch`: exactly `width` × `height`, ignoring the aspect ratio.
- `resize`: the largest size of the image's aspect ratio that fits inside `width` × `height`; the
  output may be smaller than the request on one side.
- `pad`, `pad_edge`, `pad_edge_pixel`, `pillarbox_blur`: the image is fitted as in `resize`, then
  placed on a `width` × `height` canvas at `crop_position`. The rest is `pad_color`, the mean colour
  of each edge, the edge pixels repeated outward, or a blurred and dimmed copy of the image.
- `crop`: the largest region of the image with the requested aspect ratio, anchored at
  `crop_position`, scaled to exactly `width` × `height`.
- `total_pixels`: `width` × `height` is a pixel budget, spent at the image's aspect ratio; both
  must be set.

## Outputs

| Output  | Type  | Description                                                                                                                        |
|---------|-------|------------------------------------------------------------------------------------------------------------------------------------|
| `image` | IMAGE | The resized batch: exactly the request after the grid in every mode but `resize` and `total_pixels`.                                |
| `mask`  | MASK  | The input mask resized alike, with `1` over any padding. Without an input mask: `1` over the padding and `0` under the image in the pad modes, ComfyUI's empty 64×64 mask otherwise. |

## Wiring

```
Load Image (Browse) ─▶ Resize Image (width = 1024, height = 576) ─▶ (first_frame) MiniMax H3 Hybrid to Video
                                                              └▶ (mask) any MASK input
```

## Notes

- The five settings are ordinary inputs that the pack's frontend script hides; they are saved with
  the workflow and appear in the prompt JSON. They have no sockets, so feed `width` and `height` by
  link, not the settings.
- The result is previewed on the node the way ComfyUI's own **Image Crop** previews: the preview
  survives cache hits and a page reload, and shows in both the classic canvas and the Vue node
  renderer ("Nodes 2.0"), where the dialog works too. The node runs when something downstream needs
  its output; on its own it is not an output node.
- Bypassing the node passes `image` through to `image` and `mask` through to `mask`; with no mask
  connected, the mask output then carries nothing.
- In the pad modes the canvas is snapped to `divisible_by` first and the image fitted inside it, so
  the output is exactly the snapped request: `pad` at 1000×500 with `divisible_by` 16 gives 992×496,
  never a size that only nearly fits the grid. The padding is always `1` in the mask, whether or not
  a mask came in.
- A zero `width` or `height` works in every mode but `total_pixels`, which refuses it when the
  prompt is validated. `divisible_by` never rounds a side below one multiple.
- The resize always runs on the CPU, which is where `lanczos` runs in any case, so it never competes
  with a sampler for VRAM.
- If the button is missing or the five widgets show on the node, check the browser console for a
  failed load of `resize_image.js`.
