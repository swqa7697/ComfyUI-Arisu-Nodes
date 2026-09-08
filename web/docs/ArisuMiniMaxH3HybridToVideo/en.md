# MiniMax H3 Hybrid to Video

Builds MiniMax H3 conditioning from a prompt, optional first/last keyframes, and optional
`<Picture i>` / `<Video k>` / `<Audio j>` references, all in one node. It outputs the positive
conditioning and the joint video+audio latent, ready for the sampler, exactly like the stock
**MiniMax H3 Image to Video** and **MiniMax H3 Reference to Video** nodes.

Those two stock nodes cannot be chained because each builds its own latent and only sets its own
conditioning key. The model itself already packs keyframes and references together, so this node
sets both on one conditioning.

## Inputs

| Parameter            | Type   | Description                                                                                        |
|----------------------|--------|----------------------------------------------------------------------------------------------------|
| `clip`               | CLIP   | The MiniMax H3 text encoder (Qwen3-VL).                                                            |
| `vae`                | VAE    | Video VAE; encodes keyframes and visual references.                                                |
| `audio_vae`          | VAE    | Optional. Audio VAE, needed only when a reference audio or a reference video soundtrack is connected. |
| `prompt`             | STRING | Prompt. Refer to references with the same `<Picture i>` / `<Video k>` / `<Audio j>` tags.          |
| `width`, `height`    | INT    | Canvas in pixels, multiples of 32 (default 1344 x 768). Wire them from a **MiniMax H3 Video Settings** node, or let one advertise; see the notes. |
| `length`             | INT    | Frame count at 24 fps, snapped up to the 17k+5 grid (default 124, about 5 s). Same sources as the canvas. |
| `ref_image_size`     | COMBO  | `match` scales each reference image down to the generation's pixel area; `max` caps its short edge at 2048 px. |
| `frame_picture_tags` | COMBO  | How the keyframes appear to the text encoder; see below.                                           |
| `first_frame`        | IMAGE  | Optional keyframe pinned at frame 0. Stretched to the canvas.                                      |
| `last_frame`         | IMAGE  | Optional keyframe pinned at the last frame. Center-cropped to the canvas.                          |
| `ref_image_N`        | IMAGE  | Up to 9 reference images, `<Picture i>`.                                                           |
| `ref_video_N`        | IMAGE  | Up to 3 reference clips as frame batches at 24 fps, `<Video k>`. Cropped to the video's length and to the 17k+5 grid; at least 5 frames. |
| `ref_video_audio_N`  | AUDIO  | Soundtrack of the same-numbered reference video. Gets its own `<Audio j>` label right before the video. |
| `ref_audio_N`        | AUDIO  | Up to 3 standalone reference audios, `<Audio j>`.                                                  |

## Outputs

| Output     | Type         | Description                                                    |
|------------|--------------|----------------------------------------------------------------|
| `positive` | CONDITIONING | Prompt embeddings with the keyframe and reference payloads.    |
| `latent`   | LATENT       | Empty MiniMax H3 AV latent for the requested size and length.  |

## `frame_picture_tags`

The text encoder numbers picture items 1-based in the order it sees them, and it can only see
the keyframes if they are presented as picture items alongside the reference images. This widget
decides where they go:

- `after_refs` (default): reference images keep `<Picture 1..n>` exactly as with the stock
  Reference to Video node, and the first/last frames follow as `<Picture n+1..>`. Prompts written
  for the stock node stay valid.
- `before_refs`: the first/last frames take `<Picture 1..>` as with the stock Image to Video node,
  and reference images are numbered after them.
- `none`: the frames only pin the video (they still reach the model as keyframes) and are invisible
  to the prompt.

In every mode the keyframes are sent to the model once, as keyframes. They never become extra
reference blocks.

## Notes

- When a **MiniMax H3 Video Settings** node in the same graph advertises, `width`, `height` and
  `length` come from it: the widgets grey out, a link into them is refused, and one already there is
  removed with a notice. Inside a subgraph, wire the settings node's outputs into these inputs
  instead; advertising covers the root graph only.
- Reference order in the prompt is fixed: images, then videos (each soundtrack's `<Audio j>` right
  before its `<Video k>`), then standalone audio. Ordinals are 1-based per type.
- The output conditioning is compatible with **Add Guide for MiniMax H3**, which can be chained
  after this node to anchor more frames.
- Pair the model with **ModelSamplingMiniMaxH3** (video shift 12.0, audio shift 3.0) as with the
  stock nodes. Batch size is 1.
