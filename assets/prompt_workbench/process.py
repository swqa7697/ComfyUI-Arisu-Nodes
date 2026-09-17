"""Bounded CLI discovery processes."""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any, List


def run(arguments: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Capture bounded-duration CLI discovery without exposing credentials."""
    return subprocess.run(arguments, text=True, capture_output=True, timeout=timeout, check=False)


def rpc(arguments: List[str], method: str, initialize: Any, params: Any, initialized: bool = False) -> Any:
    """Read a catalog RPC with a hard process deadline and no inference request."""
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    timer = threading.Timer(25, process.kill)
    timer.start()
    try:
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": initialize}]
        if initialized:
            messages.append({"method": "initialized", "params": {}})
        messages.append({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" not in message:
                continue
            while line := process.stdout.readline(1024 * 1024):
                response = json.loads(line)
                if response.get("id") == message["id"]:
                    if "error" in response:
                        raise ValueError("Agent catalog discovery failed")
                    if message["id"] == 1:
                        return response["result"]
                    break
        raise ValueError("Agent catalog discovery ended unexpectedly")
    finally:
        timer.cancel()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.stdout.close()
