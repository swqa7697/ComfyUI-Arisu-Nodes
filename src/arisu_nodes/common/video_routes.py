"""Video segment routes: project takes, descriptions, export preflight, join previews and verified deletion."""

from __future__ import annotations

import logging
import os
import posixpath
from typing import Any, Dict, List, Mapping, Optional

import folder_paths
from aiohttp import web

from .core import relative_path
from .http import HEADERS, Admission, body, guarded
from .paths import image_roots
from .video import DEFAULT_PROJECT, Source, director_take_id, parse_edit, parse_export_request, plan_export, plan_json
from .video_jobs import PreviewManager, describe_entries, describe_source, detect_tools
from .video_store import delete_take, deletion_plan, list_takes, predicted_export

logger = logging.getLogger(__name__)
PREFIX = "/arisu/video"
MAX_DESCRIBED = 64
_FRESH = {**HEADERS, "Cache-Control": "no-store"}
_ADMISSION = Admission(2)


def roots() -> Dict[str, str]:
    """Resolve the shared administrator-owned root snapshot."""
    return image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory())


def _deletable(allowed: Mapping[str, str], root: str, path: str, revision: str) -> bool:
    if root != "output":
        return False
    try:
        deletion_plan(allowed["output"], path, revision)
    except (OSError, ValueError):
        return False
    return True


def description(allowed: Mapping[str, str], root: str, path: str, source: Source) -> Dict[str, Any]:
    """What a panel may know about one video: root ID, relative path and measured facts, never a physical path."""
    result: Dict[str, Any] = {"root": root, "path": path, "state": source.state}
    if source.probe is None or source.probe.video is None:
        return result
    video, audio, record = source.probe.video, source.probe.audio, source.record
    sound = None
    if source.pcm is not None:
        sound = {"rate": source.pcm.rate, "channels": source.pcm.channels, "samples": source.pcm.samples, "source": "pcm"}
    elif audio is not None:
        sound = {"rate": audio.rate, "channels": audio.channels, "samples": audio.samples, "source": "embedded"}
    take = None
    directed = director_take_id(posixpath.dirname(path)) if root == "output" else None
    if record is not None:
        take = {key: record.get(key) for key in ("take", "origin", "segment", "predecessor", "transition")}
    elif directed:
        take = {"take": directed, "origin": "director", "segment": None, "predecessor": None, "transition": None}
    result.update(
        revision=source.revision,
        frames=video.frames,
        fps=[video.fps.numerator, video.fps.denominator],
        duration=float(video.duration),
        width=video.width,
        height=video.height,
        codec=video.codec,
        vfr=not video.constant,
        audio=sound,
        take=take,
        deletable=_deletable(allowed, root, path, source.revision),
    )
    return result


def _takes(project: str, legacy: bool) -> Dict[str, Any]:
    allowed, tools = roots(), detect_tools()
    found = list_takes(allowed["output"], project, legacy)
    return {
        "project": project,
        "takes": [description(allowed, "output", path, describe_source(allowed, "output", path, None, tools)) for path in found],
    }


def _describe(entries: Any) -> Dict[str, Any]:
    if not isinstance(entries, list) or len(entries) > MAX_DESCRIBED:
        raise ValueError("invalid describe request")
    allowed, tools = roots(), detect_tools()
    described: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not set(entry) <= {"root", "path", "revision"} or not isinstance(entry.get("root"), str):
            raise ValueError("invalid describe request")
        expected: Optional[str] = entry.get("revision")
        if expected is not None and not isinstance(expected, str):
            raise ValueError("invalid describe request")
        path = relative_path(entry.get("path"))
        described.append(description(allowed, entry["root"], path, describe_source(allowed, entry["root"], path, expected, tools)))
    return {"entries": described}


def _preflight(data: Dict[str, Any]) -> Dict[str, Any]:
    if set(data) != {"project", "export_name", "encoding", "codec", "crf", "document"}:
        raise ValueError("invalid preflight request")
    request = parse_export_request(data["project"], data["export_name"], data["encoding"], data["codec"], data["crf"])
    document = parse_edit(data["document"])
    allowed, tools = roots(), detect_tools()
    plan = plan_export(document, describe_entries(allowed, document, tools), request, tools.capabilities)
    return plan_json(plan, predicted_export(allowed["output"], request.project, request.name), tools.backend)


def _delete(data: Dict[str, Any]) -> Dict[str, Any]:
    entries = data.get("entries")
    if (
        set(data) != {"entries", "confirm"}
        or type(data["confirm"]) is not bool
        or not isinstance(entries, list)
        or len(entries) > MAX_DESCRIBED
    ):
        raise ValueError("invalid delete request")
    output = roots()["output"]
    base = os.path.realpath(output)
    results = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"root", "path", "revision"}
            or not all(isinstance(value, str) for value in entry.values())
        ):
            raise ValueError("invalid delete request")
        path = relative_path(entry["path"])
        item: Dict[str, Any] = {"root": entry["root"], "path": path, "state": "refused", "files": [], "bytes": 0}
        try:
            if entry["root"] != "output":
                raise PermissionError("only output takes can be deleted")
            # The request only names a candidate; ownership and the current revision are established here.
            files = deletion_plan(output, path, entry["revision"])
            item["files"] = [{"path": os.path.relpath(name, base).replace(os.sep, "/"), "bytes": size} for name, size in files]
            item["bytes"] = sum(size for _, size in files)
            item["state"] = delete_take(output, path, entry["revision"]) if data["confirm"] else "deletable"
        except (OSError, ValueError):
            logger.info("take deletion refused", exc_info=True)
        results.append(item)
    return {"entries": results, "bytes": sum(item["bytes"] for item in results if item["state"] != "refused")}


def register_routes(routes: web.RouteTableDef, app: Optional[web.Application] = None):
    """Register the video routes; ComfyUI mirrors them under ``/api``."""
    manager: Optional[PreviewManager] = None

    def previews() -> PreviewManager:
        nonlocal manager
        if manager is None:
            manager = PreviewManager(posixpath.join(folder_paths.get_temp_directory(), "arisu_join"))
        return manager

    async def cleanup(application: web.Application):
        if manager:
            await _ADMISSION.run(manager.close)

    if app is not None:
        app.on_cleanup.append(cleanup)

    def route(method: str, path: str):
        def decorate(handler: Any) -> Any:
            routes.route(method, PREFIX + path)(guarded(handler, logger, "video"))
            return handler

        return decorate

    @route("GET", "/takes")
    async def takes(request: web.Request) -> web.Response:
        project = relative_path(request.query.get("project") or DEFAULT_PROJECT)
        return web.json_response(await _ADMISSION.run(_takes, project, request.query.get("legacy") == "1"), headers=_FRESH)

    @route("POST", "/describe")
    async def describe(request: web.Request) -> web.Response:
        data = await body(request)
        if set(data) != {"entries"}:
            raise ValueError("invalid describe request")
        return web.json_response(await _ADMISSION.run(_describe, data["entries"]), headers=_FRESH)

    @route("POST", "/preflight")
    async def preflight(request: web.Request) -> web.Response:
        return web.json_response(await _ADMISSION.run(_preflight, await body(request)), headers=_FRESH)

    @route("POST", "/delete")
    async def delete(request: web.Request) -> web.Response:
        return web.json_response(await _ADMISSION.run(_delete, await body(request)), headers=_FRESH)

    @route("POST", "/join-preview")
    async def create(request: web.Request) -> web.Response:
        data = await body(request)
        if set(data) != {"outgoing", "incoming", "join"}:
            raise ValueError("invalid join preview request")
        manager = previews()
        handle = await _ADMISSION.run(lambda: manager.start(roots(), data["outgoing"], data["incoming"], data["join"], detect_tools()))
        return web.json_response({"id": handle}, status=202, headers=_FRESH)

    @route("GET", "/join-preview/{id}")
    async def status(request: web.Request) -> web.Response:
        job = previews().get(request.match_info["id"])
        answer = {
            "state": job.state,
            "progress": job.progress,
            "error": job.error,
            "variants": list(job.variants),
            "cut": job.cut,
            "signalling": job.signalling,
            "suggestion": job.suggestion,
        }
        return web.json_response(answer, headers=_FRESH)

    @route("GET", "/join-preview/{id}/view")
    async def view(request: web.Request) -> web.StreamResponse:
        job = previews().get(request.match_info["id"])
        variant = request.query.get("variant", "a")
        if job.state != "ready" or variant not in job.variants:
            raise web.HTTPConflict(text="preview is not ready")
        return web.FileResponse(posixpath.join(job.directory, variant + ".mp4"), headers={**_FRESH, "Content-Type": "video/mp4"})

    @route("DELETE", "/join-preview/{id}")
    async def release(request: web.Request) -> web.Response:
        previews().release(request.match_info["id"])
        return web.json_response({"released": True}, headers=_FRESH)
