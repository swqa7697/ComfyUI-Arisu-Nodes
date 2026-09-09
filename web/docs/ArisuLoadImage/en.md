# Load Image (Browse)

Load one image from any path on the machine running ComfyUI, picked with the **browse** button or
typed, and cropped with the **crop…** button if you like. Same file types as **Load Image**, one
`image` output; nothing is uploaded or copied.

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
| `crop…`   | button | Open the crop dialog on the picked file. The crop is kept with the workflow but shown only here and in the preview.                                                                                                        |

The browser's left pane is a directory tree like a system file explorer's: its roots are your home
directory and the mounted disks (USB drives, network shares), with **input dir** and **output dir**
shortcuts above it. The tree opens expanded down to the current directory; click a folder to enter it,
its chevron to expand it in place, and **collapse** to fold everything but the path you are in. The
filesystem root and other users' homes are not listed, but a path typed into the path field (press
Enter) opens anywhere and the tree grows a branch for it. The filter box narrows the images of the
current directory by any part of their name; folders are never filtered. Click an image to pick it.

The crop dialog shows the picked file with a box over it. Drag on the image to draw a box, drag the
box to move it, and pull its handles to resize it; the readout gives the box in pixels. Pick or type
an aspect ratio (`16:9`, `1:1`, or any `width:height`) to fit the box to it and hold it while you
drag; leave the field blank for a free box. **reset** is the whole image, which is no crop at all;
**apply** stores the box and the node previews the cropped image at the cropped size. Nothing is
resized or padded, and picking another file drops the crop.

## Outputs

| Output  | Type  | Description                                                                              |
|---------|-------|------------------------------------------------------------------------------------------|
| `image` | IMAGE | The image, cropped when a crop is set, as `[1, H, W, 3]`; every frame of an animated file becomes one image of the batch. |

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
- The crop is a hidden `crop` input, `left,top,width,height` in pixels of the upright image (after
  the EXIF rotation, the way the preview shows it), blank for the whole image; it is saved with the
  workflow and appears in the prompt JSON. It is cut from every frame after decoding. A box that
  reaches past the image, say after the file was replaced by a smaller one, is cut to the image; a
  box wholly outside it is a run error. The dialog needs the browser to decode the file itself to
  know its size, so a format it cannot show, such as TIFF, cannot be cropped.
- A missing file or a non-image type is reported when the prompt is validated, before anything runs.
  When `path` is fed by a link, the linked value is used and the browse button only previews.
- The browser and the preview are served by two routes the pack registers on ComfyUI's server,
  `/arisu/browse` (folder and image names of a directory, with the tree roots and the chain to it)
  and `/arisu/view` (an image file, or a thumbnail or crop of it). They can reach any directory the ComfyUI
  process can read, which is the same trust ComfyUI already extends to whoever can reach its server;
  hidden entries are skipped and only image-typed files are served. Mounted disks come from the
  mount table (Linux), `/Volumes` (macOS) or the drive letters (Windows); nothing touches a mount
  until you open it.
- The size shown under the node's preview is the file's own: the preview loads the file itself and
  falls back to a thumbnail only for a format the browser cannot decode, such as TIFF.
- The buttons and the on-node preview are added by the pack's frontend script in the classic node
  canvas. In the Vue node renderer ("Nodes 2.0") the buttons and their dialogs work but the node
  shows no preview. If the buttons are missing, check the browser console for a failed load of
  `load_image.js`.
- The node has no `mask` output and its right-click menu has no **Open in MaskEditor** entry, although
  ComfyUI adds one to every node that shows an image: the editor reads and writes through `input/` and
  an `image` widget, neither of which fits a path read in place. To paint or load a mask, use
  **Load Image** on a copy under `input/`.
