---
name: with-ref
description: Write MiniMax H3 Ref2VA or Hybrid prompts from Workbench MCP context when keyframes and/or mixed image, video, or audio references are present, including optional Motion Context continuation. Return exactly one markdown fence and nothing else.
---

# MiniMax H3 Ref2VA / Hybrid Prompt

Act as a professional film director. From Workbench MCP context, infer intent, design a complete audiovisual storyboard that fills the requested duration, then rewrite into the official MiniMax H3 six-section Ref2VA format. Apply Hybrid keyframe rules when first/last frames are true locks.

Read `references/mcp.md` first and follow it for tools, fields, and output shape.

## When to Use

This skill writes Ref2VA or Hybrid only. If MCP has no references and no keyframes, still write the six-section format from `requirements`. Do not switch prompt grammar.

### Mode routing

Apply the Motion Context gate first. If On, `keyframes.first` is absent.

- **Hybrid** when `keyframes.first` or `keyframes.last` is set (plus any `references`).
- **Ref2VA** when mixed references are used without a keyframe lock.
- Do not invent Hybrid keyframe language on a pure Ref2VA job.

Duration typically 5–15 s. If MCP duration/aspect are null, use 6 seconds and 16:9.

## Core Rules

1. **Exact six-section order and field names** (never reorder or invent top-level fields):
   ```
   subject_definitions:
   summary:
   retention_analysis:
   detailed_description:
   overall_soundscape:
   non_diegetic_music:
   ```
2. Read `references/ref-en.txt` (labels, retention, examples) and `references/base-en.txt` (shot / camera / dialogue / alignment vocabulary). Follow them exactly.
3. **Hybrid keyframe handling** (Hybrid only):
   - Remaining `keyframes.first` / `keyframes.last` after the Motion Context gate are true keyframes. Do not add them to the ordinary reference list (`ref_image` / standalone `<Picture N>`).
   - Declare their role in `summary` and `retention_analysis`.
   - Optionally place a short base-style alignment instruction as the very first line before the six sections when a first-frame lock remains (Motion Context Off).
4. **Reference list is not 1:1 with files.** Apply the decision tree below. Character / identity / costume / style / object images are cited inline inside `<Subject N>` and do not get an independent `<Picture N>` item. Standalone `<Picture N>` only when that image is itself a frame, composition, or storyboard anchor.
5. **Character count hard limit ≤ 7000.** Soft target for `detailed_description`: 350–500 English words for generation tasks.
6. **Background music off by default.** Set `non_diegetic_music: N/A` unless `requirements` explicitly requests score or BGM. Diegetic music stays inside `detailed_description`.
7. Output the finished prompt inside the single markdown fence required by `mcp.md`.

## Motion Context gate

Read `references/motion-context.md` only when `motion.present` is true.

- **Off (default).** Follow the rest of this skill unchanged. Keep first-frame / last-frame lock language on Hybrid jobs. Do not insert an airlock.
- **On.** Apply `motion-context.md`. Prefix `summary` with a task type that includes `video continuation`. Do not add a standalone subject for the pinned head. The pinned head owns 0.00 — treat `keyframes.first` as absent. `keyframes.last` may stay.

## Reference-list decision tree (mandatory)

`subject_definitions` is one line per item that must be tracked separately later, not one line per uploaded file. Official rule (`references/ref-en.txt` §2 / §2.2): if `<Picture N>` or `<Video N>` only identifies the source of another item and will not be analyzed on its own, cite it inline and do not add a separate line.

Never dump-all (standalone picture line for every asset) and never strip-all (subject line with no source keyword).

| Asset role in the target video | Standalone line? | How the source keyword appears |
| --- | --- | --- |
| Character / person / animal identity, face, body, costume | No `<Picture N>` line | Inline: `<Subject N> is the woman in <Picture M>, with ...` |
| Object / prop / product identity | No `<Picture N>` line | Inline inside the matching `<Subject N>` |
| Scene / environment / location look | No `<Picture N>` line | Inline: `<Subject N> is the café interior in <Picture M>, featuring ...` |
| Style / look / lighting recipe (not a frame lock) | No `<Picture N>` line | Inline inside the style or scene `<Subject N>` |
| Concrete first/last/mid frame or composition anchor | Yes `<Picture N>` line | Standalone + later shot phrasing |
| Storyboard / shot-planning image | Yes `<Picture N>` line | Standalone |
| Hybrid `first` / `last` keyframe | Never a `<Picture N>` line | Named in summary / retention as the keyframe |
| Video used only as a person's look, action, or effect | No `<Video N>` line | Inline inside `<Subject N>` |
| Video used as edit source, continuation source, or whole-clip structure | Yes `<Video N>` line | Standalone `<Video N>` + extracted subjects as `<Subject N>` |
| Audio copied or referenced | Yes `<Audio N>` line | Standalone; bind speaker with `<Subject N> (Sx)` when it maps |

Default for a typical character reference photo: inline citation, no independent picture item.

Correct character-photo line:

```
<Subject 1> is the young woman in <Picture 1>, with long dark hair, a blue cardigan, and a thin silver necklace.
```

Wrong dump-all: extra `<Picture 1> is the reference image of the woman.`
Wrong strip-all: `<Subject 1> is the young woman with long dark hair...` and no `<Picture 1>`.

List every `references[]` row the local model will receive, including pure video and audio. Video is inspected only as stills; audio is notes only. Still assign `<Video N>` / `<Audio N>` when the decision tree requires a label, because those files reach the local model.

### Numbering and later sections

- Number `<Picture N>` / `<Video N>` / `<Audio N>` in the order the source assets are used as citations, even when they have no standalone line.
- `retention_analysis` gets one line per standalone label defined in `subject_definitions` (plus the Hybrid keyframe lock line). Do not add retention rows for pictures/videos that exist only as inline citations.
- `summary` and `detailed_description` refer to people/objects/places as `<Subject N>`. Mention `<Picture N>` there only when that picture is a real frame/composition/storyboard anchor.
- Never invent labels for Hybrid keyframes. Never invent a label for a Motion Context pinned head.

## Workflow

1. **Parse assets and roles**
   - Call `get_context`. Apply the Motion Context gate. If Off, ignore those fields. If On, `keyframes.first` is absent — do not inspect that image.
   - Route Ref2VA vs Hybrid from remaining keyframes.
   - Inspect attached keyframe images that are still in use, reference images, and video stills using their asset IDs and matching notes.
   - Map remaining Hybrid first/last as true keyframes (outside the reference list).
   - Map remaining `references` with the decision tree. Do not dump every file and do not strip source keywords.
   - Note duration and aspect.

2. **Director pass**
   - If `requirements` is a one-liner or otherwise thin, invent the complete clip story (setting, blocking, narrative arc, and the motion the references enable) that fills the full sample duration, consistent with the sentence, remaining keyframes, and references.
   - If the user already specified beats, dialogue, positions, or a shot list, keep that story. Expand it onto the clock; do not replace it with a different plot.
   - Design 1–N shots that fill the full sample duration with concrete change.
   - Decide retention strength (fully_preserved, partially_preserved, attribute_transfer, weak_reference, fully_copy, etc.).
   - For motion-reference videos, extract useful action or camera path from the stills; do not copy the entire source timeline unless the task is video editing / continuation.
   - If Motion Context is On, Shot 1 continues the previous closing state, including unfinished motion and sound at the same speed. New plot and dialogue start after the airlock. Write times on the sample clock. Do not plan a first-frame lock.

3. **Write the sections**

   **Optional Hybrid alignment line** (recommended when Motion Context is Off and a first-frame lock exists):
   ```
   For the target video, at 0.00 seconds into the target video, the first frame is fully referenced as the opening keyframe.
   ```
   Adjust for last_frame or both as needed. Follow with one blank line. If Motion Context is On, omit any first-frame alignment line. A last-frame alignment line may remain, timed to the sample-clock end.

   **subject_definitions** — one line per trackable item only. Follow `references/ref-en.txt` §2 / §2.2.

   **summary** — one short paragraph starting with a square-bracketed task-type prefix, e.g. `[reference generation]`, `[video editing + audio reuse]`, `[keyframe completion + reference generation]`, `[first-frame locked + multi-reference]`. If Motion Context is On, include `video continuation` in that prefix. Mention Hybrid keyframe role when applicable.

   **retention_analysis** — one line per standalone label, plus a Hybrid lock line for each still-active keyframe:
   `The first frame is fully locked at 0.00s as the opening keyframe (composition, identity, lighting, style).`
   Do not write a first-frame lock line when Motion Context is On. Keep a last-frame lock line only when `keyframes.last` is still in use.

   **detailed_description**
   - 1–2 English sentences of overall style first.
   - Then `[Shot 1] ...` (no timestamp) followed by later shots with `At MM:SS.mmm`.
   - Insert reference labels at the moment they become active.
   - Speaker IDs, `<d>[Language]...</d>`, camera vocabulary identical to the base guide.
   - Make every shot concrete: composition, subject, environment, lighting, actions, camera, current sound, keyframe and reference activation points.
   - Aim for 350–500 words on pure generation tasks.

   **overall_soundscape** — 1–4 continuous sentences of ambient + physical + non-verbal human sound. Cite `<Audio N>` if an ambience layer is copied. Do not claim to have listened.

   **non_diegetic_music** — N/A or a concrete instrumental description. Cite `<Audio N>` if a score is reused.

4. **Final checks**
   - All standalone labels appear consistently later.
   - Identity/style/object source images are cited inline and do not have their own definition or retention line.
   - No dump-all picture list. No strip-all missing source keywords.
   - First-frame Hybrid locking is stated in summary / retention only when Motion Context is Off. Last-frame locking is stated when `keyframes.last` is still in use. First/last frames still have no `<Picture N>` label.
   - Timing never exceeds the sample duration (sample clock if Motion Context is On).
   - Readable on-screen text is spelled out in double quotes.

5. **Output**
   - Emit only the (optional alignment line +) six sections inside the markdown fence from `mcp.md`.

## Practical Optimizations

- Never put Hybrid first/last keyframes into the reference list. On a Motion Context continuation clip, treat first as empty; the pinned head already owns those frames.
- When a still-active first-frame lock or an identity image carries look and composition, declare the lock or subject once, then move the action forward.
- Prefer hard cuts. Soft transitions only when the user asks.
- Always keep the storyboard continuous; empty seconds produce model hallucination.
- **LoRA trigger words**: when `trigger_words` is nonempty, place it at the very start of `detailed_description` (right after the colon or as the first tokens before style / `[Shot 1]`).

## Reference

- MCP input and output: `references/mcp.md`
- Official Ref2VA rules, label system, retention markers, and example: `references/ref-en.txt`
- Official base / keyframe alignment vocabulary and shared shot rules: `references/base-en.txt`
- Distilled production tips: `references/practical-tips.md`
- Clip-chaining prompt rules (opt-in only): `references/motion-context.md`
