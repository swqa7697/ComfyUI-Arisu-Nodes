# MiniMax H3 SelfLift Progressive Sampler

Run the first Euler steps on a smaller video latent, then finish at the target resolution. The transition reuses the last low-resolution prediction, so an eight-step schedule still uses eight denoiser evaluations. The audio stream keeps its original dimensions throughout.

## Wiring

1. Connect your H3 model to `model`. To use a different model for the full-resolution stage, connect it to `model_hires`. Both models must use the same architecture and latent format.
2. Set **MiniMax H3 Hybrid to Video** to the final canvas size. Connect its `positive` output to `positive`, your workflow's negative conditioning to `negative`, and the H3 video VAE to `vae`.
3. Connect the Hybrid node's `latent` output to the sampler's `latent` input. For a continuation clip, connect `context_latent` and `trim_frames` as described below.
4. Connect the standard `euler` sampler from **KSamplerSelect** to `sampler` and the model's sigma schedule to `sigmas`. Euler must have `s_churn=0`. Choose a lift mode below and send the output `latent` to the usual H3 video and audio decode path.

## Lift modes

| Mode | Settings | Behavior |
| --- | --- | --- |
| Learned latent lift | Select an H3 upscaler and set `rho=0` (default). | ComfyUI's native H3 model runs the checkpoint directly on the predicted video latent. The resolution transition skips the pixel anchor. |
| SelfLift-zero | Select `none` and set `rho>0`. Upstream suggests starting with `rho=0.6` and `w_min=w_max=1` for H3. | Compares the nearest-neighbor lift with a VAE decode, resize, and re-encode. Corrects the fraction of locations with the largest disagreement. |
| Hybrid (experimental) | Select an H3 upscaler and set `rho>0` and `w_max>0`. | Applies the same selective correction to the learned lift. |

Place optional H3 upscaler weights under `models/latent_upscale_models/`. Learned and hybrid lifts require a ComfyUI build with native MiniMax H3 latent upscaling. Existing H3 checkpoints, including `h3_upscaler_lms_v0.1.safetensors`, stay in the same selector. It defaults to the first installed filename containing `h3`, ignoring case. [Upstream H3 upscaler weights](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler)

## Controls

| Input | Default | Behavior |
| --- | --- | --- |
| `seed` | 0 | Seed for the low-resolution noise. The video transition uses the next seed, wrapping at 64 bits. |
| `control after generate` | Randomize | Choose how ComfyUI updates the seed for the next run. |
| `cfg` | 5.0 | Guidance scale for both stages. |
| `lowres_scale` | 0.5 | Scales latent height and width. The low-resolution grid rounds each dimension to an even size. |
| `transition_step` | 6 | Number of low-resolution steps. Leave at least one high-resolution step. The sigma at the start of that step must be below 1. |
| `rho` | 0.0 | Fraction of spatiotemporal locations selected for correction, per batch item. |
| `w_min`, `w_max` | 0.5, 1.0 | Smallest and largest correction weights at selected locations. Use `0 ≤ w_min ≤ w_max ≤ 1`. |
| `upscaler_model` | First installed H3 checkpoint, otherwise `none` | Select the checkpoint for a learned or hybrid lift. Select `none` for SelfLift-zero. |
| `upscaler_unload` | On | Releases the learned upscaler from VRAM after the lift, before the full-resolution stage. |
| `highres_tiling` | Off | **Experimental.** Selects 1–8 spatial tiles according to available memory. One tile uses the full frame. With multiple tiles, the final picture and sound can change even with the same seed. Each tile sees the full audio timeline and all references, but only part of the picture. The sampler blends video overlaps and weights each tile's audio prediction by its share of the picture. With Motion Context, this can affect the soundtrack you keep after trimming the pinned frames. Multi-tile sampling does not support ControlNet. |

An initialized latent can carry a noise mask. A value of 1 generates content and 0 preserves the input. The sampler resizes the mask to the latent grid and accepts one mask shared across frames. Disable tiling for masked sampling. For masked VAE correction, keep `rho` or `w_min` below 1. The upstream pure-anchor shortcut requires an unmasked latent.

### Continuing a clip with H3 Motion Context

1. Feed the **current** target latent to Motion Context and to SelfLift's `latent` input. Send Motion Context's conditioning output to SelfLift's `positive`.
2. Feed the **previous** clip's Load Latent output to `context_latent` on **both** nodes. Connect Motion Context's `trim_frames` output to **both** SelfLift and Motion Context Trim. For the first clip, a trim count of zero skips motion-guide preparation.
3. Decode and trim the sampler output as usual. SelfLift uses the trim count to prepare the guide. Motion Context Trim removes the pinned frames once.

At the low resolution, SelfLift resizes Arisu Hybrid's fitted first/last images before VAE encoding. For a continuation it resizes the previous clip's decoded tail and encodes the pinned frames together as one video, then places each token at its original frame index. With only `trim_frames` connected, it decodes the pinned guide tokens together to obtain the pixels. Third-party keyframes without source pixels or a declared motion window keep the latent resize. The high-resolution steps use the incoming full-resolution conditioning. Audio timing and guides are preserved throughout.

If you use Motion Context's optional single-step refine pass, keep SelfLift on the main sampling branch and use the ordinary sampler for refinement.

## Diagnostics

The console reports the sampling plan and stage timings. Set `SELFLIFT_TIMING_SYNC=1` before starting ComfyUI for CUDA-synchronized timings, or `SELFLIFT_MEMORY_LOG=1` for memory snapshots. Set `SELFLIFT_DEBUG=1` to decode the first frame of each transition intermediate to PNG. The console reports the new `arisu-selflift-*` directory under ComfyUI's temp directory for each run.

The progressive sampler is adapted from **comfyui-SelfLift**, revision `835c3cf`. The SelfLift paper evaluated image models. The native ComfyUI learned lift runs the H3 upscaler architecture originally published by LBH-123-AI. [Sampler source](https://github.com/facok/comfyui-SelfLift/tree/835c3cf7919410f71f414688f049c6ca497789d0) · [SelfLift paper](https://arxiv.org/abs/2609.02036) · [H3 upscaler project](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler)
