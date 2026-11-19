# MiniMax H3 SelfLift Progressive Sampler

Run the first Euler steps on a smaller video latent, then finish at the target resolution. The transition reuses the last low-resolution prediction, so an eight-step schedule still uses eight denoiser evaluations. The audio stream keeps its original dimensions throughout.

## Wiring

1. Set **MiniMax H3 Hybrid to Video** to the final canvas size. Connect its `positive` output to `positive` and its `latent` output to `latent_image`. Connect your workflow's negative conditioning to `negative`.
2. Connect the H3 model, its video VAE, the standard `euler` sampler from **KSamplerSelect**, and the model's sigma schedule. Euler must have `s_churn=0`.
3. Choose a lift mode below. Send the output `latent` to the usual H3 video and audio decode path.

## Lift modes

| Mode | Settings | Behavior |
| --- | --- | --- |
| Learned latent lift | Select an H3 upscaler and set `rho=0` (default). | Runs the checkpoint directly on the video latent and skips the VAE round trip. |
| SelfLift-zero | Select `none` and set `rho>0`. Upstream suggests starting with `rho=0.6` and `w_min=w_max=1` for H3. | Compares the nearest-neighbor lift with a VAE decode, resize, and re-encode. Corrects the fraction of locations with the largest disagreement. |
| Hybrid (experimental) | Select an H3 upscaler and set `rho>0` and `w_max>0`. | Applies the same selective correction to the learned lift. |

Place optional H3 upscaler weights under `models/latent_upscale_models/`. The selector defaults to the first installed filename containing `h3`, ignoring case. If none matches, select a suitable checkpoint or raise `rho` above zero. [Upstream H3 upscaler weights](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler)

## Controls

| Input | Default | Behavior |
| --- | --- | --- |
| `seed`, `cfg` | 0, 5.0 | Seed for the low-resolution noise and guidance scale for both stages. The video transition uses the next seed, wrapping at 64 bits. |
| `transition_step` | 6 | Number of low-resolution steps. Leave at least one high-resolution step. The sigma at the start of that step must be below 1. |
| `lowres_scale` | 0.5 | Scales latent height and width. The low-resolution grid rounds each dimension to an even size. |
| `rho` | 0.0 | Fraction of spatiotemporal locations selected for correction, per batch item. |
| `w_min`, `w_max` | 0.5, 1.0 | Smallest and largest correction weights at selected locations. Use `0 ≤ w_min ≤ w_max ≤ 1`. |
| `model_hires` | Uses `model` | Optional model for the full-resolution stage. Use the same architecture and latent format. |
| `highres_tiling` | Off | Selects 1–8 spatial tiles according to available memory. Each tile sees the full audio and references. The sampler blends video overlaps and keeps the first tile's audio prediction. Tiling can change quality and speed. Multi-tile sampling does not support ControlNet. |
| `upscaler_unload` | On | Releases the learned upscaler from VRAM after the lift, before the full-resolution stage. |

An initialized latent can carry a noise mask. A value of 1 generates content and 0 preserves the input. The sampler resizes the mask to the latent grid and accepts one mask shared across frames. Disable tiling for masked sampling. For masked VAE correction, keep `rho` or `w_min` below 1. The upstream pure-anchor shortcut requires an unmasked latent.

## Diagnostics

The console reports the sampling plan and stage timings. Set `SELFLIFT_TIMING_SYNC=1` before starting ComfyUI for CUDA-synchronized timings, or `SELFLIFT_MEMORY_LOG=1` for memory snapshots. Set `SELFLIFT_DEBUG=1` to decode the first frame of each transition intermediate to PNG. The console reports the new `arisu-selflift-*` directory under ComfyUI's temp directory for each run.

This is the experimental H3 adaptation from **comfyui-SelfLift**, revision `835c3cf`. The SelfLift paper evaluated image models. The learned H3 upscaler uses the inference implementation credited to LBH-123-AI. [Sampler source](https://github.com/facok/comfyui-SelfLift/tree/835c3cf7919410f71f414688f049c6ca497789d0) · [SelfLift paper](https://arxiv.org/abs/2609.02036) · [H3 upscaler implementation](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler)
