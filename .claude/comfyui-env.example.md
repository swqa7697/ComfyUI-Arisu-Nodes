# ComfyUI environment — local facts (template)

Copy to `.claude/comfyui-env.md` and fill in for this machine. `.gitignore` tracks only this
template, so the filled-in copy never leaves the machine. `CLAUDE.md`'s "Hard boundary" section
holds the *rules*, keyed on `$COMFYUI_PATH`; this file holds the machine-specific *facts* those
rules point at. When it is missing, an agent must treat `$COMFYUI_PATH` as a live,
expensive-to-rebuild install and ask before touching anything named below.

| Field | Value | What it is for |
|---|---|---|
| `comfyui_path` | `<ComfyUI root>` | Must match `make comfyui-path` (default `~/apps/comfyui`). |
| `service_unit` | `<name>.service` | User systemd unit. `status`/`journalctl` only, never `start\|stop\|restart`. |
| `launcher` | `<path to start script>` | What starts it, e.g. a wrapper running `uv run python main.py` inside the install. |
| `api_endpoint` | `http://<host>:<port>` | `curl -s <api_endpoint>/object_info` is an allowed read. |
| `torch_build` | `+cu<version>` | CUDA wheel tag; sets the recovery index `https://download.pytorch.org/whl/cu<version>`. |
| `torch_rebuild_time` | `<minutes>` | The price of one mistake, so the ban reads as a cost, not a whim. |
| `installed_packages` | `<count>` | What a stray `uv sync` in that directory would remove. |
| `venv_has_pip` | `yes` / `no` | If no, recovery must go through `uv pip install --python <venv python>`. |
| `venv_write_lock` | `applied` / `not applied` | Whether `chmod -R a-w .venv` is in place. |
| `gpu` | `<count, shared or dedicated>` | Why an agent never restarts the service. |
| `verified_on` | `<tool versions, date>` | When these facts were last checked. |
