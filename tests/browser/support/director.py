"""Exercise Director's continuous render controls with a disposable two-take queue."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, Route, expect


def inspect_render_recovery(page: Page, director_id: str):
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
        first = page.get_by_role("button", name="1. Launch the paper boat", exact=False)
        second = page.get_by_role("button", name="2. Follow the boat", exact=False)
        first.click()
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
        files[saved]["video"] = "replaced"
        second.click()
        current.click()
        expect(status).to_contain_text("missing or has changed")
        assert len(jobs) == 3
        first.click()
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
