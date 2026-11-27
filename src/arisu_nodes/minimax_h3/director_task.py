"""Prepare a bounded Director task and enforce its writing-skill choices."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..common.media import MediaRef
from . import director
from .core import (
    CLIP_FRAME_STEP,
    FPS,
    MIN_CLIP_FRAMES,
    MOTION_WINDOWS,
    RESOURCE_LIMITS,
    ResourceBundle,
    h3_json,
)
from .director_media import director_video_ref, library_resources, segment_resources, validate_draft_media

ROLES = ("first", "last", "image", "video", "audio")
DIRECTOR_SKILL = "bundled:sequence-director"
MAX_SKILL_BYTES = 32 * 1024 * 1024


def _open_document(name: str, flags: int) -> int:
    return os.open(name, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))


def writing_catalog(skills: Dict[str, Path]) -> Dict[str, Dict[str, Any]]:
    """Describe discovered writing skills. Incomplete metadata allows manual selection only."""
    rows = {}
    for key, path in skills.items():
        if key == DIRECTOR_SKILL:
            continue
        row = {"id": key, "name": path.name, "purpose": "", "inputs": [], "characteristics": "", "automatic": False}
        try:
            with open(path / "director.json", "rb", opener=_open_document) as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
                    raise ValueError("invalid writing metadata")
                raw = f.read(8193)
                if len(raw) > 8192:
                    raise ValueError("invalid writing metadata")
                data = h3_json(raw)
            inputs = data["inputs"]
            if (
                isinstance(inputs, list)
                and len(inputs) <= len(ROLES)
                and all(role in ROLES for role in inputs)
                and all(isinstance(data[k], str) and 0 < len(data[k].strip()) <= 512 for k in ("purpose", "characteristics"))
            ):
                row.update(purpose=data["purpose"], characteristics=data["characteristics"], inputs=inputs, automatic=True)
        except (OSError, KeyError, TypeError, ValueError):
            pass
        rows[key] = row
    return rows


def copy_documents(source: Path, target: Path, remaining: int) -> int:
    """Snapshot only regular UTF-8 writing documents under the admitted skill directory."""
    if source.is_symlink():
        raise ValueError("Writing skill changed during preparation.")
    target.mkdir()
    for item in source.rglob("*"):
        if item.suffix.lower() not in (".md", ".txt") or item.is_dir():
            continue
        if item.is_symlink() or not item.resolve().is_relative_to(source.resolve()):
            raise ValueError("Writing skill changed during preparation.")
        with open(item, "rb", opener=_open_document) as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError("Invalid writing skill document.")
            data = f.read(min(1024 * 1024, remaining) + 1)
        if len(data) > min(1024 * 1024, remaining):
            raise ValueError("Writing skill documents exceed the single-task budget.")
        data.decode("utf-8")
        destination = target / item.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        remaining -= len(data)
    if not (target / "SKILL.md").is_file():
        raise ValueError("Writing skill changed during preparation.")
    return remaining


@dataclass
class DirectorTask:
    """One creative task frozen at submission, including the full reviewed plan."""

    document: Dict[str, Any]
    task: str
    request: str
    reselect: bool
    catalog: Dict[str, Dict[str, Any]]
    predecessor: Optional[MediaRef] = None
    prepared_document: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)

    @classmethod
    def capture(cls, value: Any, prompt: Any, node_id: str, skills: Dict[str, Path]) -> DirectorTask:
        """Capture the film and the optional previous take for a continuation revision."""
        if (
            not isinstance(value, dict)
            or set(value) - {"task", "request", "reselect_skill", "predecessor"}
            or value.get("task") not in ("plan", "refine")
        ):
            raise ValueError("Choose a whole-film plan or a segment revision.")
        task = value["task"]
        request, reselect = value.get("request", ""), value.get("reselect_skill", False)
        if not isinstance(request, str) or len(request) > 16384 or type(reselect) is not bool:
            raise ValueError("Invalid Director revision request.")
        node = prompt.get(node_id) if isinstance(prompt, dict) else None
        if (
            not isinstance(node, dict)
            or node.get("class_type") != "ArisuMiniMaxH3DirectorWorkbench"
            or not isinstance(node.get("inputs"), dict)
        ):
            raise ValueError("Select a Director Workbench.")
        inputs = node["inputs"]
        document = director.parse_document(inputs.get("film_json"))
        if task == "plan" and not document["film"]["brief"].strip():
            raise ValueError("Enter the film requirements before planning.")
        if task == "plan" and request.strip():
            raise ValueError("Edit the film requirements before replanning. Revision requests apply to one segment.")
        if task == "refine" and (not document["selected"] or not request.strip()):
            raise ValueError("Select a segment and enter a revision request.")
        catalog = writing_catalog(skills)
        selected = cls(document, task, request, reselect, catalog)
        forced = selected.fixed_choices()
        missing = [f"{segment}: {skill}" for segment, skill in forced.items() if skill and skill not in catalog]
        if missing:
            raise ValueError("Choose a replacement for the unavailable writing skill (" + ", ".join(missing) + ").")
        receipt = value.get("predecessor")
        if receipt is not None:
            if not isinstance(receipt, dict) or set(receipt) - {"revision"} != {"segment", "take", "project", "video"}:
                raise ValueError("Invalid Director predecessor receipt.")
            segments = document["segments"]
            index = next((i for i, segment in enumerate(segments) if segment["id"] == document["selected"]), -1)
            if (
                task != "refine"
                or index <= 0
                or segments[index]["transition"] != "continuation"
                or receipt["segment"] != segments[index - 1]["id"]
            ):
                raise ValueError("The predecessor must belong to the segment immediately before the selected continuation.")
            selected.predecessor = director_video_ref(receipt["take"], receipt["video"], receipt["project"])
        return selected

    def prepare_resources(self, roots: Mapping[str, str]) -> ResourceBundle:
        """Freeze the revisions inspected by the agent and each planning reference's effective soundtrack."""
        doc = self.document
        plan = self.task == "plan"
        resources = library_resources(doc, roots) if plan else segment_resources(doc, roots, doc["selected"])
        assets = {asset["id"]: asset for asset in doc["assets"]}
        for item in resources.sources():
            asset = {**assets[item.id], "revision": item.revision}
            if plan and item.kind == "video":
                asset["include_audio"] = item.include_audio
            assets[item.id] = asset
        self.prepared_document = {**doc, "assets": list(assets.values())}
        return resources

    def fixed_choices(self) -> Dict[str, str]:
        """Return writing skill restrictions for existing segments and newly planned segments."""
        film_skill = self.document["film"]["writing_skill"]
        chosen = {"New segments": film_skill} if self.task == "plan" else {}
        for segment in self.document["segments"]:
            if self.task == "refine" and segment["id"] != self.document["selected"]:
                continue
            if segment["skill_locked"]:
                chosen[segment["id"]] = segment["skill"]
            elif film_skill or self.task == "plan" or self.reselect:
                chosen[segment["id"]] = film_skill
            else:
                chosen[segment["id"]] = segment["skill"]
        return chosen

    def stage(self, target: Path, skills: Dict[str, Path], remaining: int) -> Dict[str, Any]:
        """Mount only eligible or explicitly requested writing documents and expose relative document paths."""
        source = skills.get(DIRECTOR_SKILL)
        if source is None:
            raise ValueError("The bundled sequence-director skill is unavailable.")
        remaining = copy_documents(source, target, min(remaining, MAX_SKILL_BYTES))
        fixed = set(self.fixed_choices().values())
        options = []
        (target / "writing").mkdir()
        for key, row in self.catalog.items():
            if key not in fixed and (not row["automatic"] or "" not in fixed):
                continue
            if key not in skills:
                raise ValueError(f"Writing skill {key} became unavailable. Generate again.")
            directory = "writing/" + str(len(options) + 1)
            remaining = copy_documents(skills[key], target / directory, remaining)
            options.append({**row, "path": directory + "/SKILL.md"})
        doc = self.prepared_document or self.document
        # Asset locations, revisions and render receipts are host data. Expose creative metadata only.
        return {
            "task": self.task,
            "request": self.request,
            "reselect_skill": self.reselect,
            "writing_skills": options,
            "film": doc["film"],
            "library": [
                {k: a[k] for k in ("id", "kind", "note", "muted", "crop", "crop_basis_ratio", "clip", "include_audio") if k in a}
                for a in doc["assets"]
                if not a.get("muted")
            ],
            "outline": doc["outline"],
            "continuity": doc["continuity"],
            "coverage": doc["coverage"],
            "segments": [
                {
                    k: s[k]
                    for k in (
                        "id",
                        "intent",
                        "seconds",
                        "transition",
                        "overlap_frames",
                        "prompt",
                        "opening",
                        "closing",
                        "bindings",
                        "skill",
                        "skill_reason",
                        "skill_locked",
                    )
                }
                for s in doc["segments"]
            ],
            "selected": doc["selected"],
            "limits": {
                "fps": FPS,
                "frame_grid_start": MIN_CLIP_FRAMES,
                "frame_grid_step": CLIP_FRAME_STEP,
                "overlap_windows": [int(value) for value in MOTION_WINDOWS],
                "max_segments": director.MAX_SEGMENTS,
                "max_bindings_per_role": {role: RESOURCE_LIMITS.get(role, 1) for role in ROLES},
                "max_result_utf8_bytes": director.RESULT_LIMIT,
            },
        }

    def result(self, text: str, roots: Mapping[str, str], *, attachment_sources: Optional[Mapping[str, str]] = None) -> str:
        """Validate one complete provider result and every selected writing skill against the submitted snapshot."""
        budget_error = "Director output exceeds the single-task 256 KiB budget. Shorten the brief or target runtime."
        if len(text) > director.RESULT_LIMIT + 32:
            raise ValueError(budget_error)
        fence = re.fullmatch(r"\s*```(?:json|text|markdown)?[ \t]*\r?\n([\s\S]*?)\r?\n```\s*", text)
        if len((fence[1] if fence else text).encode("utf-8")) > director.RESULT_LIMIT:
            raise ValueError(budget_error)
        if "ARISU_POLICY_REFUSAL" in text:
            raise ValueError("Request refused by Workbench policy.")
        if not fence or not fence[1].strip() or "```" in fence[1]:
            raise ValueError(
                "Invalid Director response format. Expected one JSON fence; text, markdown, or unlabeled fences are also accepted."
            )
        try:
            raw = h3_json(fence[1])
        except ValueError:
            raise ValueError("Incomplete or malformed Director JSON; a token limit has not been confirmed.") from None
        prepared = self.prepared_document or self.document
        result = director.validate_draft(
            self.document, self.task, raw, attachment_sources=attachment_sources, prepared_assets=prepared["assets"]
        )
        fixed = self.fixed_choices()
        rows: List[Dict[str, Any]] = result["segments"] if self.task == "plan" else [result["segment"]]
        for segment in rows:
            key = segment["skill"]
            required = fixed.get(segment["id"], self.document["film"]["writing_skill"])
            row = self.catalog.get(key)
            if not row or (required and key != required) or (not required and not row["automatic"]):
                raise ValueError(
                    f"Segment {segment['id']}: choose an available writing skill that respects the selection ({required or key})."
                )
            roles = {binding["role"] for binding in segment["bindings"]}
            if row["automatic"] and roles.difference(row["inputs"]):
                raise ValueError(f"Segment {segment['id']}: {key} does not support the bound asset roles.")
            if not required and not segment["skill_reason"].strip():
                raise ValueError(f"Segment {segment['id']}: explain the automatic skill selection.")
        validate_draft_media(prepared, result, self.task, roots)
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
