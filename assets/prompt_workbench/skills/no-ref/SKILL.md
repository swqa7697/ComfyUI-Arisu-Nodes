---
name: no-ref
description: Write MiniMax H3 T2VA, I2VA, FL2VA, or L2VA prompts from Workbench MCP context, including optional Motion Context continuation. Return exactly one markdown fence and nothing else.
---

# MiniMax H3 T2VA / FL2VA Prompt

Act as a professional film director. From Workbench MCP context, infer intent, design a complete audiovisual storyboard that fills the requested duration, then rewrite into the official MiniMax H3 base prompt structure.

Read `references/mcp.md` first and follow it for tools, fields, and output shape.

## When to Use

This skill writes T2VA / I2VA / FL2VA / L2VA only. Keep that field order even if extra Studio cards appear in `references`. Extra images, video stills, and audio notes may inform look, motion, and sound; do not emit Ref2VA sections or `<Video N>` / `<Audio N>` / `<Subject N>` labels.

## Core Rules

1. **Prompt is a timeline, not a description.** Every second must have concrete action, camera, and sound. Empty time produces drift or padding.
2. **Exact field order and names** (never invent new fields):
   - Optional alignment instruction (I2VA / FL2VA / L2VA only)
   - `integrated_multimodal_description:`
   - `overall_soundscape:`
   - `non_diegetic_music:`
3. Read `references/base-en.txt` and follow its shot notation, camera vocabulary, speaker IDs, `<d>` dialogue format, and examples exactly.
4. **Character count hard limit ≤ 7000.** Soft target: keep tight; when keyframe images carry visual load the prompt can be shorter.
5. **Background music off by default.** Set `non_diegetic_music: N/A` unless `requirements` explicitly requests score, BGM, or music. Diegetic music belongs inside the multimodal description.
6. Output the finished prompt inside the single markdown fence required by `mcp.md`.

## Motion Context gate

Read `references/motion-context.md` only when `motion.present` is true.

- **Off (default).** Follow the rest of this skill unchanged. Keep I2VA / FL2VA / L2VA alignment lines. Do not insert an airlock.
- **On.** Apply `motion-context.md` (union rule, airlock, sample-clock timestamps, first frame absent, continue audio). Use the Base section there.

## Infer mode from keyframes

Apply the Motion Context gate first. If On, `keyframes.first` is absent.

- no `keyframes.first` or `last` → T2VA
- first only → I2VA
- first and last → FL2VA
- last only → L2VA

Duration and aspect come from MCP; if null, use 6 seconds and 16:9.

## Workflow

1. **Parse mode and constraints**
   - Call `get_context`. Apply the Motion Context gate. If Off, ignore motion fields. If On, `keyframes.first` is absent — do not inspect that image.
   - Infer mode from remaining keyframes. Read mounted keyframe images that are still in use, then any useful reference images or video stills.
   - On a continuation clip the previous tail is a Shot 1 description aid, not a new first-frame picture.

2. **Director pass**
   - If `requirements` is a one-liner or otherwise thin, invent the complete clip story (setting, blocking, narrative arc, emotional beats, and physical actions) that fills the full sample duration, consistent with the sentence, remaining keyframes, and extra images.
   - If the user already specified beats, dialogue, positions, or a shot list, keep that story. Expand it onto the clock; do not replace it with a different plot.
   - Break into 1–4 shots with precise cut times that land inside that length.
   - Decide camera language using the official motion-type + amplitude + speed vocabulary.
   - Design diegetic sound timeline and any spoken lines.
   - If Motion Context is On, Shot 1 continues the previous closing state, including unfinished motion and sound at the same speed. New plot and dialogue start after the airlock. Write times on the sample clock.

3. **Write the three core fields**
   - Start `[Shot 1]` with style + composition (derive style from a still-active keyframe when present, never a dropped first frame; otherwise from `requirements`). Common anchors: `Live-action, cinematic`, `2D-animated`, `3D CG`, etc.
   - Later shots: `[Shot N] At MM:SS.mmm, the camera cuts to...`
   - Insert speaker IDs `(S1)`, dialogue as `<d>[Language] exact words</d>`.
   - Keep every visual and audio detail synchronized to the timeline.
   - `overall_soundscape`: 1–4 sentences of continuous ambient + physical + non-verbal human sound. No dialogue or non-diegetic music here. Audio-reference notes may color this description; do not claim to have listened.
   - `non_diegetic_music`: N/A or a concrete instrumental description (tempo, instruments, dynamics only).

4. **Keyframe alignment instructions** (must be the very first line when required)
   - I2VA:
     ```
     For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
     ```
   - FL2VA:
     ```
     How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
     ```
   - L2VA:
     ```
     How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
     ```
   Follow with one blank line, then the three core fields.
   Write alignment for the inferred mode only. If Motion Context is On, that is T2VA (no alignment) or L2VA (last-frame line at the sample-clock end) — never an I2VA / FL2VA first-frame claim.

5. **Negative / quality constraints**
   - Add quality prohibitions only when needed (no subtitles, no watermarks, no text unless spelled out, no soft dissolves unless requested, keep live-action texture). Prefer positive constraints.

6. **Final output**
   - Emit only the complete prompt text inside the markdown fence from `mcp.md`.
   - Preserve user-supplied dialogue, lyrics, or on-screen text verbatim in the original language.

## Practical Optimizations

- Always fill the entire duration with observable change. A static hold still needs micro-motion (breathing, fabric, light, camera drift) or the model will invent filler.
- Prefer hard cuts over dissolves unless the user asks.
- When a still-active keyframe is supplied, never re-describe its static appearance at length; anchor once then move forward.
- For FL2VA (Motion Context Off) favor a single continuous shot so the model can interpolate cleanly from the starting pose to the last-frame pose. If Motion Context is On, there is no first-frame pose; open from the pinned closing state and land on last if present.
- Spell every readable on-screen string in double quotes; add “do not misspell, do not add extra text”.
- Camera motion is written as natural English inside the shot, never as trailing tags.
- **LoRA trigger words**: when `trigger_words` is nonempty, place it at the very start of `integrated_multimodal_description` (right after the colon or as the first tokens of `[Shot 1]`).

## Reference

- MCP input and output: `references/mcp.md`
- Full official rules and examples: `references/base-en.txt`
- Distilled production tips: `references/practical-tips.md`
- Clip-chaining prompt rules (opt-in only): `references/motion-context.md`
