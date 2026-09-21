# H3 Motion Context — Prompt Rules

ComfyUI pack: `NikoDemon80/ComfyUI-H3-Motion-Context` (v0.6.x).
These rules change the **written prompt only**. They do not invent new official fields.

Read this file only when `get_context` has `motion.present` true. Do not infer continuation from casual wording in `requirements`.

## Gate (mandatory)

**On** only when `motion.present` is true.

**Off** when it is false. Write the prompt exactly as the parent skill already specifies.

- First clip of a chain (Load 0): `present` is false.
- This job is one-shot. Never ask a question. If `motion.notes` is empty, infer unfinished motion and sound from `motion.stills`.
- When Off: no airlock, no dropped first-frame alignment, no rewritten opening to match a previous tail, no Motion Context mention in the emitted prompt.

## What the node does (prompt-relevant)

The node pins the previous clip's video+audio latent tail at the **head** of this clip and re-injects it every sampling step. The model renders **prompt ∪ pinned frames**, not replacement.

- Contradictions become unions (extra people, extra props, stacked compositions).
- `first_frame` anchors are dropped. `last_frame` anchors survive.
- Pinned audio is a keyframe on this clip's timeline, ending at the join and reaching backward. It is not a Ref2VA `<Audio N>` block.
- Delivered file is `context_length` frames shorter than the sampled clip (`head` + Trim). At 22 frames that is ~0.92 s.
- Prompt timestamps follow the **sampled** clock (includes the pinned head). After Trim the file clock starts `context_length` frames later.

Use `motion.context_length` and `motion.audio_context_length` from MCP. Do not invent other values.

## First frame is absent

When On, treat `keyframes.first` as missing even if MCP lists it and the image is attached. The pin owns 0.00.

- Do not inspect that image.
- Infer / route mode as if `first` were null: I2VA → T2VA, FL2VA → L2VA, Hybrid with only first → Ref2VA. Last-only stays L2VA / Hybrid-last.
- Drop first-frame alignment and lock language.
- Shot 1 starts from the pinned closing state, not from that picture's pose or composition.
- `keyframes.last` is unchanged.

## Sample clock vs delivered clock

Video Settings length is already the sample clock.

- `motion.sample_duration_seconds` is the clock you write `At MM:SS.mmm` against. Fill that duration.
- `motion.delivered_duration_seconds` is after Trim (`sample` minus `context_length` / 24).
- Last-frame alignment times use the **sample** end, not the delivered end.
- A beat the user wants at delivered 4.00 s must be written at `4.00 + context_length/24` (22 frames → 4.92 s).

State neither clock math nor node names in the emitted prompt. Only the timestamps change.

## Closing state (stills + notes)

The previous tail is a description aid for Shot 1, not a new first-frame / `<Picture N>` / `<Audio N>` / Hybrid `first_frame`.

`motion.stills` are ordered VAE stills of the pinned tail (2, 4, 6 or 8 for windows 5, 22, 39 or 56), including both endpoints. Inspect the attached image for each `asset_id`. `motion.notes` covers unfinished motion direction, whether the camera is still moving, and what sound or line was in progress.

Use stills and notes together. If notes are empty, infer from stills only.

## Airlock (when present)

Do not ask for continuation and change at the same instant.

1. `[Shot 1]` (no timestamp) restates the **exact closing state**: same people, wardrobe, props-in-hand, stance, lens height, framing, unfinished motion vector, and continuing sound. No new characters. No dialogue.
2. Keep that framing about **2.0 s on the sample clock** (about 1.5 s is the minimum past a 22-frame pin). Then cut or move.
3. Put the first new setup, new beat, and first spoken line **after** the airlock. Unfinished motion keeps its current speed and contact through this window — do not pause, idle, or slow it to wait for the join.
4. Add life on top of that vector (breath, weight shift, eyeline, fabric, inertia). Micro-motion is extra, not a replacement for the unfinished motion. A frozen or slowed actor reads as a stalled file.
5. After Trim the audience sees a shorter matched head (`2.0 − C/fps`). If the user wants a full 2 s matched head **in the file**, extend the sample-side airlock to `2.0 + C/fps`.

## Union rule

The pinned head is not a suggestion. Shot 1 must not describe a different headcount, staging, costume, or framing. Negative constraints such as "no extra people" do not delete whoever is already in the pin, and they do not delete whoever the prompt newly introduces. Make the two sets equal.

## Audio on continuation clips

- `overall_soundscape` continues the previous tail; it does not restart a new bed at 0.00.
- First spoken line after the airlock.
- Do not start a new `non_diegetic_music` bed that would stack on a pinned score. Keep `N/A` unless the user wants a new score **after** the airlock and describes a diegetic break.
- Do not cite the previous clip's generated soundtrack as a reference audio asset.

## Mode notes

Apply only the section that matches this skill's prompt format.

### Base — T2VA / I2VA / FL2VA / L2VA

- After first is absent, I2VA jobs are T2VA (no 0.00 Picture 1 line). FL2VA jobs are L2VA: keep the last-frame alignment sentence; set its time to the **sample** end.
- Do not treat motion stills as I2VA Picture 1.

### Ref2VA

- Keep the official six sections and the existing label/retention rules.
- Prefix `summary` with a task type that includes continuation, e.g. `[video continuation + reference generation]`.
- Do not add a standalone subject for the pinned head.
- Identity/motion/audio references still condition the **whole** clip. You cannot write "this reference starts at 00:02". Put new action after the airlock instead.
- Do not attach the previous generated audio as `<Audio N>`.

### Hybrid

- After first is absent, keep `keyframes.last` if an end lock is still wanted. Do not move it into `references`.
- Do not emit `The first frame is fully locked at 0.00s ...`. Optionally state that the opening continues the previous tail.
- Last-frame lock line, if any, uses the sample-clock end time.
- Decision tree for identity/style images is unchanged. The previous tail is not a Hybrid keyframe image and not a `<Picture N>`.

## Output still equals one prompt block

Same official fields as the parent skill. No extra top-level keys. The fence language is in `mcp.md`.
