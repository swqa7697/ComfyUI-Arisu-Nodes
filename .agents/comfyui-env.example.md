# ComfyUI environment — local facts (template)

Keep local settings in `.agents/comfyui-env.md`. On a fresh checkout, copy this template
there and fill in the values for this machine. When migrating, preserve the values
from the existing `.claude/comfyui-env.md`. From the repository root, create the local Claude Code symlink with
`ln -s ../.agents/comfyui-env.md .claude/comfyui-env.md`. Git ignores both local paths.
The “Hard boundary” section of `AGENTS.md` defines the rules for `$COMFYUI_PATH`.
This file holds the machine-specific facts. When it is missing, an agent must treat `$COMFYUI_PATH` as a live,
expensive-to-rebuild install and ask before touching anything named below.

| Field | Value | What it is for |
|---|---|---|
| `comfyui_path` | `<ComfyUI root>` | Must match `make comfyui-path` (default `~/apps/comfyui`). |
| `service_unit` | `<name>.service` | User systemd unit. `status`/`journalctl` only, never `start\|stop\|restart`. |
| `launcher` | `<path to start script>` | What starts it, e.g. a wrapper running `uv run python main.py` inside the install. |
| `api_endpoint` | `http://<host>:<port>` | `curl -s <api_endpoint>/object_info` is an allowed read. |
| `torch_build` | `+cu<version>` | CUDA wheel tag; sets the recovery index `https://download.pytorch.org/whl/cu<version>`. |
| `torch_rebuild_time` | `<minutes>` | The price of one mistake, so the ban reads as a cost, not a whim. |
| `gpu` | `<count, shared or dedicated>` | Why an agent never restarts the service. |
| `verified_on` | `<tool versions, date>` | When these facts were last checked. |
