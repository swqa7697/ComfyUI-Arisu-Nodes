"""Fixed Docker operations for the Workbench's shared, administrator-owned agents."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .core import AGENT_IDS, BASIC_EFFORTS

logger = logging.getLogger(__name__)
ASSETS = Path(__file__).resolve().parents[3] / "assets" / "prompt_workbench"
BASE_IMAGE = "python:3.13-slim-trixie"
LABEL = "org.arisu.workbench.instance"
PROVIDER_LABEL = "org.arisu.workbench.provider"
MAX_OUTPUT = 2 * 1024 * 1024


class AgentBusy(ValueError):
    """An agent operation already owns the service."""


class DockerAgents:
    """Manage only this installation's labelled images, volumes and containers."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.namespace = "arisu-workbench-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
        self.guard = threading.Lock()
        self.discovery = threading.Lock()
        self.stopping = threading.Event()
        self.logs: List[str] = []
        self.log_lock = threading.Lock()
        self.log_bytes = 0
        self.log_session: Dict[str, Any] = {}
        self.operation: Optional[Dict[str, Any]] = None
        self.preferences: Dict[str, Any] = {}
        self._status: Dict[str, Any] = {}
        self._checked = 0.0
        path = directory / "workbench.json"
        if path.is_file() and not path.is_symlink() and not directory.is_symlink():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    self.preferences = {key: value for key, value in data.items() if key in AGENT_IDS and isinstance(value, dict)}
            except (OSError, ValueError):
                logger.warning("Unable to read Workbench preferences")

    def image(self, agent: str) -> str:
        """Return the fixed provider image name."""
        if agent not in AGENT_IDS:
            raise ValueError("unsupported agent")
        return self.namespace + "-" + agent + ":current"

    def volume(self, agent: str) -> str:
        """Return a dedicated provider authentication volume."""
        self.image(agent)
        return self.namespace + "-" + agent + "-auth"

    def command(self, args: List[str], timeout: int = 30, check: bool = True, data: Optional[str] = None) -> str:
        """Execute a fixed argv with a bounded lifetime and captured output."""
        result = subprocess.run(["docker", *args], input=data, text=True, capture_output=True, timeout=timeout, check=False)
        if check and result.returncode:
            logger.warning("Workbench Docker operation failed: %s", result.stderr[-4000:])
            raise ValueError("Docker operation failed; see the server log")
        if len(result.stdout) > MAX_OUTPUT:
            raise ValueError("Docker response exceeds limit")
        return result.stdout

    def owned(self, kind: str, name: str) -> bool:
        """Require this install's label before acting on an existing resource."""
        try:
            data = json.loads(self.command([kind, "inspect", name], check=False))
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                return False
            labels = data[0].get("Labels") if kind == "volume" else data[0].get("Config", {}).get("Labels")
            return (labels or {}).get(LABEL) == self.namespace
        except (OSError, ValueError, subprocess.SubprocessError):
            return False

    def begin_logs(self, agent: str, action: str, job: str = ""):
        """Replace the previous session only after the caller owns the operation guard."""
        with self.log_lock:
            self.operation = {"agent": agent, "action": action, "state": "running"}
            self.logs.clear()
            self.log_bytes = 0
            self.log_session = {"session": uuid.uuid4().hex, "agent": agent, "action": action, "job": job, "state": "running"}

    def finish_logs(self, state: str):
        """Retain the current session for its open viewers until the next operation."""
        with self.log_lock:
            self.log_session["state"] = state
            if self.operation:
                self.operation["state"] = state

    def read_logs(self, session: str = "", cursor: int = 0, job: str = "") -> Dict[str, Any]:
        """Page the current session atomically, without replaying old jobs or history."""
        with self.log_lock:
            if job and job != self.log_session.get("job"):
                return {"session": "", "lines": [], "cursor": 0, "more": False}
            start = min(cursor, len(self.logs)) if session == self.log_session.get("session") else 0
            end, size = start, 0
            while end < len(self.logs) and end - start < 128 and size < 256 * 1024:
                size += len(self.logs[end])
                end += 1
            return {**self.log_session, "lines": self.logs[start:end], "cursor": end, "more": end < len(self.logs)}

    def log(self, text: str):
        """Keep complete readable output; redact credentials and remove terminal controls."""
        text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", str(text))
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        text = re.sub(r"(?i)(bearer\s+|(?:access_token|refresh_token|api_key)[\"' :=]+)\S+", r"\1[redacted]", text)
        text = re.sub(r"\b(?:sk-|xai-)[A-Za-z0-9_-]{16,}", "[redacted]", text)
        text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32)
        with self.log_lock:
            size = len(text.encode("utf-8")) + 1
            if self.log_bytes + size > 16 * 1024 * 1024:
                raise ValueError("operation log exceeds 16 MiB; stopped without truncating output")
            self.logs.append(text)
            self.log_bytes += size

    def run_args(self, agent: str, name: str, image: Optional[str] = None) -> List[str]:
        """Apply the same isolation to discovery, login and generation."""
        return [
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--label",
            LABEL + "=" + self.namespace,
            "--label",
            PROVIDER_LABEL + "=" + agent,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "1000:1000",
            "--cpus",
            "2",
            "--memory",
            "2g",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
            "--tmpfs",
            "/work:rw,nosuid,nodev,size=256m,uid=1000,gid=1000",
            "--mount",
            "type=volume,src=" + self.volume(agent) + ",dst=/home/agent/." + agent,
            "--log-opt",
            "max-size=5m",
            "--log-opt",
            "max-file=2",
            *(["--entrypoint", "python"] if image == BASE_IMAGE else []),
        ]

    def invoke(self, agent: str, action: str, timeout: int = 45, image: Optional[str] = None) -> Dict[str, Any]:
        """Run the provider adapter and decode its single status result."""
        name = self.namespace + "-check-" + uuid.uuid4().hex
        try:
            text = self.command([*self.run_args(agent, name), image or self.image(agent), agent, action], timeout)
            return json.loads(text)
        finally:
            if self.owned("container", name):
                self.command(["rm", "-f", name], check=False)

    def status(self, refresh: bool = False) -> Dict[str, Any]:
        """Report Docker readiness without installing anything automatically."""
        if not refresh and self._checked > time.monotonic() - 15:
            return {**self._status, "operation": self.operation}
        if not self.discovery.acquire(blocking=False):
            return {**self._status, "operation": self.operation}
        if not self.guard.acquire(blocking=False):
            self.discovery.release()
            return {**self._status, "operation": self.operation}
        result: Dict[str, Any] = {"docker": False, "agents": {}}
        try:
            if not shutil.which("docker"):
                return result
            self.command(["info", "--format", "{{.OSType}}"], timeout=5)
            result["docker"] = True
            for agent in AGENT_IDS:
                info: Dict[str, Any] = {"installed": self.owned("image", self.image(agent)), "ready": False, "models": []}
                if info["installed"] and self.owned("volume", self.volume(agent)):
                    try:
                        info.update(self.invoke(agent, "inspect"))
                        info["ready"] = bool(info.get("authenticated") and info.get("auto") and info.get("models"))
                    except (ValueError, OSError, subprocess.SubprocessError):
                        info["error"] = "Agent discovery failed; inspect logs or update the image."
                choice = self.preferences.get(agent, {})
                models = info.get("models", [])
                model = next((m for m in models if m["id"] == choice.get("model")), None)
                model = model or next((m for m in models if m.get("default")), None) or next(iter(models), None)
                if model:
                    efforts = model.get("efforts", [])
                    effort = choice.get("effort")
                    info["selection"] = {
                        "model": model["id"],
                        "effort": effort if effort in efforts else "medium" if "medium" in efforts else next(iter(efforts), ""),
                    }
                result["agents"][agent] = info
        except (OSError, ValueError, subprocess.SubprocessError):
            result["error"] = "Docker is unavailable to the ComfyUI server."
        finally:
            self.guard.release()
            self.discovery.release()
        self._status, self._checked = result, time.monotonic()
        return {**result, "operation": self.operation}

    def configure(self, agent: str, model: str, effort: str):
        """Persist validated preferences outside workflow state."""
        info = self.status()["agents"].get(agent, {})
        selected = next((item for item in info.get("models", []) if item["id"] == model), None)
        if selected is None or effort not in selected.get("efforts", []) + ([""] if not selected.get("efforts") else []):
            raise ValueError("unsupported model or effort")
        if effort and effort not in BASIC_EFFORTS:
            raise ValueError("unsupported reasoning effort")
        self.preferences[agent] = {"model": model, "effort": effort}
        self.save_preferences()
        self._checked = 0

    def save_preferences(self):
        """Atomically save model choices without touching authentication."""
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink() or (self.directory / "workbench.json").is_symlink():
            raise ValueError("invalid configuration destination")
        temp = self.directory / ("workbench-" + uuid.uuid4().hex + ".json")
        try:
            with temp.open("x") as output:
                json.dump(self.preferences, output)
            os.replace(temp, self.directory / "workbench.json")
        finally:
            temp.unlink(missing_ok=True)
        self._checked = 0

    def stream(
        self,
        args: List[str],
        deadline: float,
        cancelled: threading.Event,
        name: Optional[str] = None,
        data: Optional[str] = None,
        receive: Optional[Callable[[str], None]] = None,
    ):
        """Reap the real Docker child/container before returning or releasing guards."""
        process = subprocess.Popen(["docker", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        errors: List[BaseException] = []

        def read():
            try:
                total = 0
                while line := process.stdout.readline(1024 * 1024 + 1):
                    total += len(line)
                    if len(line) > 1024 * 1024 or total > 16 * 1024 * 1024:
                        raise ValueError("operation log exceeds limit")
                    if receive:
                        receive(line)
                    if not line.startswith("ARISU_RESULT "):
                        self.log(line.rstrip())
            except (ValueError, OSError, KeyError, TypeError) as error:
                errors.append(error)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            if data:
                process.stdin.write(data)
            process.stdin.close()
            while process.poll() is None:
                if errors:
                    break
                if cancelled.wait(0.1) or time.monotonic() > deadline:
                    raise ValueError("operation cancelled or timed out")
            reader.join(timeout=5)
            if errors:
                if str(errors[0]).startswith("operation log exceeds"):
                    raise ValueError("operation log exceeds limit; stopped without truncating earlier output") from None
                raise ValueError("operation output could not be read")
            if process.returncode:
                raise ValueError("agent operation failed; open logs for details")
        finally:
            if name and self.owned("container", name):
                self.command(["rm", "-f", name], check=False)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            reader.join(timeout=5)
            process.stdout.close()

    def manage(self, agent: str, action: str, reserved: bool = False):
        """Build/login/update/remove through explicit settings actions only."""
        self.image(agent)
        if action not in ("build", "update", "login", "logout", "remove"):
            raise ValueError("unsupported management action")
        if not reserved and not self.guard.acquire(blocking=False):
            raise AgentBusy("Workbench is busy")
        self.operation = {"agent": agent, "action": action, "state": "running"}
        try:
            self.begin_logs(agent, action)
            self.log("[" + agent + "] " + action)
            if action in ("build", "update"):
                candidate = self.namespace + "-" + agent + ":candidate"
                existing = self.command(["image", "ls", "--format", "{{.Repository}}:{{.Tag}}"]).splitlines()
                for name in (candidate, self.image(agent)):
                    if name in existing and not self.owned("image", name):
                        raise ValueError("agent image name is already in use")
                self.stream(
                    [
                        "build",
                        "--pull",
                        "--no-cache",
                        "--progress=plain",
                        "--label",
                        LABEL + "=" + self.namespace,
                        "--label",
                        PROVIDER_LABEL + "=" + agent,
                        "--build-arg",
                        "AGENT=" + agent,
                        "-t",
                        candidate,
                        str(ASSETS),
                    ],
                    time.monotonic() + 1800,
                    self.stopping,
                )
                if not self.owned("volume", self.volume(agent)):
                    # Refuse an existing unowned name before creating a managed volume.
                    existing = self.command(["volume", "ls", "--format", "{{.Name}}"])
                    if self.volume(agent) in existing.splitlines():
                        raise ValueError("authentication volume name is already in use")
                    self.command(["volume", "create", "--label", LABEL + "=" + self.namespace, self.volume(agent)])
                self.invoke(agent, "check", image=candidate)
                self.command(["tag", candidate, self.image(agent)])
                self.command(["image", "rm", candidate])
            elif action == "remove":
                # Include retired image IDs after updates, never Docker-wide prune.
                filters = ["--filter", "label=" + LABEL + "=" + self.namespace, "--filter", "label=" + PROVIDER_LABEL + "=" + agent]
                for identifier in self.command(["ps", "-aq", *filters]).splitlines():
                    if self.owned("container", identifier):
                        self.command(["rm", "-f", identifier])
                retired = self.command(["image", "ls", "-q", *filters]).splitlines()
                for kind, name in (
                    ("image", self.image(agent)),
                    ("image", self.namespace + "-" + agent + ":candidate"),
                    ("volume", self.volume(agent)),
                ):
                    if self.owned(kind, name):
                        self.command([kind, "rm", name])
                for identifier in set(retired):
                    if self.owned("image", identifier):
                        self.command(["image", "rm", identifier])
                self.preferences.pop(agent, None)
                self.save_preferences()
            else:
                if not self.owned("image", self.image(agent)) or not self.owned("volume", self.volume(agent)):
                    raise ValueError("build this agent first")
                name = self.namespace + "-" + action + "-" + uuid.uuid4().hex
                self.stream([*self.run_args(agent, name), self.image(agent), agent, action], time.monotonic() + 600, self.stopping, name)
            self.operation["state"] = "complete"
        except Exception as error:
            logger.exception("Workbench management failed")
            self.operation["state"] = "failed"
            self.operation["error"] = (
                "Operation output exceeded its limit; stopped without truncating earlier logs."
                if isinstance(error, ValueError) and str(error).startswith("operation log exceeds")
                else "Operation failed; see the logs."
            )
            raise
        finally:
            self.finish_logs(self.operation["state"])
            self._checked = 0
            self.guard.release()

    def generate(
        self, agent: str, inputs: Path, skill: Path, selection: Dict[str, Any], cancelled: threading.Event, deadline: float
    ) -> str:
        """Run a single agent with only the prepared job and selected skill mounted."""
        name = self.namespace + "-generate-" + uuid.uuid4().hex
        result: List[str] = []

        def receive(line: str):
            if line.startswith("ARISU_RESULT "):
                result.append(json.loads(line.removeprefix("ARISU_RESULT "))["final"])

        self.log("[job " + inputs.name + "] generating with " + agent)
        self.stream(
            [
                *self.run_args(agent, name),
                "--mount",
                "type=bind,src=" + str(inputs) + ",dst=/inputs,readonly",
                "--mount",
                "type=bind,src=" + str(skill) + ",dst=/skill,readonly",
                "--mount",
                "type=bind,src="
                + str(skill)
                + ",dst=/home/agent/"
                + (".agents" if agent == "codex" else ".grok")
                + "/skills/selected,readonly",
                self.image(agent),
                agent,
                "generate",
            ],
            deadline,
            cancelled,
            name,
            json.dumps(selection),
            receive,
        )
        if len(result) != 1:
            raise ValueError("agent did not return one final response")
        return result[0]

    def close(self):
        """Ask the owning workers to stop; no persistent log container is needed."""
        self.stopping.set()
