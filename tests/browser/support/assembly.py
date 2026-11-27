"""Walk the Assemble Video panel on the real frontend against the synthetic video routes."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from playwright.sync_api import Page, Route, expect

from tests.browser.support.harness import ASSEMBLY, OUTPUT_SPEC, PROJECT, FixtureServer, add_node, contained, screenshot


def edit(page: Page, node_id: str) -> Dict[str, Any]:
    """The saved edit list of the assembly node."""
    return json.loads(
        page.evaluate("id => window.comfyAPI.app.app.graph.getNodeById(id).widgets.find(w => w.name === 'edit_json').value", node_id)
    )


def names(page: Page) -> List[str]:
    """Row names in list order."""
    return page.locator(".arisu-assembly .entry .name").all_inner_texts()


def inspect_assembly(page: Page, server: FixtureServer, name: str):
    """Build an edit from three sources, check and export it, preview a join, delete a take, then import the workflow."""
    # The Director node stays in the workflow with its two project receipts; it only leaves the view.
    node_id = add_node(page, ASSEMBLY, clear=False)
    panel = page.locator(".arisu-assembly")
    expect(panel).to_be_visible()
    contained(page, ".arisu-assembly")
    page.evaluate(
        """([id, project]) => {
        const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id);
        const widget = node.widgets.find(w => w.name === 'project_prefix');
        widget.value = project; widget.callback?.(project);
        for (const hidden of ['edit_json', 'export_request'])
            if (!node.widgets.find(w => w.name === hidden).hidden) throw Error(hidden + ' is visible');
        if (node.inputs.some(input => ['edit_json', 'export_request'].includes(input.widget?.name ?? input.name))) throw Error('State has a socket');
        app.extensionManager.workflow.activeWorkflow.changeTracker.captureCanvasState();
    }""",
        [node_id, PROJECT],
    )
    panel.get_by_role("button", name="Refresh file states", exact=True).click()
    expect(panel.locator(".heading .label")).to_have_text("Project " + PROJECT)
    expect(panel.get_by_role("button", name="Export the film as a new version", exact=True)).to_be_disabled()
    screenshot(page, name, "assembly-empty")

    # An earlier take of the same segment keeps its own footage and record.
    earlier = "e7b6d3f0-9074-46f7-9676-0cbede38d651"
    launch = next(item for item in server.video_segments.values() if item["segment"] == "launch")
    server.video_segments[earlier] = {**launch, "take": earlier, "created": "2026-11-27T11:51:00Z"}
    server.video_directed.add(f"{PROJECT}/director/{earlier}/clip.mp4")
    # Project takes: several at once, with footage already in the edit marked.
    panel.get_by_role("button", name="Add published takes of the project", exact=True).click()
    picker = page.get_by_role("dialog", name="Takes of " + PROJECT, exact=True)
    expect(picker.get_by_role("listitem")).to_have_count(6)
    expect(picker.locator(".take .name").first).to_have_text("Segment 01")
    expect(picker.locator(".take .name").nth(2)).to_have_text("Segment 02")
    expect(picker).not_to_contain_text("Launch the paper boat")
    picker.get_by_label("Filter takes", exact=True).fill("paper boat")
    expect(picker.get_by_role("listitem")).to_have_count(2)
    expect(picker.get_by_role("listitem").first).to_contain_text("Director choice")
    preview = picker.get_by_role("button", name="Preview Segment 01", exact=False).first
    preview.focus()
    page.keyboard.press("Enter")
    expect(picker.locator("video:visible")).to_have_count(1)
    preview.click()
    expect(picker.locator("video:visible")).to_have_count(0)
    picker.get_by_label("Filter takes", exact=True).fill("")
    page.wait_for_function(
        "Array.from(document.querySelectorAll('.take-thumb img')).length === 6 && Array.from(document.querySelectorAll('.take-thumb img')).every(img => img.naturalWidth > 0)"
    )
    contained(page, "dialog.arisu-assembly-dialog")
    confirm = picker.get_by_role("button", name="Add Takes", exact=True)
    expect(confirm).to_be_disabled()
    picker.get_by_label("Select shot_00001_.mp4", exact=True).check()
    picker.get_by_label("Select shot_00002_.mp4", exact=True).check()
    picker.get_by_label("Filter takes", exact=True).fill("00003")
    expect(picker.get_by_role("listitem")).to_have_count(1)
    picker.get_by_label("Filter takes", exact=True).fill("")
    expect(picker.get_by_label("Select shot_00001_.mp4", exact=True)).to_be_checked()
    screenshot(page, name, "assembly-takes")
    picker.get_by_role("button", name="Add 2 Takes", exact=True).click()
    expect(panel.locator(".entry")).to_have_count(2)
    expect(panel.locator(".entry[data-state=ok]")).to_have_count(2)
    expect(panel.get_by_role("button", name="Add published takes of the project", exact=True)).to_be_focused()
    delete = panel.get_by_role("button", name="Delete the selected video files from disk", exact=True)
    for name_on_disk in ("shot_00001_.mp4", "shot_00002_.mp4"):
        selected = panel.get_by_label("Select " + name_on_disk, exact=True)
        expect(selected).to_be_checked()
        selected.uncheck()
    expect(delete).to_be_disabled()

    # Director footage arrives in film order with the take IDs of its receipts.
    panel.get_by_role("button", name="Import Director takes in film order", exact=True).click()
    expect(panel.locator(".status")).to_contain_text("Imported 2 takes in film order")
    expect(panel.locator(".entry[data-state=ok]")).to_have_count(4)
    imported = edit(page, node_id)["entries"][2:]
    assert [(row["source"], row["segment"]) for row in imported] == [
        ("director", "launch"),
        ("director", "follow"),
    ]
    assert all(row["path"].startswith(PROJECT + "/director/" + row["take"] + "/") for row in imported)

    # An existing video is added by browsing; only videos are offered.
    panel.get_by_role("button", name="Add a video file by browsing", exact=True).click()
    browser = page.locator("dialog[open].arisu-browser")
    expect(browser.locator(".arisu-browser-file")).to_have_count(1)
    expect(browser.locator(".arisu-browser-file")).to_contain_text("found.webm")
    screenshot(page, name, "assembly-browse")
    browser.locator(".arisu-browser-file").click()
    expect(panel.locator(".entry")).to_have_count(5)
    expect(panel.locator(".entry[data-state=ok]")).to_have_count(5)
    assert names(page) == [
        "shot_00001_.mp4",
        "shot_00002_.mp4",
        "Segment 01",
        "Segment 02",
        "found.webm",
    ]
    assert [row["source"] for row in edit(page, node_id)["entries"]] == ["take", "take", "director", "director", "file"]
    expect(panel.locator(".sum")).to_contain_text("5 of 5 · 240 frames · 10.00 s")

    # Reorder by dragging onto the upper half of the first row, then by keyboard with focus kept on the handle.
    order = names(page)
    rows = panel.locator(".entry")
    rows.nth(1).locator(".handle").drag_to(rows.nth(0), target_position={"x": 60, "y": 4})
    expect(panel.locator(".entry .name").first).to_have_text("shot_00002_.mp4")
    assert names(page) == [order[1], order[0], *order[2:]]
    handle = panel.get_by_role("button", name="Reorder shot_00001_.mp4 with the arrow keys", exact=True)
    handle.focus()
    handle.press("ArrowUp")
    expect(panel.get_by_role("button", name="Reorder shot_00001_.mp4 with the arrow keys", exact=True)).to_be_focused()
    assert names(page) == order
    screenshot(page, name, "assembly-row-focus")

    # Excluding keeps the row and drops it from the totals; Undo and Redo work from inside the panel.
    panel.get_by_role("button", name="Exclude shot_00001_.mp4", exact=True).click()
    expect(panel.locator(".entry.muted")).to_have_count(1)
    expect(panel.locator(".sum")).to_contain_text("4 of 5 · 192 frames")
    panel.get_by_role("button", name="Undo", exact=True).click()
    expect(panel.locator(".entry.muted")).to_have_count(0)
    expect(panel.locator(".sum")).to_contain_text("5 of 5")
    panel.get_by_role("button", name="Redo", exact=True).click()
    expect(panel.locator(".entry.muted")).to_have_count(1)
    # The history keys answer once from a focused row, and from a row checkbox, which ComfyUI itself skips.
    panel.get_by_role("button", name="Reorder found.webm with the arrow keys", exact=True).focus()
    page.keyboard.press("Control+z")
    expect(panel.locator(".entry.muted")).to_have_count(0)
    assert names(page) == order
    page.keyboard.press("Control+Shift+Z")
    expect(panel.locator(".entry.muted")).to_have_count(1)
    panel.get_by_label("Select found.webm", exact=True).focus()
    page.keyboard.press("Control+z")
    expect(panel.locator(".entry.muted")).to_have_count(0)
    assert names(page) == order
    page.keyboard.press("Control+y")
    expect(panel.locator(".entry.muted")).to_have_count(1)
    assert [row["included"] for row in edit(page, node_id)["entries"]] == [False, True, True, True, True]
    contained(page, ".arisu-assembly")
    screenshot(page, name, "assembly-list")

    # The export check names what must be decided; confirming the common output makes the plan ready.
    export = panel.get_by_role("button", name="Export the film as a new version", exact=True)
    panel.get_by_role("button", name="Check what the export will do", exact=True).click()
    plan = panel.get_by_role("region", name="Export check", exact=True)
    expect(plan).to_contain_text("192 frames")
    expect(plan).to_contain_text("The sources differ in size, frame rate or sound.")
    expect(export).to_be_disabled()
    screenshot(page, name, "assembly-needs")
    plan.locator(".need button").click()
    expect(plan.locator(".need")).to_have_count(0)
    expect(plan).to_contain_text("Video: encode h264 CRF 18")
    expect(plan).to_contain_text(f"To {PROJECT}/exports/main_00001/main_00001.mp4")
    assert edit(page, node_id)["output"] == OUTPUT_SPEC
    expect(export).to_be_enabled()
    contained(page, ".arisu-assembly")
    screenshot(page, name, "assembly-plan")

    # Export queues this node alone, with a request ID that exists only in the submitted prompt.
    submitted: List[Dict[str, Any]] = []
    history: Dict[str, Any] = {}

    def submit(route: Route):
        if route.request.method != "POST":
            route.fallback()
            return
        body = route.request.post_data_json
        submitted.append(body)
        target = body["partial_execution_targets"][0]
        film = f"{PROJECT}/exports/main_00001"
        history[body["prompt_id"]] = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                target: {
                    "images": [{"type": "output", "subfolder": film, "filename": "main_00001.mp4"}],
                    "animated": [True],
                    "arisu_project": [PROJECT],
                    "arisu_export": [
                        {
                            "request": body["prompt"][target]["inputs"]["export_request"],
                            "path": film + "/main_00001.mp4",
                            "name": "main",
                            "counter": 1,
                            "frames": 192,
                            "samples": 256000,
                            "duration": 8.0,
                        }
                    ],
                }
            },
        }
        route.fulfill(json={"prompt_id": body["prompt_id"]})

    def check_history(route: Route):
        key = route.request.url.rsplit("/", 1)[1]
        route.fulfill(json={key: history[key]} if key in history else {})

    page.route("**/api/prompt", submit)
    page.route("**/api/history/*", check_history)
    try:
        export.click()
        expect(panel.locator(".receipt")).to_have_text(f"Exported {PROJECT}/exports/main_00001/main_00001.mp4 · 192 frames")
    finally:
        page.unroute("**/api/prompt", submit)
        page.unroute("**/api/history/*", check_history)
    assert len(submitted) == 1
    job = submitted[0]
    assert job["partial_execution_targets"] == [node_id] and set(job["prompt"]) == {node_id}
    inputs = job["prompt"][node_id]["inputs"]
    assert inputs["export_request"] == job["prompt_id"] and inputs["project_prefix"] == PROJECT
    assert json.loads(inputs["edit_json"]) == edit(page, node_id)
    saved = page.evaluate(
        """id => {
        const node = window.comfyAPI.app.app.graph.getNodeById(id);
        return [node.widgets.find(w => w.name === 'export_request').value, node.serialize().widgets_values[6], node.properties.arisuAssembly];
    }""",
        node_id,
    )
    assert saved[0] == "" and saved[1] == "" and saved[2]["pending"] is None and saved[2]["last"]["request"] == job["prompt_id"]
    screenshot(page, name, "assembly-exported")

    # A join between a Director take and its verified predecessor: direct cut first, then the candidate.
    panel.get_by_role("button", name="Preview the join before Segment 02", exact=True).click()
    join = page.get_by_role("dialog", name="Preview Join", exact=True)
    expect(join).to_contain_text("Colour signalling matches on both sides.")
    player = join.locator("video")
    page.wait_for_function("document.querySelector('.arisu-assembly-dialog video').readyState >= 2")
    compare = join.get_by_role("button", name="Show Candidate", exact=True)
    expect(compare).to_be_disabled()
    match = join.get_by_label("Experimental: match colour across this join", exact=True)
    expect(match).to_be_enabled()
    match.check()
    switch = join.get_by_role("button", name="Show Direct Cut", exact=True)
    expect(switch).to_be_enabled()
    join.get_by_label("Click fade", exact=True).select_option("10")
    expect(switch).to_be_enabled()
    page.wait_for_function("document.querySelector('.arisu-assembly-dialog video').readyState >= 2")
    assert "variant=b" in player.get_attribute("src")
    switch.click()
    expect(join.get_by_role("button", name="Show Candidate", exact=True)).to_have_attribute("aria-pressed", "true")
    assert "variant=a" in player.get_attribute("src")
    contained(page, "dialog.arisu-assembly-dialog")
    screenshot(page, name, "assembly-join")
    join.get_by_role("button", name="Apply to This Join", exact=True).click()
    expect(panel.locator(".join").nth(1)).to_contain_text("Colour match · Fade 10 ms")
    stored = edit(page, node_id)["entries"][3]["join"]
    assert stored["fade"] == 10 and stored["correction"]["luma_offset"] == -0.02
    assert stored["correction"]["basis"] == {
        "prev_source": "output:" + imported[0]["path"],
        "prev_end": 48,
        "source": "output:" + imported[1]["path"],
        "start": 0,
    }
    previews = [body for kind, body in server.video_requests if kind == "join-preview"]
    assert [bool(body["join"]["correction"]) for body in previews] == [False, True, True] and previews[-1]["join"]["fade"] == 10
    assert "basis" not in previews[-1]["join"]["correction"] and not server.previews
    # A plain file has no known predecessor, so its join offers no colour match.
    panel.get_by_role("button", name="Preview the join before found.webm", exact=True).click()
    expect(join).to_contain_text("Available only when the incoming take continues the outgoing take.")
    expect(match).to_be_disabled()
    join.get_by_role("button", name="Cancel", exact=True).click()
    expect(join).to_have_count(0)

    # A plain video and Director footage can share a confirmation. Cancel keeps both files and rows.
    panel.get_by_label("Select found.webm", exact=True).check()
    panel.get_by_label("Select Segment 01", exact=True).check()
    delete.click()
    confirm = page.get_by_role("dialog", name="Delete Files from Disk", exact=True)
    expect(confirm.get_by_role("button", name="Delete 1 Folder and 5 Files", exact=True)).to_be_enabled()
    director_folder = "output:" + imported[0]["path"].rsplit("/", 1)[0] + "/"
    expect(confirm.get_by_text(director_folder, exact=True)).to_be_visible()
    expect(confirm).to_contain_text(director_folder + "clip.arisu/latent.safetensors")
    expect(confirm).to_contain_text("output:" + imported[0]["path"])
    expect(confirm).to_contain_text("output:" + edit(page, node_id)["entries"][-1]["path"])
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(panel.locator(".entry")).to_have_count(5)
    assert not server.video_deleted
    panel.get_by_label("Select Segment 01", exact=True).uncheck()
    panel.get_by_label("Select found.webm", exact=True).uncheck()
    panel.get_by_label("Select shot_00002_.mp4", exact=True).check()
    delete.click()
    expect(confirm.get_by_role("row")).to_have_count(5)
    expect(confirm).to_contain_text(PROJECT + "/videos/shot_00002_.arisu/audio.wav")
    contained(page, "dialog.arisu-assembly-dialog")
    screenshot(page, name, "assembly-delete")
    assert server.video_requests[-1] == (
        "delete",
        {
            "entries": [{"root": "output", "path": PROJECT + "/videos/shot_00002_.mp4", "revision": ""}],
            "confirm": False,
        },
    )
    confirm.get_by_role("button", name="Delete 1 Folder and 3 Files", exact=True).click()
    expect(panel.locator(".entry")).to_have_count(4)
    assert server.video_requests[-1][1]["confirm"] is True and server.video_deleted == {PROJECT + "/videos/shot_00002_.mp4"}
    panel.get_by_label("Select found.webm", exact=True).check()
    panel.get_by_role("button", name="Remove the selected rows from the edit; no file is touched", exact=True).click()
    expect(panel.locator(".entry")).to_have_count(3)
    assert [kind for kind, _ in server.video_requests].count("delete") == 3

    # An imported workflow keeps the order and take IDs but no location; one explicit action finds the takes again.
    page.evaluate("async () => { const app = window.comfyAPI.app.app; await app.loadGraphData(app.graph.serialize()); }")
    expect(panel.locator(".entry[data-state=unbound]")).to_have_count(3)
    unbound = edit(page, node_id)
    assert all(row["path"] == "" and "revision" not in row and row["take"] for row in unbound["entries"])
    assert all(row["join"] == {"correction": None, "fade": 0} for row in unbound["entries"])
    assert page.evaluate("id => window.comfyAPI.app.app.graph.getNodeById(id).properties.arisuAssembly ?? null", node_id) is None
    expect(panel.locator(".status")).to_contain_text("3 rows lost their files when this edit was imported or copied.")
    expect(export).to_be_disabled()
    contained(page, ".arisu-assembly")
    screenshot(page, name, "assembly-unbound")
    panel.get_by_role("button", name="Find these takes again in the project", exact=True).click()
    expect(panel.locator(".status")).to_contain_text("Rebound 3 of 3 rows from " + PROJECT)
    expect(panel.locator(".entry[data-state=ok]")).to_have_count(3)
    assert (
        server.video_requests[-2] == ("takes", {"project": PROJECT, "legacy": "1"})
        or ("takes", {"project": PROJECT, "legacy": "1"}) in server.video_requests
    )
    screenshot(page, name, "assembly-rebound")
