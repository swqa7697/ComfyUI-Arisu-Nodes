# MiniMax H3 Context Latent Resize

**Beta.** Resize a saved MiniMax H3 AV latent to a new resolution so a clip chain can change size at
a join. Built for the `context_latent` input of the third-party **H3 Motion Context** chaining node,
which refuses a previous clip whose resolution differs from the clip being generated. The picture is decoded, lanczos-resized and
encoded again with the H3 video VAE; the audio stream and the frame count are passed through
untouched.

## Why

A motion-context chain pins the last frames and the last second of sound of clip A at the head of
clip B by slicing them straight out of A's latent. That only works when both clips have the same
resolution, and the pack refuses otherwise.

ComfyUI's stock **Upscale Latent** and **Upscale Latent By** cannot help:

- The chaining pack's Load Latent node emits the video/audio pair as a plain list, and a sampler emits
  it as a `NestedTensor`. Both stock nodes fail on either container with an `AttributeError`.
- **Upscale Latent** divides pixel sizes by 8. H3's VAE is 16x, so even a fixed container would land
  on the wrong grid.
- Interpolating the 24-channel latent directly hands the model context it never saw in training. The
  join comes out soft and can shift colour.

Resizing in pixel space instead yields a real latent for the new size. It costs one VAE round trip on
the picture only; the sound stays bit-exact.

## Inputs

| Parameter         | Type   | Description                                                                                          |
|-------------------|--------|------------------------------------------------------------------------------------------------------|
| `latent`          | LATENT | The previous clip's AV latent: the output of the chain's Load Latent node, or a sampler's AV latent. |
| `vae`             | VAE    | The MiniMax H3 video VAE, the same one the Motion Context node takes.                                |
| `width`, `height` | INT    | Resolution of the clip being generated next, multiples of 16 (default 1344 x 768).                   |
| `crop`            | COMBO  | `disabled` stretches the frames to the new size; `center` keeps the aspect ratio and crops the overflow. |

## Outputs

| Output   | Type   | Description                                                                                          |
|----------|--------|------------------------------------------------------------------------------------------------------|
| `latent` | LATENT | The AV latent at the new resolution, in the same container as the input. Wire it into `context_latent`. |

When the input already has the requested resolution the node returns it as is and the VAE is not
touched.

## Wiring

```
H3 Motion Context Load Latent ─▶ MiniMax H3 Context Latent Resize ─▶ (context_latent) H3 Motion Context
                                        ▲
                             H3 video VAE (same as Motion Context's vae)
```

Set `width` / `height` to the size of the clip being generated, that is, the size of the empty latent
feeding the sampler. Keep the aspect ratio equal to the previous clip's or use `center`.

## Notes

- Only the video stream changes. The audio stream, the temporal length, and any other keys in the
  latent dict pass through unchanged, so the chaining node's frame and audio arithmetic still holds.
- The output is a plain list when the input was one. That is deliberate on the chaining pack's side:
  such a latent is only meant for `context_latent` and is not decodable by stock nodes.
- The whole previous clip is decoded to 32-bit pixels on the CPU: about 1.5 GB for 124 frames at
  1344 x 768. VRAM stays bounded because the H3 VAE tiles internally.
- ComfyUI's lanczos resize goes through 8-bit images. Every other H3 path that encodes pixels (the
  stock nodes, the chaining pack's own pixel fallback, an h264 decode) has the same hop, and it is far
  below the VAE's own reconstruction error.
- A resolution change is still one lossy join per chain: the pinned frames are a VAE reconstruction of
  the previous clip rather than the exact numbers the model produced. Same-size joins do not need this
  node and stay bit-exact.
- The node refuses latents that are not an H3 video/audio pair, and refuses to run if the VAE ever
  changes the temporal length during the round trip, rather than building a context that lands at the
  wrong instant.
