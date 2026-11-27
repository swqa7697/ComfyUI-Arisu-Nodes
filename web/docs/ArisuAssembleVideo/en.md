# Assemble Video

Choose saved takes, put them in order, check each join, and export the film. The node works on videos that are already
on disk, so it needs no wire from a sampler or from **Save Video Segment**, and it can live in a workflow of its own.

## Workflow

1. Set `project_prefix` to the project the takes were saved in, typed or linked from **Path Builder**.
2. Build the edit: add project takes, import a Director film, or add an existing video.
3. Replace takes, reorder, exclude, and preview joins until the edit is right. None of this runs a workflow or touches a file.
4. **Check Export** shows the frame count, the duration and what will happen to each track.
5. **Export** writes a new version. Each export is separate: `main_00001`, then `main_00002`, and so on.

## Inputs

| Parameter        | Type   | Description                                                                                                                                             |
|------------------|--------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `project_prefix` | STRING | The project directory under ComfyUI's output directory. Blank uses `arisu_video`. A linked value is read through **Path Builder** before any run.       |
| `export_name`    | STRING | The name of the export. `main` writes `<project>/exports/main_00001/main_00001.mp4`.                                                                    |
| `encoding`       | COMBO  | `inherit` copies the source video when every source allows it. `encode` always encodes the film once with `codec` and `crf`.                            |
| `codec`          | COMBO  | `h264`, `h265` or `av1`, used when the film's video is encoded.                                                                                         |
| `crf`            | INT    | Quality on the selected encoder's scale: 0–51 for H.264 and H.265, 0–63 for AV1. Suggested: 18, 20, 24.                                                 |

The edit list is stored with the workflow. It is not a connectable value.

## Outputs

| Output   | Type   | Description                                                             |
|----------|--------|-------------------------------------------------------------------------|
| `video`  | VIDEO  | The exported film.                                                      |
| `path`   | STRING | The film's path relative to the output directory.                       |
| `record` | STRING | The export record (`sequence.json`): sources, ranges and encoder used.  |

An ordinary Run writes no film and passes nothing downstream. Only **Export** produces these outputs.

## Building the Edit

- **Add Project Takes** shows a still and duration for each clip. Click a still to play the clip in a separate preview dialog. Close it or press Escape to return to the same place in the list. Search by segment description, number, filename or take ID.
  Director takes show the segment number and are grouped in film order. **Director choice** marks the take held by the open Director, and **In edit** marks footage already in the assembly.
  Each rerender has its own short take ID and, when recorded, a creation time. Multiple selected takes enter the edit in the displayed order.
  A standalone assembly uses the most recently rendered sequence for each film. Removed segments keep their footage and follow the active sequence.
  Older takes use available Director receipts or their saved render metadata to identify the segment. When neither identifies a segment, the still and short take ID identify the clip.
- **Import from Director** replaces the entire edit, including manually added videos, with the selected Director’s current rendered takes in film order.
  An empty list imports immediately. If the list contains any clips, choose **Replace Edit** to confirm or **Cancel** to keep your edit.
  Segments without a render are skipped. If the Director has no rendered takes, the existing edit stays in place.
  Import again after rendering or reordering segments to rebuild the list. **Undo** restores the previous edit in one step.
- **Add Existing Video** browses for any video under the output directory or a configured root, including videos
  saved before this node existed.

Each edit row shows a still, the segment number or filename, and the duration. A short ID distinguishes
Director takes. Rows also show when footage is trimmed, muted or unavailable. Files that are **Missing** or **Unusable** can be replaced with **Reselect**. Restoring a take to its
recorded location preserves its segment, predecessor and PCM soundtrack. Plain videos use their selected path.

## Editing

- Drag the handle, or focus it and press the arrow keys, to reorder. **Move Up** and **Move Down** are also reachable by keyboard.
- The dot excludes a row from the film without removing it. `×` removes it from the edit.
- `⇄` replaces the take at that position. Click a candidate’s thumbnail to preview it before choosing **Use**.
- Click a row to play it, choose its audio source, or, for a video without a take record, skip frames at its head.
  Use the head skip only for a file that still contains its continuation overlap; sound is cut at the same time.
- Tick several rows and use **Remove Selected**. Undo and redo work from the panel (`Ctrl+Z`, `Ctrl+Shift+Z`).

The totals line follows the included rows. Takes saved by **Save Video Segment** are used in full: their overlap was
already trimmed before saving.

## Joins

**Preview Join** loops the end of one take and the start of the next, with sound. A join is a direct cut unless you
change it.

- Colour signalling is compared first. If the two sides are tagged differently, fix the sources.
- **Experimental: match colour** is offered only when the incoming take is the recorded continuation of the outgoing
  one and a steady brightness or colour step exists. It previews a small correction that fades out over the first
  frames of the incoming take. Compare it with the direct cut, then apply it or keep the cut.
- **Click fade** auditions a very short fade at the two edges for an audible click.

A correction or fade belongs to one join. Replacing, excluding or moving either take, or trimming at the cut, returns
that join to a direct cut. A colour match makes the export encode the video once; the frame count and the position of
the sound do not change.

## Export Check and Export

**Check Export** reports the expected frames and duration, the destination, and one line per track:

- **Video: copy** when the sources share one encoding and whole takes are joined. This adds no compression loss.
- **Video: encode** for mixed codecs, a head trim, a colour match, differing sizes or rates, or `encoding` set to `encode`.
- **Audio** is rebuilt from the saved PCM onto one continuous timeline whenever takes with sound are joined, and
  encoded once. A silent take fills its exact time slot.

When a decision is yours, the check stops and offers it: choose a codec for mixed sources, confirm a common size,
frame rate or sample rate, switch a row to its embedded audio when its saved PCM is gone, or clear a colour match that
no longer fits. **Export** is available when nothing is open.

**Export** submits only this node to ComfyUI's queue, so it waits behind running generations and does not start any.
Edits made after you press it apply to the next export. **Stop** cancels the job; an incomplete film is never
published. If the page reloads during an export, the panel finds the same job again.

Each export directory holds the film and its `sequence.json`. Earlier versions and all sources are left as they are.

## Removing and Deleting

Use **Remove Selected** to remove rows from the edit and keep their files on disk.

To delete videos from disk, tick their rows and click **Delete Files…**. The confirmation shows the files currently
at those locations, with their root and relative path. Review the list and confirm once.

- Deleting a **Director take** removes its entire `<project>/director/<UUID>/` or `arisu_director/<UUID>/`
  folder, including the latent, other clips and all subfolders. Selecting two clips from that take lists the folder once.
- Deleting an **ordinary project take** removes the selected video and its dedicated `<video stem>.arisu/` folder,
  including the take record, audio and anything else stored there. Other takes in the shared `videos/` folder stay in place.
- Deleting a **standalone video or exported film** removes the selected video file. Its parent folder stays in place.

Deletion applies to the selected files in ComfyUI's `input`, `output` and configured media directories.
If an export is reading a file, deletion waits until the export finishes. Undo can restore the edit rows only.

## Imported and Copied Workflows

Reopening a saved workflow keeps the edit and checks every file again. An imported workflow, or a pasted or
duplicated node, keeps the order and the choices but not the file locations. **Rebind from Project** finds the takes
again by their IDs inside this node's project; a plain video file is reselected by hand.

## Notes

- An edit holds up to 512 rows; one export includes up to 100.
- A take deletion can review up to 4,096 filesystem entries per take folder, including directories.
- Videos are read from ComfyUI's input and output directories and the roots an administrator configured. Exports are
  written only under the output directory.
- Without a system `ffmpeg`, exports use the bundled PyAV libraries and always encode.
- Frame interpolation and upscaling are separate postproduction steps.
