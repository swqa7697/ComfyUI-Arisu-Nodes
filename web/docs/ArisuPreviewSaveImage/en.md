# Preview & Save Image

Preview an image batch and pass it through unchanged. A run saves nothing; the **save** button
writes the previewed images under ComfyUI's output directory at `path`, without queueing a run.

## Why

**Preview Image** shows a result but keeps nothing, and **Save Image** keeps every result of every
run. Picking the one good frame out of many runs means re-running with a save node wired in, or
digging the file out of the temp directory. This node previews like the first and saves like the
second, but only when you click.

## Inputs

| Parameter | Type   | Description                                                                                                                                                                                                                                  |
|-----------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `images`  | IMAGE  | The batch to preview. Every image in it is saved on click, one file each.                                                                                                                                                                    |
| `path`    | STRING | Where the button saves: a filename prefix under ComfyUI's output directory with **Save Image**'s `filename_prefix` rules (default `ComfyUI`). `shots/a` saves `output/shots/a_00001_.png`; `%year%`, `%width%` and the like are expanded; absolute paths and `..` are refused. Can be linked from **Path Builder**. |
| `save`    | button | Save the images the preview currently shows.                                                                                                                                                                                                 |

## Outputs

| Output   | Type  | Description                 |
|----------|-------|-----------------------------|
| `images` | IMAGE | The input batch, unchanged. |

## Wiring

```
VAE Decode ─▶ Preview & Save Image ─▶ (images) next node
Path Builder ─▶ (path)
```

## Notes

- The button saves what the preview shows, so run first. After a page reload or a ComfyUI restart
  the preview has to be produced again; the button says so instead of saving.
- `path` is read when you click, so it can change between saves without a re-run. When `path` is
  fed by a link, the value from the last run is used.
- Saved files are PNG with the preview's workflow metadata, like **Save Image**. The counter suffix
  means a second click never overwrites the first save.
- The button is added by the pack's frontend script in the classic node canvas. If it is missing,
  check the browser console for a failed load of `preview_save_image.js`.
