# MiniMax H3 Hybrid to Video (Advanced)

**MiniMax H3 Hybrid to Video** for two-sampler latent-upscale workflows. It builds the same
conditioning and AV latent as the hybrid node (prompt, optional first/last keyframes, optional
`<Picture i>` / `<Video k>` / `<Audio j>` references) and adds a third output: a positive
conditioning whose keyframes are encoded at the size of the finally upscaled video.

## Why

In a two-pass workflow, sampler 1 runs at the generation size, a latent upscaler (for example
**Minimax H3 Latent Upscaler (3D)**) enlarges the video latent, and sampler 2 refines it. The
keyframe latents in the first-pass conditioning are still at the generation size, so sampler 2 fails
with

```
RuntimeError: shape mismatch: value tensor of shape [7546, 96] cannot be broadcast to indexing result of shape [15106, 96]
```

Resampling the keyframe latents onto the new grid avoids the error but blurs the anchors. This node
re-encodes the original pixel keyframes at the target size instead, so the second pass gets sharp
anchors.

## Inputs

Everything from **MiniMax H3 Hybrid to Video** (see its help page) plus:

| Parameter                         | Type | Description                                                                                  |
|-----------------------------------|------|----------------------------------------------------------------------------------------------|
| `target_width`, `target_height`   | INT  | Size of the upscaled video in pixels, multiples of 32 (default 2688 x 1536). Set them to what the latent upscaler outputs. An advertising **MiniMax H3 Video Settings (Upscale)** node drives them like the canvas; the plain settings variant leaves them manual. |

## Outputs

| Output                | Type         | Description                                                                              |
|-----------------------|--------------|------------------------------------------------------------------------------------------|
| `positive`            | CONDITIONING | The first-pass conditioning: keyframes encoded at `width` x `height`.                    |
| `latent`              | LATENT       | Empty MiniMax H3 AV latent at `width` x `height` for sampler 1.                           |
| `positive (upscaled)` | CONDITIONING | Same prompt embeddings and references, keyframes encoded at `target_width` x `target_height`. |

The first two outputs match the hybrid node, so it can replace that node without rewiring.

## Wiring

```
                     ┌─ positive ──────────▶ Guider 1 ─▶ Sampler 1 ─▶ Latent Upscaler ─▶ Sampler 2
Hybrid (Advanced) ───┼─ latent ────────────▶ Sampler 1                                     ▲
                     └─ positive (upscaled) ─────────────────────────▶ Guider 2 ───────────┘
```

The latent upscaler's output size must equal `target_width` x `target_height`. With
**Minimax H3 Latent Upscaler (3D)** use its `target dimensions` mode with the same numbers, or make
sure its multiplier lands on them after its 32-pixel alignment.

## Notes

- Keyframes are resized once per distinct canvas. A frame that already has the generation size, or
  the target size, is passed to the VAE as is: ComfyUI's lanczos resize goes through 8-bit images even
  when the size does not change, so skipping it keeps the frame exact.
- When `target_width` x `target_height` equals `width` x `height`, nothing is encoded twice and
  `positive (upscaled)` is the same conditioning as `positive`.
- Reference images are sized for each pass. With `ref_image_size = match` they are scaled to the
  pixel area of that pass, so the upscaled pass carries larger reference tokens and samples slower;
  with `max` the size does not depend on the pass. A reference is encoded again only when its size
  differs between the passes, otherwise both conditionings share the same block.
- Reference videos and audio never depend on the generation size (videos use the model's fixed
  768-short-edge canvas), so they are encoded once and shared.
- The text encoder sees the keyframes and references at the generation size only, because the prompt
  is encoded once; `frame_picture_tags` works as in the hybrid node.
- The same crop policy applies at both sizes: `first_frame` is stretched, `last_frame` is
  center-cropped. Keep the target aspect equal to the generation aspect unless you want a different
  crop in the second pass.
- Keyframes added later by **Add Guide for MiniMax H3** or a motion-context node are not covered;
  add them against the latent of the pass they belong to.

## Resource Studio input

Connect the optional `resources` input from **MiniMax H3 Resource Studio**, or enable Studio's root-graph advertising. Bundle ownership hides and disconnects individual keyframe/reference inputs. While advertising, `resources` remains visible but disabled and disconnected. Releasing ownership restores empty sockets; Undo can restore the previous wires. Direct API calls cannot combine a bundle with populated individual resource inputs.

An empty bundle intentionally supplies no resources. Hybrid validates source revisions, reads original cropped pixels, and performs consumer-specific resizing. It samples selected videos at 24 fps, caps them to generation length, and aligns down to `17k+5`; paired audio follows the effective video interval. Standalone audio keeps its own selection. Muted sources are excluded, and an audio VAE is needed only when active resources emit audio. The Advanced variant derives each distinct canvas directly from original cropped pixels.
