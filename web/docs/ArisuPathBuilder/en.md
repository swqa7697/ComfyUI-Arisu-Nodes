# Path Builder

Join separate text fields into one path with `/`, for `filename_prefix` inputs such as
**Save Video**, **Save Image**, or a latent save node. Blank fields are skipped and surrounding
slashes and spaces are trimmed, so `minimax_h3` + `test` gives `minimax_h3/test`.

## Why

A prefix like `<project>/<series>` is usually assembled from two **String** primitives and a
**Concatenate Text** node, or from a subgraph wrapping them. This node holds the pieces as separate
fields on one node, so each part can be edited on its own and the whole prefix is one link.

## Inputs

| Parameter     | Type   | Description                                                                                     |
|---------------|--------|-------------------------------------------------------------------------------------------------|
| `segment_N`   | STRING | One path piece each, in order. Blank pieces are skipped; a piece may itself contain `/`.        |
| `+ field`     | button | Shows the next field (up to 16).                                                                |
| `- field`     | button | Hides the last visible field and clears it.                                                     |

The node starts with one field. The number of visible fields is saved with the workflow.

## Outputs

| Output | Type   | Description                              |
|--------|--------|------------------------------------------|
| `path` | STRING | The fields joined with `/`, blanks skipped. |

## Wiring

```
Path Builder ─▶ (filename_prefix) Save Video
             └▶ (filename_prefix) Save Latent
```

## Notes

- The separator is always `/`: ComfyUI's `filename_prefix` inputs use it for subfolders on every
  platform.
- Every field is trimmed of surrounding whitespace and slashes before joining, so `videos/` and
  `/h3_clip` give `videos/h3_clip`. A leading `/` on the first field is dropped too; ComfyUI does not
  accept absolute prefixes.
- The `+` / `-` buttons and the hidden fields are handled by the pack's frontend script in the
  classic node canvas. If the buttons do not appear, check the browser console for a failed load of
  `path_builder.js`.
