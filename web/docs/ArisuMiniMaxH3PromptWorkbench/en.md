# MiniMax H3 Prompt Workbench

Draft a MiniMax H3 prompt with a Docker-isolated agent, review it, and send the
finalized text downstream. **A normal Run only returns Finalized prompt.** It
does not contact an agent, load motion context, or prepare references.

## Editing and generation

1. Write Finalized prompt directly, or select an agent and skill on the left.
2. Connect Video Settings and Resource Studio bundles, or advertise them.
   Reference notes follow active references; keyframes need no notes.
3. Add trigger words and shot requirements, then click **Generate prompt**.
4. Open **Generation results → Output prompt** to review or edit the result, then
   **Apply to Workbench**. Or choose **Apply output** on the node. Applying replaces
   Finalized prompt as one undoable edit; closing the dialog leaves it unchanged.

Explicit bundle wires can cross subgraph boundaries. Use a separate Workbench for each context
when a subgraph is instantiated more than once.

Generation prepares only the selected dependency graph. It never queues a
downstream sampler or save node. Generate captures the current contexts once. Editing video
settings, Resource Studio, Workbench fields, connections, or Finalized prompt does not cancel
the job or clear its results. Those edits affect the next Generate. Contexts, finalized output,
and the Docker job are independent; only Generate and Apply transfer information between them.
Apply replaces the current finalized text even when the contexts have changed; Undo restores
that text. A result matching Finalized prompt is shown as Applied.

Generation and results survive Undo/Redo and switching between open workflow tabs. Cancel,
deleting the Workbench node, closing/replacing its workflow, or leaving the page releases the
job. Imported and duplicated workflows start with no generation state.
One generation runs at a time, with a ten-minute deadline. Builds have a thirty-minute deadline.
Cancellation affects this job; it does not interrupt unrelated ComfyUI work.

## Motion Context

Connect **H3 Motion Context Load Latent** to `context_latent` and its video VAE
to `vae`. Both sockets are required to enable Motion Context. The section opens
automatically when both are connected; click **Motion context** to expand or
collapse its controls. The **Enable motion context** checkbox at the right of the header
defaults to on and is available only when both sockets are connected. Clicking the checkbox
does not expand or collapse the section. Switch it off for a
first clip without disconnecting either wire; motion settings remain saved, and motion
frames and notes are omitted from that generation.

Settings and reference preparation run on CPU without entering the video queue. Only
motion preparation joins that queue, using the GPU for VAE decoding after earlier video
jobs finish. Workbench uses a separate execution cache for this preparation, preserving
video cache entries. Memory pressure, model offloading, and changes to the video workflow
can still cause reloads or recomputation.

- Load index **0** returns no previous context: the first clip needs no VAE decode.
- Windows **5, 22, 39, 56** are video frames at 24 fps. Respectively **2, 4, 6, 8** ordered stills
  describe the decoded tail to the agent, including both endpoints.
- Audio context length is descriptive only. **0** follows video length; no
  audio latent is decoded by this node.
- Short or incompatible saved latents require corrected inputs; arbitrary
  latent producers and upstream samplers are not accepted.

## Agent setup

Open **Arisu → Prompt Workbench → Agents** in ComfyUI Settings, or use the
node's **Setup** shortcut to the same interface. Build an image, complete the
device-code login shown in Activity, and choose a supported model and effort.
Only low, medium, and high efforts are exposed.

Docker must already be installed and accessible to the ComfyUI server process.
If unavailable, the left column is disabled and Finalized prompt stays editable.
Images use `python:3.13-slim-trixie` and official standalone CLI distributions.
Updates preserve login; failed updates retain the usable image. Confirmed complete removal deletes only that provider’s owned images, containers, and login volume.

Agent accounts are shared by trusted users of this ComfyUI installation.
The existing ComfyUI access boundary is trusted; this feature adds no login.
Provider credentials remain in dedicated Docker volumes, never workflows.
Generation requires network access to the provider and may consume account usage.

Bundled skills are **with-ref** (default; Ref2VA / Hybrid) and **no-ref** (T2VA / I2VA / FL2VA /
L2VA). They share one MCP: `get_context` returns duration,
aspect, requirements, trigger words, keyframes, grouped references, and motion stills;
`read_skill` serves selected `.md`/`.txt` skill documents. Raster assets include absolute mounted
paths and unique IDs matching their initial-prompt attachments; image/file readers are disabled.
MCP never transfers image bytes. Video references are ordered stills; audio is listed with notes
only. Administrators can add `<skill-name>/SKILL.md` folders under `user/__arisu_nodes/skills`.
Files and skills are mounted read-only for generation; the agent has no Docker socket, GPU, or
mount of the ComfyUI installation.

Switch **Codex / Grok Build** tabs in agent settings to leave more space for colored build
and login logs. Device-login URLs open directly in your browser.

**Generation results** is always available. Its **Activity** tab shows provider-exposed
analysis directly, with context metadata, tool arguments, and loaded skill files in collapsed
details. Expand a tool row to inspect its text. Repeated provider updates refresh the same row,
preserving expanded details. Scroll up to pause following new output, or choose
**Resume auto-scroll**. The **Output prompt** tab lets you edit the latest result and
**Apply to Workbench**. You can also use **Apply output** directly on the node.
Generation sends a success or failure notification without opening a dialog.
Starting another generation clears the previous output immediately. Activity and unapplied
output stay outside the workflow and node data; only the node's saved fields, including
explicitly applied finalized text, travel with workflow copies.

Only the current operation is retained until the next operation or server shutdown.
There is no separate Docker log container. Output is paged without message clipping;
exceeding the 16 MiB operation output budget stops the operation with an error.
Use **Update CLI** for both installed providers to enable structured activity records in existing
images, and whenever an image reports an incompatible Workbench policy. Older images retain
plain-text log support; their multiline tool output has less reliable grouping.

Selected media and motion stills are cached beneath ComfyUI temp, bounded to 2 GiB and expired
after 30 idle minutes. Closing/removing the workflow releases its interests.

Generation disables native CLI sandboxes inside Docker and never asks for approval or decisions.
Docker protects the root filesystem and input/skill mounts; writable locations are limited to CLI
runtime state and authentication. Immutable policies disable web, shell, edits, delegation and
unrelated reads. Results come from provider streams, never a generated file.

A brief asking the agent to code, browse, change files or bypass policy fails as a whole. A video
about a programmer is still allowed. Prompt-injection detection is probabilistic; denied tools,
invalid output, mismatched attachments, and incomplete context/skill reads fail generation without changing finalized text.

Scroll over the panel to zoom the graph; hold the middle mouse button to pan. Overflowing editors keep normal vertical scrolling; Ctrl+wheel zooms the graph there.

Agent activity displays provider-exposed thoughts as readable text. Expand tool and other detail sections to inspect their full output.

Prepared images preserve transparency, apply selected crops, and use lossless WebP, with a
32 MiB limit per image, including keyframes, video stills, and motion stills.
Only images exceeding a 4000-pixel longer edge are resized, using Lanczos. Video references
provide up to eight distinct evenly spaced frames across the entire selected clip, including
the first and last displayed frames. No video transcoding or audio decoding occurs.
Each attachment carries a matching asset ID, role, sequence position, and current notes.
Agent containers have 512 MiB of `/tmp` space. Grok's complete initial JSON prompt file is
bounded to 384 MiB, including Base64 images, text, metadata, and JSON overhead. This allows
approximately 288 MiB of prepared images before text and metadata, reserving 128 MiB of
temporary space for other CLI files. The shared media cache remains capped at 2 GiB.
Lossless files exceeding the image limit or Grok’s bounded prompt payload fail generation;
quality is never silently reduced.
