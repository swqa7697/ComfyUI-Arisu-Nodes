# MiniMax H3 Director Workbench

Add **MiniMax H3 Director Workbench** to plan a film and render its segments in order. Connect its `prompt`, `video_settings`, and `resources` outputs to the matching inputs on **MiniMax H3 Hybrid to Video**.

## Plan the film

1. Enter the creative brief on the node. Open **Film setup** to edit the story requirements, trigger words, continuity notes, canvas, and generation range together. An optional target runtime can be approximate.
2. Open **Asset library** to add images, videos, or audio. Give each asset a note. Select its thumbnail to edit the default crop or clip. For video, choose whether to include its soundtrack.
3. Choose **Plan the film**. The selected Workbench agent prepares the outline, continuity decisions, requirement coverage, and all segment prompts in one task. Agent setup is shared with Prompt Workbench.
4. Review the plan and its estimated runtime, then apply it in one edit. Undo restores the previous plan. If a plan exceeds the agent budget, reduce the brief or the requested scope and try again.
5. A film-wide writing skill applies to all segments except those with a locked choice. Automatic selection records the skill and its reason for each segment.

A film can contain up to 128 segments and 256 library assets. The saved film document is limited to 1 MiB. Each structured agent result is limited to 256 KiB of UTF-8 text. The provider’s context and output limits can be lower.

## Review a segment

Choose a row in **Sequence** to edit its finalized prompt or render that segment. Use **+ Add** to write a segment manually. Open **Direction & bindings** to edit the intent, opening and closing states, timing, transition, and bound assets, or to reorder the segment. Edits in these dialogs are saved as you work. Close the dialog or press Escape to return to the sequence. Library assets are available to the director during planning. Only the current segment’s bindings are sent to Hybrid. Select a bound thumbnail to override the crop or clip interval for that segment. Video bindings also have a segment soundtrack setting.

Prompt tags follow the segment’s input order. For example, `<Picture 1>` refers to the first numbered picture for the selected keyframe tag setting. A saved stable tag such as `<Picture:umbrella>` follows the asset with ID `umbrella` as bindings move. Reselect missing or changed sources before rendering.

To revise one segment, open **Revise prompt**, enter a revision request, and choose **Refine current segment**. For a continuation, you can include tail images from its predecessor’s render and supply written audio notes. Review the proposed replacement and apply it to the target segment. Neighbor suggestions are advisory.

## Render and resume

To use the render controls, connect one Motion Context Load Latent to Motion Context. Feed Hybrid’s conditioning and latent into Motion Context, then connect its conditioning and Hybrid’s latent to the sampler. Connect the sampled latent to Motion Context Save Latent and to both VAE decoders. Feed the decoded picture and sound through Motion Context Trim using the Motion Context `trim_frames` output. Connect both trimmed outputs to Create Video at 24 fps, then connect Create Video to Save Video.

Each segment generates a full clip at 24 fps with a legal H3 frame count inside the film’s duration range. Hard cuts use all generated frames. A continuation uses the previous take’s Motion Context, then trims the overlap from the delivered picture and soundtrack.

**Render current segment** renders the selected segment. **Render remaining segments** works forward from the selection and checks completed takes before submitting another generation. Stopping lets the current render finish. A changed or missing predecessor must be rendered again before continuing from it.

Save the workflow to keep the applied film, library, segment selection, and render records. Keep the corresponding rendered videos and latent files under the ComfyUI output directory to resume. Planning drafts and agent activity live in the open workflow. A normal ComfyUI Run emits the selected segment’s three finalized outputs. Use the Director render buttons to record takes for later segments.
