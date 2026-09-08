# MiniMax H3 Video Settings (Upscale)

**MiniMax H3 Video Settings** for two-sampler latent-upscale workflows. Besides the canvas and the
frame count it derives the size of the upscaled video from an `upscale_factor`, rounded to the
32-pixel grid, and puts `target_width` / `target_height` into the bundle so
**MiniMax H3 Hybrid to Video (Advanced)** encodes its second-pass keyframes at the right size.

## Inputs

Everything from **MiniMax H3 Video Settings** plus:

| Parameter        | Type  | Description                                                                              |
|------------------|-------|------------------------------------------------------------------------------------------|
| `upscale_factor` | FLOAT | Factor of the latent upscaler between the two samplers (default 2.0). Targets are rounded to multiples of 32. |

## Outputs

| Output           | Type                      | Description                                                                 |
|------------------|---------------------------|-----------------------------------------------------------------------------|
| `width`, `height`, `length` | INT            | As in **MiniMax H3 Video Settings**.                                        |
| `upscale_factor` | FLOAT                     | The factor, for a latent upscaler's multiplier input.                       |
| `target_width`   | INT                       | Upscaled width, a multiple of 32.                                           |
| `target_height`  | INT                       | Upscaled height, a multiple of 32.                                          |
| `settings`       | ARISU_MINIMAX_H3_SETTINGS | Bundle with all five values.                                                |

## Wiring

```
Video Settings (Upscale) ─ settings ─▶ (settings) Hybrid to Video (Advanced)
                         ├ upscale_factor ─▶ Latent Upscaler (multiplier)
                         └ target_width / target_height ─▶ Resize nodes for keyframes, previews, ...
```

## Notes

- Fed to the plain **MiniMax H3 Hybrid to Video**, the bundle's target keys are ignored.
- Fed to the Advanced node, the plain **MiniMax H3 Video Settings** bundle overrides width, height and
  length only; `target_width` / `target_height` stay manual.
- Make sure the latent upscaler lands on the same target size: with **Minimax H3 Latent Upscaler
  (3D)** in multiplier mode the 32-pixel alignment matches this node's rounding; in target mode, wire
  `target_width` / `target_height` into it.
- Advertising and its limits are the same as for **MiniMax H3 Video Settings**: root graph only,
  one advertiser per graph, explicit links win.
