# Preview & Save Image (Upscale)

**Preview & Save Image** with an upscale model applied when saving. A run writes only temporary previews and never
touches the model; the **save** button upscales the previewed images with `upscale_model` and writes
them under ComfyUI's output directory at `path`, without queueing a run. `none` saves them as is.

## Why

Upscaling every candidate of a batch run is wasted GPU time when only one gets kept. This node keeps
the run light and spends the upscale on the image you pick, with the same tiled model upscale as
ComfyUI's **Upscale Image (using Model)**.

## Inputs

| Parameter       | Type   | Description                                                                                                                                                                                                                                  |
|-----------------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `images`        | IMAGE  | The batch to preview. Every image in it is saved on click, one file each.                                                                                                                                                                    |
| `path`          | STRING | Where the button saves: a filename prefix under ComfyUI's output directory with **Save Image**'s `filename_prefix` rules (default `ComfyUI`). `shots/a` saves `output/shots/a_00001_.png`; `%year%`, `%width%` and the like are expanded; absolute paths and `..` are refused. Can be linked from **Path Builder**. |
| `upscale_model` | COMBO  | A model from `models/upscale_models`, or `none` (default) to save at the original size. Applied when saving, never during the run.                                                                                                            |
| `save`          | button | Upscale and save the images the preview currently shows.                                                                                                                                                                                     |

## Outputs

| Output   | Type  | Description                                              |
|----------|-------|----------------------------------------------------------|
| `images` | IMAGE | The input batch, unchanged and at the original size.     |

## Wiring

```
VAE Decode ─▶ Preview & Save Image (Upscale) ─▶ (images) next node
Path Builder ─▶ (path)
```

## Notes

- A click accepts at most 256 previews and a 1 MiB JSON request. Only one save runs at a time;
  a busy request returns 429 and can be retried after the current save finishes, even if its browser disconnected.
- Preview reads stay under ComfyUI's temp directory and writes stay under its output directory,
  including symlink targets. Supply `path` as a relative filename prefix; absolute paths are refused
  even when already inside output. Every `..` component is refused. External image roots cannot
  redirect saves. Temporary previews remain in temp. Existing files
  and symlinks are never overwritten; the counter advances to an unused filename.

- The upscale runs on the GPU inside the save request, sharing it with any job that is running. It
  uses 512 px tiles with a 32 px overlap and halves the tile when memory runs out, like the stock
  node; very large images can still exceed available memory.
- The saved size is the preview size times the model's factor (`4x-...` models give 4×). The preview
  and the `images` output stay at the original size.
- Everything in the notes of **Preview & Save Image** applies: run first, `path` is read at click
  time, saved files carry the workflow metadata and a counter suffix.
- Selecting a model does not queue a run; the model list refreshes when the node definitions are
  reloaded (for example after adding a model and refreshing the page).
