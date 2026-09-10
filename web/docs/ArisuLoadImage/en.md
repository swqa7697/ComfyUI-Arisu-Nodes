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

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | STRING | Image path relative to the selected root, such as `refs/a.png`. Browse fills it in; typing or linking works too. |
| `root` | COMBO | A server-configured directory ID; `input` by default. Includes `output` and any administrator-configured external roots. |
| `browse` | button | Open the directory browser at the selected file or root. |
| `crop…` | button | Crop the image in a dialog. The crop is saved with the workflow. |

The browser's tree contains only configured roots. Click a folder to enter it, its chevron to
expand it, and **collapse** to fold everything but the current chain. The path field is relative
to the selected root; **up** stops at that root. **input dir** and **output dir** switch roots.
The filter narrows image names in the current directory. Click an image to select both its root
and relative path. Nothing is uploaded or copied.

**Saved** holds pinned `{root, path}` locations in your ComfyUI user settings. **+ save** pins a
directory (including a root); its row opens it and **✕** forgets it. Bookmarks do not grant access.
Legacy absolute bookmarks are not imported, and old absolute workflow paths must be reselected.

The machine owner can enable external disks or shares with `arisu_paths.json` beside the installed
pack's root `__init__.py`, then restart ComfyUI:

```json
{"roots": {"photos": "/data/photos", "references": "/mnt/library/references"}}
```

Root IDs use lowercase letters, digits, `_` and `-`, beginning with a letter (maximum 64 characters).
`input` and `output` are reserved. Values must be existing absolute directories, never filesystem
roots. On Windows use paths such as `D:/Photos`. A missing file leaves only built-in roots enabled;
an invalid file disables all external roots and logs a configuration error. This local file is not
included in releases; keep a backup across reinstalls. Only configure image directories you intend
clients of this ComfyUI server to access. No browser route or workflow can edit this allowlist.

The crop dialog shows the picked file with a box over it. Drag on the image to draw a box, drag the
box to move it, and pull its handles to resize it; the readout gives the box in pixels. The **ratio**
menu sets an aspect ratio: a preset (`1:1`, `3:2`, `2:3`, `4:3`, `3:4`, `16:9`, `9:16`), or
`custom`, which shows a width and a height field, makes the box the largest one of that ratio in the
image and holds it while you drag; `free` leaves the box as it is and lets it take any shape. The
choice is remembered for the picked image and starts over as `free` on another one. **reset** is the
whole image at `free`, which is no crop at all; **apply** stores the box and the node previews the
cropped image at the cropped size. Nothing is resized or padded, and picking another file drops the
crop.

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

- Paths are resolved beneath the selected root, including symlink targets. Absolute paths, home
  expansion, `..` components, drive/UNC paths, and escaping symlinks are rejected in both the
  routes and node execution. Hidden entries are omitted from the browser.
- Supported files are raster image types Pillow can decode (PNG, JPEG, WebP, GIF, TIFF, and others).
  SVG, document formats such as EPS/WMF (even renamed), and undecodable content are refused. An animated file still loads all matching-size frames
  into the node's output; browser previews show its first frame.
- Full-size previews and the crop dialog receive decoded PNG pixels at the original upright size;
  thumbnails receive bounded WebP. This also allows cropping TIFF images. Source metadata and
  active document content are never served through the view route.
- Editing the source file changes the node's cache key through its size and modification time.
- The hidden `crop` input is `left,top,width,height` in pixels after EXIF rotation. It applies to
  every frame. A crop reaching beyond an edge is clipped; one wholly outside the image is refused.
  Picking a different file or changing roots clears the crop.
- When `path` or `root` is linked, execution uses its linked value. Browse only selects the widget
  values; the same containment checks apply at execution even when pre-run validation has no value.
- `/arisu/browse` and `/arisu/view` accept a root ID and relative path. Listings and errors do not
  reveal physical root paths. Missing files return 404; invalid paths return 400; unsupported
  image contents return 415. Unexpected errors stay in the server log.
- In the classic canvas, the node shows its preview. In the Vue renderer ("Nodes 2.0"), the buttons
  and dialogs work but the node shows no preview. Check the browser console if buttons are missing.
- The node has no mask output or **Open in MaskEditor** menu entry. To paint a mask, use the stock
  **Load Image** node with a copy under `input/`.
