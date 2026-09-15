# Workbench MCP

This job is one-shot. The Workbench MCP is the only user input. Do not ask questions. Do not read `/inputs` as files. Do not invent tools. Follow this file for every skill; prompt grammar stays in `SKILL.md`.

## Tools

1. `get_context` — no arguments. Returns the job JSON below.
2. `read_image` — `{"asset_id": "<id>"}`. Raster stills only (PNG, JPEG, WebP). Use it for keyframes, reference images, video stills, and motion stills listed in the JSON.

There is no audio or video tool. Staged WebM and WAV files are not readable and must not be cited as something you opened.

## JSON fields

- `duration_seconds`, `frame_count`, `aspect_ratio`: from Video Settings. If null, default 6 seconds and 16:9.
- `trigger_words`, `requirements`: LoRA tokens and the user's brief (Chinese or English).
- `motion.present`: the only continuation switch.
  - False: ignore stills and notes. No airlock. Do not mention Motion Context in the prompt.
  - True: read `motion-context.md`. `read_image` every `motion.stills[].asset_id` in order. `motion.notes` may be empty; infer from stills. `sample_duration_seconds` is the clock for `At MM:SS.mmm` (Video Settings length, including the pinned head). `delivered_duration_seconds` is after Trim. Do not add `context_length` on top of Video Settings length.
- `keyframes.first` / `keyframes.last`: `{asset_id, name, resource_id}` or null. These are locks, never members of `references`.
- `references[]`: every active Studio card the local model will receive.
  - image: `inspect.type` is `image` — `read_image` on `asset_ids[0]` (already cropped).
  - video: `inspect.type` is `stills` — `read_image` each `frames[].asset_id` in order; `timestamp` is seconds on the selected clip. Reconstruct motion from stills; do not claim to have watched a file.
  - audio: `inspect.type` is `none` — use `note`, `selected_clip`, and `requirements` only; never claim to have listened.
  - video `include_audio`: the local model also receives that soundtrack.
- `assets[]`: authorization table for `read_image`. Ignore non-image rows.

Motion stills are not references and not a first-frame lock. Do not invent `<Picture N>`, `<Video N>`, `<Audio N>`, or `<Subject N>` for the pinned head.

## Output

The entire assistant message must be exactly one nonempty fenced block whose info string is `markdown`. No commentary, reasoning, or questions outside the fence.
