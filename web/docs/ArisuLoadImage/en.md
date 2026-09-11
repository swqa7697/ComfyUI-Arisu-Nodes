# Load Image (Browse)

Load an image beneath a server-configured directory using the **browse** button, and optionally
crop it with **crop…**. The node returns one `image` output; nothing is uploaded or copied.

## Why

**Load Image** lists only the top level of the input directory, and the one way to use another file
is an upload that copies it into `input/`. Keeping images where they already live means typing
paths by hand in a text node, without seeing what is being loaded. This node opens a directory
browser with thumbnails, remembers the picked path, and shows the image on the node.

## Inputs

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | hidden STRING | Image path relative to the selected root, such as `refs/a.png`. Stored by Browse; unavailable for typing or wiring in the UI. |
| `root` | hidden COMBO | Directory ID stored by Browse; `input` by default. Select `input`, `output` or a configured external root inside the browser. |
| `browse` | button | Open the directory browser at the selected file or root. |
| `crop…` | button | Crop the image in a dialog. The crop is saved with the workflow. |

A read-only row above **browse** shows the selected filename, or “No image selected”. Long names
are shortened with an ellipsis; hover to see the full filename.

The browser's tree contains only configured roots. Click a folder to enter it, its chevron to
expand it, and **collapse** to fold everything but the current chain. The read-only path display
shows the current directory relative to the selected root; **up** stops at that root. **input dir** and **output dir** switch roots.
The filter narrows image names in the current directory. Click an image to select both its root
and relative path. Nothing is uploaded or copied.

**Saved** holds pinned `{root, path}` locations in your ComfyUI user settings. **+ save** pins a
directory (including a root); its row opens it and **✕** forgets it. Bookmarks do not grant access.
Legacy absolute bookmarks are not imported, and old absolute workflow paths must be reselected.
Reopening a saved ComfyUI workflow, refreshing it, switching existing tabs, and undo/redo within
that workflow preserve selections and crops. Imported JSON/PNG/API-format workflows, pasted or
duplicated nodes, workflow insertion and workflow duplication clear the image and crop and reset
the root to `input`; reselect with **browse**. Matching imported IDs or filenames do not preserve
selections, and unknown restoration contexts also reset. Saved bookmarks remain available.
When a workflow restores a wired `path` or `root`, the node disconnects those inputs, clears the selected path and
crop, and resets the root to `input`; reselect with **browse**. All selection resets are silent. Navigating directories
alone does not change the selected image; click an image to select it.

The machine owner can enable external disks or shares in `user/__arisu_nodes/config.arisu.jsonc`
under ComfyUI's configured user directory, then restart ComfyUI. On first startup the pack creates
a commented template with empty roots, without overwriting any existing file:

```jsonc
{
  // Shared image libraries; use existing absolute directories.
  "roots": {"photos": "/data/photos", "references": "/mnt/library/references"}
}
```

Both `//` and `/* ... */` comments are supported; trailing commas are not. Ordinary JSON also works.
The old pack-local `arisu_paths.json` is ignored. Manually copy its root entries into the new
template and restart; there is no automatic migration.

Root IDs use lowercase letters, digits, `_` and `-`, beginning with a letter (maximum 64 characters).
`input` and `output` are reserved. Values must be existing absolute directories, never filesystem
roots. On Windows use paths such as `D:/Photos`. A missing file becomes an empty template;
creation/read errors, invalid configuration and symlinked configuration destinations disable
external roots and log an error. The file survives pack reinstalls; keep a backup. Only configure
image directories you intend clients of this ComfyUI server to access. The protected system-user
directory is excluded from ComfyUI's public user-data API; workflows and browser settings cannot
edit this allowlist.

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
| `image` | IMAGE | The image, cropped when a crop is set, as `[1, H, W, 3]`. |

## Wiring

```
Load Image (Browse) ─▶ (first_frame) MiniMax H3 Hybrid to Video
                    └▶ (image) any IMAGE input
```

## Notes

- Paths are resolved beneath the selected root, including symlink targets. Absolute paths, home
  expansion, `..` components, drive/UNC paths, and escaping symlinks are rejected in both the
  routes and node execution. Hidden entries are omitted from the browser.
- Supported files are PNG, JPEG, WebP, BMP and AVIF, the raster types browsers decode natively;
  the extension decides, in any letter case. TIFF, GIF, SVG, document formats and anything else are
  neither listed nor loaded. Static images only: Browse does not list animated PNG, WebP or AVIF
  files; a selection restored from a workflow loads its first frame.
- The node preview and the crop dialog receive the original file, exactly as Load Image's previews
  do, never a resized or re-encoded copy. A crop is previewed as a WebP rendering at the crop's own
  size; Browse thumbnails are the only resized images.
- Editing the source file changes the node's cache key through its size and modification time.
- The hidden `crop` input is `left,top,width,height` in pixels after EXIF rotation. It applies to
  the image. A crop reaching beyond an edge is clipped; one wholly outside the image is refused.
  Picking a different file or changing roots clears the crop.
- Browse-only selection is a UI restriction. API and workflow JSON still carry root-relative
  values, which the server validates at execution, validation and fingerprinting. Hidden controls
  and socket restrictions do not replace filesystem containment checks.
- `/arisu/browse` and `/arisu/view` accept a root ID and relative path. Listings and errors do not
  reveal physical root paths. Missing files return 404; invalid paths return 400; unsupported
  image contents return 415. Unexpected errors stay in the server log.
- In the classic canvas, the node shows its preview. In the Vue renderer ("Nodes 2.0"), the buttons
  and dialogs work but the node shows no preview. Check the browser console if buttons are missing.
- The node has no mask output or **Open in MaskEditor** menu entry. To paint a mask, use the stock
  **Load Image** node with a copy under `input/`.
