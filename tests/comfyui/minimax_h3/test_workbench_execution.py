"""Actual executor cache retention across bounded motion preparation jobs."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import comfy.model_management
import execution
import nodes
import pytest

from src.arisu_nodes.minimax_h3 import workbench_execution

pytestmark = pytest.mark.comfyui


def test_motion_preparation_preserves_video_cache_on_success_failure_and_interrupt(monkeypatch: pytest.MonkeyPatch):
    calls = []

    class Output:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"value": ("INT",)}}

        RETURN_TYPES = ("INT",)
        FUNCTION = "run"
        OUTPUT_NODE = True

        def run(self, value):
            calls.append(value)
            if value == -1:
                raise ValueError("synthetic failure")
            if value == -2:
                raise comfy.model_management.InterruptProcessingException()
            return (value,)

    monkeypatch.setitem(nodes.NODE_CLASS_MAPPINGS, "ArisuCacheProbe", Output)
    monkeypatch.setattr(workbench_execution, "_pending", {})
    monkeypatch.setattr(workbench_execution, "_adapter", None)
    monkeypatch.setattr(execution.PromptExecutor, "execute_async", execution.PromptExecutor.execute_async)
    server = SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)
    video = {"v": {"class_type": "ArisuCacheProbe", "inputs": {"value": 1}}}
    for policy in (execution.CacheType.CLASSIC, execution.CacheType.LRU, execution.CacheType.RAM_PRESSURE):
        runner = execution.PromptExecutor(server, cache_type=policy, cache_args={"lru": 8, "ram": 0, "ram_inactive": 0})
        runner.execute(video, "video", {}, ["v"])
        assert runner.success
        cached = runner.caches
        baseline = calls.count(1)
        for value in (2, -1, -2):
            graph = {"w": {"class_type": "ArisuCacheProbe", "inputs": {"value": value}}}
            job = SimpleNamespace(node_id="w", cancelled=threading.Event(), deadline=time.monotonic() + 30, prepared=threading.Event())
            workbench_execution.register("motion", job, graph)
            workbench_execution.install()
            runner.execute(graph, "motion", {}, ["w"])
            assert runner.caches is cached and runner.success == (value == 2)
            runner.execute(video, "video-again", {}, ["v"])
            assert runner.success and calls.count(1) == baseline
        # A copied graph cannot use a registered capability; no node executes.
        workbench_execution.register("motion", job, graph)
        before = list(calls)
        runner.execute(dict(graph), "motion", {}, ["w"])
        assert not runner.success and calls == before and runner.caches is cached
        # A browser marker alone cannot trigger isolation.
        ordinary = {"o": {"class_type": "ArisuCacheProbe", "inputs": {"value": 3}}}
        runner.execute(ordinary, "unregistered", {"workbench": True}, ["o"])
        assert runner.success and calls[-1] == 3 and runner.caches is cached

    with monkeypatch.context() as changed:
        changed.setattr(execution.PromptExecutor, "execute_async", lambda *args: None)
        with pytest.raises(ValueError, match="unavailable"):
            workbench_execution.register("unsupported", job, graph)
    assert "unsupported" not in workbench_execution._pending
