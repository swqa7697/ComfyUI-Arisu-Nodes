"""Exercise Director's continuous render controls with a disposable two-take queue."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, Route, expect

from tests.browser.support.harness import FixtureServer


def edit_segment(page: Page, section: str = "Prompt"):
    """Enter a section through the public segment editor controls."""
    if not page.get_by_role("dialog", name="Edit Segment", exact=True).count():
        page.get_by_role("button", name="Edit Segment", exact=True).click()
    page.get_by_role("tab", name=section, exact=True).click()


def inspect_render_recovery(page: Page, director_id: str, server: FixtureServer):
    """Exercise render recovery with the execution links consumed by the Director controls."""

    def node(kind: str, **inputs: Any) -> Dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    loader, save, latent = "previous", "save_video", "save_latent"
    output = {
        director_id: node("ArisuMiniMaxH3DirectorWorkbench"),
        "hybrid": node("ArisuMiniMaxH3HybridToVideo", prompt=[director_id, 0], video_settings=[director_id, 1], resources=[director_id, 2]),
        loader: node("MiniMaxH3MotionContextLoadLatent"),
        "motion": node("MiniMaxH3MotionContext", context_latent=[loader, 0], conditioning=["hybrid", 0], latent=["hybrid", 1]),
        "sampler": node("KSampler", positive=["motion", 0], latent_image=["hybrid", 1]),
        latent: node("MiniMaxH3MotionContextSaveLatent", latent=["sampler", 0]),
        "picture": node("VAEDecode", samples=["sampler", 0]),
        "sound": node("VAEDecodeAudio", samples=["sampler", 0]),
        "trim": node("MiniMaxH3MotionContextTrim", images=["picture", 0], audio=["sound", 0], trim_frames=["motion", 1]),
        "video": node("CreateVideo", images=["trim", 0], audio=["trim", 1]),
        save: node("SaveVideo", video=["video", 0]),
    }

    jobs: List[Dict[str, Any]] = []
    history: Dict[str, Any] = {}
    files: Dict[str, Any] = {}
    fail = True
    normal_runs = []

    def submit(route: Route):
        if route.request.method != "POST":
            route.fallback()
            return
        body = route.request.post_data_json
        graph = body["prompt"]
        if graph[save]["inputs"].get("filename_prefix") == "arisu_director/manual/clip":
            normal_runs.append(graph[loader]["inputs"].copy())
            route.fulfill(json={"prompt_id": "682f6981-6acc-49a0-bfcc-a2a73be4a121", "number": 1, "node_errors": {}})
            return
        key = body["prompt_id"]
        selected = json.loads(graph[director_id]["inputs"]["film_json"])["selected"]
        subfolder = "arisu_director/" + key
        assert graph[save]["inputs"]["filename_prefix"] == graph[latent]["inputs"]["filename_prefix"] == subfolder + "/clip"
        assert set(body["partial_execution_targets"]) == {save, latent}
        jobs.append({"segment": selected, "previous": graph[loader]["inputs"], "id": key})
        success = selected != "follow" or not fail
        history[key] = {
            "status": {"status_str": "success" if success else "error", "completed": success},
            "outputs": {
                save: {"images": [{"type": "output", "subfolder": subfolder, "filename": "clip_00001_.mp4"}]},
                latent: {"latents": [{"type": "output", "subfolder": subfolder, "filename": "clip_00001.safetensors"}]},
            },
        }
        if success:
            files[key] = {"video": "video-revision", "latent": "latent-revision"}
        route.fulfill(json={"prompt_id": key})

    def check_history(route: Route):
        key = route.request.url.rsplit("/", 1)[1]
        route.fulfill(json={key: history[key]} if key in history else {})

    def check_file(route: Route):
        key = parse_qs(urlsplit(route.request.url).query)["take"][0]
        route.fulfill(json=files.get(key, {}))

    page.route("**/api/prompt", submit)
    page.route("**/api/history/*", check_history)
    page.route("**/api/arisu/resources/director-take?*", check_file)
    page.evaluate(
        """async graph => {
        const {app}=await import('/scripts/app.js'), {api}=await import('/scripts/api.js');
        const toPrompt=app.graphToPrompt, fetch=api.fetchApi;
        window.restoreDirectorFixture=()=>{app.graphToPrompt=toPrompt;api.fetchApi=fetch;};
        app.graphToPrompt=async()=>({output:graph});
        api.fetchApi=async function(path,...rest) {
            const result=await fetch.call(this,path,...rest);
            if(path==='/prompt' && window.dropDirectorResponse) {
                window.dropDirectorResponse=false;
                throw Error('Connection lost after submission');
            }
            return result;
        };
    }""",
        output,
    )
    try:
        first = page.get_by_role("button", name="01 Launch the paper boat", exact=False)
        second = page.get_by_role("button", name="02 Follow the boat", exact=False)
        first.click()
        page.keyboard.press("Escape")
        remaining = page.get_by_role("button", name="Render remaining segments", exact=True)
        current = page.get_by_role("button", name="Render current segment", exact=True)
        status = page.locator(".arisu-director .status")
        remaining.click()
        expect(status).to_contain_text("Retry segment “follow”")
        expect(first).to_contain_text("Rendered")
        expect(second).to_contain_text("Pending")
        saved = jobs[0]["id"]
        assert jobs[0]["previous"]["clip_index"] == 0
        fail = False
        remaining.click()
        expect(second).to_contain_text("Rendered")
        assert [job["segment"] for job in jobs] == ["launch", "follow", "follow"]
        assert jobs[2]["previous"]["latent_path"] == f"arisu_director/{saved}/clip_00001.safetensors"
        remaining.click()
        expect(remaining).to_be_enabled()
        assert len(jobs) == 3
        second.click()
        page.keyboard.press("Escape")
        page.evaluate(
            """async ([id, save]) => {
              const {app} = await import('/scripts/app.js'), {api} = await import('/scripts/api.js');
              const node = app.graph.getNodeById(id);
              node.properties.arisuDirectorTemplate = true;
              const {output} = await app.graphToPrompt();
              output[id].inputs.film_json = node.widgets.find(widget => widget.name === 'film_json').value;
              output[save].inputs.filename_prefix = 'arisu_director/manual/clip';
              await api.queuePrompt(0, {output, workflow: app.graph.serialize()});
              delete node.properties.arisuDirectorTemplate;
            }""",
            [director_id, save],
        )
        assert len(normal_runs) == 1 and normal_runs[0]["latent_path"] == jobs[2]["previous"]["latent_path"]
        # Use the same predecessor receipt for the revision. The agent may see its actual tail only with valid wiring.
        edit_segment(page, "Revise Prompt")
        revision = page.get_by_role("dialog", name="Edit Segment", exact=True)
        unavailable = revision.get_by_text("Using the film plan. Previous tail frames are unavailable.", exact=True)
        expect(unavailable).to_be_visible()
        page.keyboard.press("Escape")
        page.evaluate(
            """id => {
                const graph = window.comfyAPI.app.app.graph, target = graph.getNodeById(id);
                for (const [type, port] of [['MiniMaxH3MotionContextLoadLatent','context_latent'], ['VAELoader','vae']]) {
                    const slot = target.inputs.findIndex(input => input.name === port);
                    class Source extends LGraphNode {
                        constructor() { super(); this.comfyClass = type; this.addOutput(port, target.inputs[slot].type); }
                    }
                    const fixture = 'FixtureDirector' + type;
                    LiteGraph.registerNodeType(fixture, Source);
                    const source = LiteGraph.createNode(fixture);
                    source.pos = [-1000, -1000]; graph.add(source); source.connect(0, target, slot);
                }
            }""",
            director_id,
        )
        edit_segment(page, "Revise Prompt")
        expect(revision.get_by_text("Tail frames from segment 1 are available for this revision.", exact=True)).to_be_visible()
        instructions = revision.get_by_label("What should change in segment 2?", exact=True)
        instructions.fill("Match the bow position in the preceding take.")
        submit_revision = revision.get_by_role("button", name="Refine current segment", exact=True)
        with page.expect_response("**/arisu/workbench/generate"):
            submit_revision.click()
        expect(status).to_contain_text("Output ready to apply")
        refinement = server.generation_requests[-1]
        assert refinement["options"]["motion_enabled"] and refinement["options"]["context_length"] == "22"
        assert not refinement["options"].get("motion_audio_notes") and not refinement["options"].get("motion_notes")
        graph = refinement["prompt"]
        source = graph[refinement["node_id"]]["inputs"]["context_latent"][0]
        assert graph[source]["inputs"]["latent_path"] == jobs[2]["previous"]["latent_path"]
        edit_segment(page, "Revise Prompt")
        expect(instructions).to_have_value("")
        expect(revision.get_by_text("Tail frames from segment 1 are available for this revision.", exact=True)).to_be_visible()
        # The take can change while the editor is open. Submission must recheck it and fall back to the film.
        files[saved]["video"] = "replaced"
        instructions.fill("Continue from the planned closing pose.")
        with page.expect_response("**/arisu/workbench/generate"):
            submit_revision.click()
        expect(status).to_contain_text("Output ready to apply")
        fallback = server.generation_requests[-1]
        assert not fallback["options"]["motion_enabled"]
        assert set(fallback["prompt"]) == {fallback["node_id"]}
        edit_segment(page, "Revise Prompt")
        expect(unavailable).to_be_visible()
        page.keyboard.press("Escape")
        second.click()
        page.keyboard.press("Escape")
        current.click()
        expect(status).to_contain_text("missing or has changed")
        assert len(jobs) == 3
        first.click()
        page.keyboard.press("Escape")
        page.evaluate("window.dropDirectorResponse=true")
        current.click()
        expect(status).to_contain_text("Connection lost after submission")
        current.click()
        expect(second).to_contain_text("Needs rerender")
        expect(first).to_contain_text("Rendered")
        assert len(jobs) == 4 and jobs[-1]["id"] != saved
    finally:
        page.evaluate("window.restoreDirectorFixture()")
        page.unroute("**/api/prompt", submit)
        page.unroute("**/api/history/*", check_history)
        page.unroute("**/api/arisu/resources/director-take?*", check_file)


def inspect_project_render(page: Page, server: FixtureServer, director_id: str):
    """Render the film through Save Video Segment into a project, then lose one latent.

    The saver's project comes from a wired Path Builder, so takes go to ``<project>/director/<take>``.
    The receipts stay on the node afterwards for the assembly import.
    """

    def node(kind: str, **inputs: Any) -> Dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    loader, save, latent, project = "previous", "save_segment", "save_latent", "films/night shoot"
    output = {
        director_id: node("ArisuMiniMaxH3DirectorWorkbench"),
        "hybrid": node("ArisuMiniMaxH3HybridToVideo", prompt=[director_id, 0], video_settings=[director_id, 1], resources=[director_id, 2]),
        loader: node("MiniMaxH3MotionContextLoadLatent"),
        "motion": node("MiniMaxH3MotionContext", context_latent=[loader, 0], conditioning=["hybrid", 0], latent=["hybrid", 1]),
        "sampler": node("KSampler", positive=["motion", 0], latent_image=["hybrid", 1]),
        latent: node("MiniMaxH3MotionContextSaveLatent", latent=["sampler", 0]),
        "picture": node("VAEDecode", samples=["sampler", 0]),
        "sound": node("VAEDecodeAudio", samples=["sampler", 0]),
        "trim": node("MiniMaxH3MotionContextTrim", images=["picture", 0], audio=["sound", 0], trim_frames=["motion", 1]),
        "video": node("CreateVideo", images=["trim", 0], audio=["trim", 1]),
        "paths": node("ArisuPathBuilder", segment_1="films", segment_2=" night shoot/"),
        save: node(
            "ArisuSaveVideoSegment",
            video=["video", 0],
            project_prefix=["paths", 0],
            clip_name="clip",
            codec="h264",
            crf=18,
            take_context="",
        ),
    }
    jobs: List[Dict[str, Any]] = []
    history: Dict[str, Any] = {}
    files: Dict[str, Any] = {}
    asked: List[Dict[str, List[str]]] = []

    def submit(route: Route):
        if route.request.method != "POST":
            route.fallback()
            return
        body = route.request.post_data_json
        graph, key = body["prompt"], body["prompt_id"]
        subfolder = f"{project}/director/{key}"
        # The take context locates the video; the latent uses the same project directory.
        assert "filename_prefix" not in graph[save]["inputs"]
        assert graph[latent]["inputs"]["filename_prefix"] == subfolder + "/clip"
        assert graph[latent]["inputs"]["clip_index"] == 1 and set(body["partial_execution_targets"]) == {save, latent}
        jobs.append({"id": key, "previous": graph[loader]["inputs"], "context": json.loads(graph[save]["inputs"]["take_context"])})
        history[key] = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                # The saver claims its own counter, so the video is not assumed to be number one.
                save: {"images": [{"type": "output", "subfolder": subfolder, "filename": "clip_00002_.mp4"}]},
                latent: {"latents": [{"type": "output", "subfolder": subfolder, "filename": "clip_00001.safetensors"}]},
            },
        }
        files[key] = {"video": "video-revision", "latent": "latent-revision"}
        route.fulfill(json={"prompt_id": key})

    def check_history(route: Route):
        key = route.request.url.rsplit("/", 1)[1]
        route.fulfill(json={key: history[key]} if key in history else {})

    def check_file(route: Route):
        query = parse_qs(urlsplit(route.request.url).query)
        asked.append(query)
        route.fulfill(json=files.get(query["take"][0], {}))

    page.route("**/api/prompt", submit)
    page.route("**/api/history/*", check_history)
    page.route("**/api/arisu/resources/director-take?*", check_file)
    page.evaluate(
        """async graph => {
        const {app}=await import('/scripts/app.js');
        const toPrompt=app.graphToPrompt;
        window.directorProjectGraph=graph;
        window.restoreDirectorFixture=()=>{app.graphToPrompt=toPrompt;};
        app.graphToPrompt=async()=>({output:graph});
    }""",
        output,
    )
    try:
        first = page.get_by_role("button", name="01 Launch the paper boat", exact=False)
        second = page.get_by_role("button", name="02 Follow the boat", exact=False)
        first.click()
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Render remaining segments", exact=True).click()
        expect(first).to_contain_text("Rendered")
        expect(second).to_contain_text("Rendered")
        assert len(jobs) == 2
        launch, follow = jobs
        assert launch["context"] == {"take": launch["id"], "segment": "launch", "predecessor": None, "transition": "cut"}
        assert follow["context"] == {"take": follow["id"], "segment": "follow", "predecessor": launch["id"], "transition": "continuation"}
        assert launch["previous"]["latent_path"] == f"{project}/director" and launch["previous"]["clip_index"] == 0
        assert follow["previous"]["latent_path"] == f"{project}/director/{launch['id']}/clip_00001.safetensors"
        # The file check names the project, and the take context was written only into the submitted copies.
        mine = [query for query in asked if query["take"][0] in files]
        assert mine and all(query["project"] == [project] and query["video"] == ["clip_00002_.mp4"] for query in mine)
        # Receipts of the earlier stock-saver renders are still checked at their original location.
        legacy = [query for query in asked if query["take"][0] not in files]
        assert legacy and all("project" not in query and query["video"] == ["clip_00001_.mp4"] for query in legacy)
        assert page.evaluate("id => window.directorProjectGraph[id].inputs", save)["take_context"] == ""
        assert "filename_prefix" not in page.evaluate("id => window.directorProjectGraph[id].inputs", save)
        receipts = page.evaluate("id => window.comfyAPI.app.app.graph.getNodeById(id).properties.directorRenders.takes", director_id)
        assert [(take["project"], take["saver"], take["video"]["subfolder"]) for take in receipts] == [
            (project, "ArisuSaveVideoSegment", f"{project}/director/{launch['id']}"),
            (project, "ArisuSaveVideoSegment", f"{project}/director/{follow['id']}"),
        ]
        # A removed latent ends the take's use as a predecessor, not its footage: a trusted reopen reports it.
        files[launch["id"]] = {"video": "video-revision"}
        page.evaluate(
            """async () => {
            const app = window.comfyAPI.app.app;
            await app.loadGraphData(app.graph.serialize(), true, true, app.extensionManager.workflow.activeWorkflow);
        }"""
        )
        expect(first).to_contain_text("Latent removed")
        expect(second).to_contain_text("Rendered")
    finally:
        # The receipts outlive this fixture: later trusted reloads of the workflow check the same files on the host.
        server.director_takes.update(files)
        page.evaluate("window.restoreDirectorFixture(); delete window.directorProjectGraph;")
        page.unroute("**/api/prompt", submit)
        page.unroute("**/api/history/*", check_history)
        page.unroute("**/api/arisu/resources/director-take?*", check_file)
