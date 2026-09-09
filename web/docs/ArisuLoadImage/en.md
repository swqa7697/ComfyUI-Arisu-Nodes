# Load Image (Browse)

Load one image from any path on the machine running ComfyUI, picked with the **browse** button or
typed. Same file types as **Load Image**, one `image` output; nothing is uploaded or copied.

## Why

**Load Image** lists only the top level of the input directory, and the one way to use another file
is an upload that copies it into `input/`. Keeping images where they already live means typing
paths by hand in a text node, without seeing what is being loaded. This node opens a directory
browser with thumbnails, remembers the picked path, and shows the image on the node.

## Inputs

| Parameter | Type   | Description                                                                                                                                                                                                                   |
|-----------|--------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `path`    | STRING | The image file. Three forms: an absolute path (`/data/refs/a.png`), a `~` path (`~/Pictures/a.png`), or a path relative to ComfyUI's input directory (`sub/a.png`). The browse button fills it in; typing works too. |
| `browse`  | button | Open the directory browser. It starts where `path` points, or in the input directory.                                                                                                                                       |

The browser has a path field (type a directory and press Enter), an **up** button, an **input dir**
button, and a filter box that narrows folders and files by any part of their name. Click a folder
to enter it and an image to pick it.

## Outputs

| Output  | Type  | Description                                                                              |
|---------|-------|------------------------------------------------------------------------------------------|
| `image` | IMAGE | The image as `[1, H, W, 3]`; every frame of an animated file becomes one image of the batch. |

## Wiring

```
Load Image (Browse) ─▶ (first_frame) MiniMax H3 Hybrid to Video
                    └▶ (image) any IMAGE input
```

## Notes

- Accepted files are what **Load Image** accepts: any name whose type the interpreter's MIME table
  calls an image (PNG, JPEG, WebP, GIF, BMP, TIFF, and so on). Animated files load as a batch; frames
  of a different size than the first are skipped.
- The run reads the file in place, so editing it on disk and queueing again loads the new pixels;
  the node's cache key follows the file's size and modification time.
- A missing file or a non-image type is reported when the prompt is validated, before anything runs.
  When `path` is fed by a link, the linked value is used and the browse button only previews.
- The browser and the preview are served by two routes the pack registers on ComfyUI's server,
  `/arisu/browse` (folder and image names of a directory) and `/arisu/view` (an image file or a
  thumbnail of it). They can reach any directory the ComfyUI process can read, which is the same
  trust ComfyUI already extends to whoever can reach its server; hidden entries are skipped and
  only image-typed files are served.
- The browse button and the on-node preview are added by the pack's frontend script in the classic
  node canvas. In the Vue node renderer ("Nodes 2.0") the button and the browser work but the node
  shows no preview. If the button is missing, check the browser console for a failed load of
  `load_image.js`.
- The node has no `mask` output and its right-click menu has no **Open in MaskEditor** entry, although
  ComfyUI adds one to every node that shows an image: the editor reads and writes through `input/` and
  an `image` widget, neither of which fits a path read in place. To paint or load a mask, use
  **Load Image** on a copy under `input/`.
