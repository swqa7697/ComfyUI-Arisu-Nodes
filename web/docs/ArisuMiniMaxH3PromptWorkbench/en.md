# MiniMax H3 Prompt Workbench

Draft a MiniMax H3 prompt with a Docker-isolated agent, review it, and send the
finalized text downstream. **A normal Run only returns Finalized prompt.** It
does not contact an agent, load motion context, or prepare references.

## Editing and generation

1. Write Finalized prompt directly, or select an agent and skill on the left.
2. Connect Video Settings and Resource Studio bundles, or advertise them.
   Reference notes follow active references; keyframes need no notes.
3. Add trigger words and shot requirements, then click **Generate prompt**.
4. Review the generated draft. **Apply** replaces Finalized prompt as an undoable
   edit; **Discard** keeps your current prompt.

Explicit bundle wires can cross subgraph boundaries. Use a separate Workbench for each context
when a subgraph is instantiated more than once.

Generation prepares only the selected dependency graph. It never queues a
downstream sampler or save node. Changing sources cancels stale generation.
One generation runs at a time, with a ten-minute deadline. Builds have a thirty-minute deadline.
Cancellation affects this job; it does not interrupt unrelated ComfyUI work.

## Motion Context

Connect **H3 Motion Context Load Latent** to `context_latent` and its video VAE
to `vae`. Both sockets are required to enable Motion Context. The section opens
automatically when both are connected; click **Motion context** to expand or
collapse its controls.

- Load index **0** returns no previous context: the first clip needs no VAE decode.
- Windows **5, 22, 39, 56** are video frames at 24 fps. Up to 12 ordered stills
  describe the decoded tail to the agent.
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

The bundled **hybrid2va** skill is a feasibility stub. Administrators can add
`<skill-name>/SKILL.md` folders under `user/__arisu_nodes/skills`.
Files and skills are mounted read-only for generation; the agent has no Docker
socket, GPU, or mount of the ComfyUI installation.

Switch **Codex / Grok Build** tabs in agent settings to leave more space for colored build
and login logs. Device-login URLs open directly in your browser.

During generation, the running indicator and **Agent activity** button show complete
provider-exposed analysis, reference/tool calls, and text results. Scroll up to pause
following new output; **Resume auto-scroll** returns to the latest output. An open activity
dialog stays readable when generation finishes; close it to review the draft.

Only the current operation is retained until the next operation or server shutdown.
There is no separate Docker log container. Output is paged without message clipping;
exceeding the 16 MiB operation output budget stops the operation with an error.
Use **Update CLI** for existing images to install the expanded event renderer.

Selected media and motion stills are cached beneath ComfyUI temp, bounded to 2 GiB and expired
after 30 idle minutes. Closing/removing the workflow releases its interests.

The MCP offers `get_context` and `read_image` for manifest-listed images only.
See the README’s optional Docker smoke check for standalone CLI, skill, MCP, mount,
log, and cleanup verification without using a provider account.

Scroll over the panel to zoom the graph; hold the middle mouse button to pan. Overflowing editors keep normal vertical scrolling; Ctrl+wheel zooms the graph there.

Agent activity displays provider-exposed thoughts as readable text. Expand tool and other detail sections to inspect their full output.
