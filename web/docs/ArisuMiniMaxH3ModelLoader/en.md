# MiniMax H3 Model Loader

Load one H3 checkpoint in **native** mode (the default), or build one experimental
**hybrid** model from two compatible checkpoints. Both modes return the same
standard **MODEL** socket for downstream model patches and sampling.

Choose `mode` first, then `base_model` from ComfyUI's registered diffusion models.
Supported containers are unsharded `.safetensors` and `.sft` with unprefixed H3 tensor names.
`weight_dtype`, the last widget, is an advanced native loading option; `default`
leaves the choice to ComfyUI. The FP8 choices request native model operations, not conversion between
arbitrary checkpoint quantization formats. `native` mode also permits pre-composed
checkpoints supported by the installed ComfyUI H3 implementation.

In **hybrid**, choose an `overlay_model` and enter `block_start` and `block_end`.
Indices are zero-based and inclusive: `45–49` selects five block AdaLN families,
`17–17` selects one, and `0–49` selects all fifty. The editable initial values
`25–49` are not a quality recommendation. Advanced `include_final_adaln` additionally
replaces final AdaLN; it defaults off and never changes the block interval.

`hybrid` replaces each selected weight and bias as a complete family before native
model construction. Attention, MLPs, output heads, and the time embedder or pruned
curve table remain from base. Pruned replacement therefore uses overlay's
coefficients with base's curve, which does not reproduce overlay's exact function.
Different finite curve values are allowed; matching layouts do not prove lineage
or generation quality.

Initial `hybrid` support is restricted to matching unquantized canonical full/full
or 1025-by-8 pruned/pruned H3 layouts (including F16 AdaLN in pruned BF16 releases).
Mixed full/pruned pairs, architecture conflicts, quantization declarations and
companions, and declared baked compositions are rejected. Use `native` for quantized
or pre-composed checkpoints. Unknown representations require explicit support.

`native` keeps the `hybrid` controls visible but disabled and ignores their settings,
including a missing previous overlay.
`hybrid` fails clearly for an invalid active selection and never silently becomes
`native`. Switching mode preserves the output connection and saved `hybrid` controls;
ComfyUI controls execution caching and model eviction.

`hybrid` follows the native AIMDO or mmap reader and preserves tensor references.
When ordinary mmap is explicitly disabled, only selected overlay tensors are
copied to owned CPU storage. The log reports selected tensor bytes, not peak RAM
or VRAM. Reload factories retain the exact interval, final toggle, dtype, and file
identity; replacing a source requires re-execution. Do not edit mapped checkpoints
while they are in use.

`hybrid` remains experimental. Header compatibility and small storage tests do not
certify generation quality, full-model GPU offload under memory pressure,
multi-GPU execution, every downstream patch, or Windows/macOS behavior. No range
is universally better. Compare with `native` using your own fixed prompts and seeds.
