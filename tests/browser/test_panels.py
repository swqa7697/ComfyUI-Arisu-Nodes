"""Real-browser regression journeys for the two custom MiniMax panels."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from playwright.sync_api import Locator, Page, expect, sync_playwright

from tests.browser.support.harness import DRAFT, STUDIO, WORKBENCH, FixtureServer, add_node, browser_page, screenshot

pytestmark = pytest.mark.browser


def widget_value(page: Page, node_id: str, name: str) -> Any:
    return page.evaluate(
        """([id, name]) => window.comfyAPI.app.app.graph.getNodeById(id).widgets.find(w => w.name === name).value""", [node_id, name]
    )


def studio_state(page: Page, node_id: str) -> Dict[str, Any]:
    return json.loads(widget_value(page, node_id, "resources_json"))


def contained(page: Page, selector: str):
    """Assert the rendered panel/dialog fits the viewport without horizontal clipping."""
    box = page.locator(selector).bounding_box()
    assert box and box["width"] > 0 and box["height"] > 0
    viewport = page.viewport_size
    assert box["x"] >= 0 and box["y"] >= 0, box
    assert box["x"] + box["width"] <= viewport["width"] + 1, box
    assert box["y"] + box["height"] <= viewport["height"] + 1, box
    assert page.locator(selector).evaluate("e => e.scrollWidth <= e.clientWidth + 1")


def pick(page: Page, name: str):
    page.locator("dialog[open] .arisu-browser-file").filter(has_text=name).click()


def hover_button(page: Page, button: Locator, name: str, state: str):
    """Check actual pointer feedback and its reset, without a stored pixel baseline."""
    page.mouse.move(10, 10)
    normal = button.evaluate("e => getComputedStyle(e).backgroundColor")
    button.hover()
    expect(button).not_to_have_css("background-color", normal)
    screenshot(page, name, state)
    page.mouse.move(10, 10)
    expect(button).to_have_css("background-color", normal)


def inspect_native_nodes(page: Page, name: str):
    """Exercise the native widgets and settings dialogs alongside the custom panels."""
    definitions = page.evaluate("async () => (await fetch('/object_info')).json()")
    for node_type in definitions:
        if node_type in (STUDIO, WORKBENCH):
            continue
        node_id = add_node(page, node_type)
        # Defaults come from the real Colors menu. Workflow restoration must win
        # over them when the workflow carries saved custom colors.
        page.evaluate(
            """id => {
            const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id);
            const name = node.type === 'ArisuLoadImage' ? 'red' :
                node.type.startsWith('ArisuPreviewSaveImage') ? 'yellow' : null;
            if (name) {
                const preset = app.canvas.constructor.node_colors[name];
                if (node.color !== preset.color || node.bgcolor !== preset.bgcolor) throw Error('Wrong node preset');
                const saved = node.serialize();
                node.configure({...saved, color:'#123456', bgcolor:'#234567'});
                if (node.color !== '#123456' || node.bgcolor !== '#234567') throw Error('Lost custom color');
                node.configure(saved);
            }
        }""",
            node_id,
        )
        screenshot(page, name, node_type)
        # Canvas buttons have no DOM :hover. Sample their actual fill pixels
        # before/after pointer entry and exit, including both Path Builder cells.
        points = page.evaluate(
            """id => {
            const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id), ds = app.canvas.ds;
            const rect = app.canvas.canvas.getBoundingClientRect();
            return (node.widgets ?? []).filter(w => ['button','arisu_button_row'].includes(w.type)).flatMap(w => {
                const xs = w.type === 'arisu_button_row' ? [25, node.size[0] / 2 + 10] : [25];
                return xs.map(x => [(node.pos[0] + x + ds.offset[0]) * ds.scale + rect.left,
                    (node.pos[1] + w.last_y + 4 + ds.offset[1]) * ds.scale + rect.top]);
            });
        }""",
            node_id,
        )
        sample = """([x,y]) => {
            const canvas = document.querySelector('#graph-canvas'), rect = canvas.getBoundingClientRect();
            return Array.from(canvas.getContext('2d').getImageData(
                (x - rect.left) * canvas.width / rect.width, (y - rect.top) * canvas.height / rect.height, 1, 1).data).join(',');
        }"""
        for index, point in enumerate(points):
            page.mouse.move(10, 10)
            normal = page.evaluate(sample, point)
            page.mouse.move(*point)
            page.wait_for_function("([point,normal]) => (" + sample + ")(point) !== normal", arg=[point, normal])
            screenshot(page, name, node_type + f"-hover-{index}")
            page.mouse.move(10, 10)
            page.wait_for_function("([point,normal]) => (" + sample + ")(point) === normal", arg=[point, normal])
        # Click each settings widget at its actual canvas position.
        controls = page.evaluate(
            """id => {
            const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id), ds = app.canvas.ds;
            const rect = app.canvas.canvas.getBoundingClientRect();
            return (node.widgets ?? []).filter(w => w.type === 'button' && ['Settings…','Keyframes…'].includes(w.name)).map(w => [
                (node.pos[0] + node.size[0] / 2 + ds.offset[0]) * ds.scale + rect.left,
                (node.pos[1] + w.last_y + 10 + ds.offset[1]) * ds.scale + rect.top
            ]);
        }""",
            node_id,
        )
        for x, y in controls:
            page.mouse.click(x, y)
            expect(page.locator(".arisu-settings[open]")).to_be_visible()
            contained(page, ".arisu-settings[open]")
            screenshot(page, name, node_type + "-settings")
            page.keyboard.press("Escape")
            expect(page.locator(".arisu-settings[open]")).to_have_count(0)


def test_resource_studio():
    # One journey, repeated at two usable desktop viewports without multiplying test cases.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((1440, 900), (1024, 768)):
                name = f"studio-{width}"
                with FixtureServer() as server, browser_page(browser, server, name, width, height) as page:
                    inspect_native_nodes(page, name)
                    node_id = add_node(page, STUDIO)
                    expect(page.locator(".arisu-studio")).to_be_visible()
                    contained(page, ".arisu-studio")
                    screenshot(page, name, "empty")
                    page.get_by_role("button", name="First Frame", exact=True).click()
                    expect(page.locator("dialog[open]")).to_be_visible()
                    contained(page, "dialog[open]")
                    screenshot(page, name, "Browse")
                    pick(page, "scene.png")
                    expect(page.locator(".arisu-studio img")).to_be_visible()
                    assert studio_state(page, node_id)["keyframes"]["first"]["path"] == "scene.png"
                    page.get_by_role("button", name="Crop", exact=True).click()
                    page.locator(".arisu-cropper-ratio").select_option("1:1")
                    contained(page, "dialog[open]")
                    screenshot(page, name, "crop")
                    hover_button(page, page.get_by_role("button", name="Reset", exact=True), name, "crop-reset-hover")
                    hover_button(page, page.get_by_role("button", name="Auto-Crop", exact=True), name, "crop-auto-hover")
                    page.get_by_role("button", name="Apply", exact=True).click()
                    page.wait_for_function(
                        """id => {
                        const data = JSON.parse(window.comfyAPI.app.app.graph.getNodeById(id).widgets.find(w => w.name === 'resources_json').value);
                        return data.keyframes.first.crop?.width === data.keyframes.first.crop?.height;
                    }""",
                        arg=node_id,
                    )
                    crop = studio_state(page, node_id)["keyframes"]["first"]["crop"]
                    assert crop["width"] == crop["height"] and crop["width"] > 0
                    page.get_by_role("button", name="Browse References…", exact=True).click()
                    pick(page, "sound.wav")
                    expect(page.get_by_label("Start Seconds")).to_be_visible()
                    page.get_by_label("Start Seconds").fill("1")
                    page.get_by_label("Start Seconds").press("Tab")
                    page.get_by_label("End Seconds").fill("4")
                    page.get_by_label("End Seconds").press("Tab")
                    contained(page, "dialog[open]")
                    screenshot(page, name, "clip")
                    page.get_by_role("button", name="Apply", exact=True).click()
                    expect(page.get_by_role("button", name="Edit audio sound.wav", exact=True)).to_be_visible()
                    assert studio_state(page, node_id)["references"][0]["clip"] == {"start": 1, "end": 4}
                    # More rows than the panel can display exercise real scrolling.
                    for index in range(2, 10):
                        page.get_by_role("button", name="Browse References…", exact=True).click()
                        pick(page, f"scene-{index}.png")
                        expect(page.get_by_role("button", name=f"Edit image scene-{index}.png", exact=True)).to_be_attached()
                    references = page.locator(".arisu-studio .references")
                    references.hover()
                    page.mouse.wheel(0, 600)
                    page.wait_for_function("document.querySelector('.arisu-studio .references').scrollTop > 0")
                    screenshot(page, name, "populated")
                    page.get_by_role("button", name="Edit image scene-9.png", exact=True).focus()
                    page.keyboard.press("Tab")
                    assert page.evaluate("!!document.activeElement.closest('.arisu-studio .reference')")
                    screenshot(page, name, "row-focus")
                    # Drag the real canvas resize handle and verify its DOM widget follows.
                    before_size = page.evaluate("id => Array.from(window.comfyAPI.app.app.graph.getNodeById(id).size)", node_id)
                    corner = page.evaluate(
                        """id => {
                        const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id), ds = app.canvas.ds;
                        const rect = app.canvas.canvas.getBoundingClientRect();
                        return [(node.pos[0] + node.size[0] + ds.offset[0]) * ds.scale + rect.left - 3,
                                (node.pos[1] + node.size[1] + ds.offset[1]) * ds.scale + rect.top - 3];
                    }""",
                        node_id,
                    )
                    page.mouse.move(*corner)
                    page.mouse.down()
                    page.mouse.move(corner[0] + 80, corner[1] + 30, steps=10)
                    page.mouse.up()
                    after_size = page.evaluate("id => Array.from(window.comfyAPI.app.app.graph.getNodeById(id).size)", node_id)
                    assert after_size[0] > before_size[0] and after_size[1] > before_size[1]
                    contained(page, ".arisu-studio")
                    screenshot(page, name, "resized")
                    # Canvas input is real: wheel zoom and middle-button pan over the node's DOM.
                    before = page.evaluate("window.comfyAPI.app.app.canvas.ds.scale")
                    page.get_by_role("button", name="First Frame", exact=True).hover()
                    page.mouse.wheel(0, 150)
                    page.wait_for_function("scale => window.comfyAPI.app.app.canvas.ds.scale !== scale", arg=before)
                    offset = page.evaluate("Array.from(window.comfyAPI.app.app.canvas.ds.offset)")
                    page.mouse.down(button="middle")
                    page.mouse.move(425, 365, steps=5)
                    page.mouse.up(button="middle")
                    assert page.evaluate("Array.from(window.comfyAPI.app.app.canvas.ds.offset)") != offset
                    contained(page, ".arisu-studio")
                    screenshot(page, name, "canvas")
        finally:
            browser.close()


def test_prompt_workbench():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((1440, 900), (1024, 768)):
                name = f"workbench-{width}"
                with FixtureServer() as server, browser_page(browser, server, name, width, height) as page:
                    expect(page.get_by_role("button", name="Manage Agents", exact=True)).to_have_count(0)
                    node_id = add_node(page, WORKBENCH)
                    expect(page.get_by_role("button", name="Generate Prompt", exact=True)).to_be_enabled()
                    contained(page, ".arisu-workbench")
                    page.get_by_label("Requirements", exact=True).fill("Follow a paper boat across a pond.")
                    page.get_by_label("LoRA Trigger Words", exact=True).fill("paper_art")
                    page.get_by_label("Finalized Prompt", exact=True).fill("Original prompt")
                    screenshot(page, name, "editing")
                    generate = page.get_by_role("button", name="Generate Prompt", exact=True)
                    results = page.get_by_role("button", name="Generation Results", exact=True)
                    assert generate.evaluate("e => getComputedStyle(e).backgroundColor") != results.evaluate(
                        "e => getComputedStyle(e).backgroundColor"
                    )
                    hover_button(page, results, name, "results-hover")
                    hover_button(page, generate, name, "generate-hover")
                    # Keyboard changes keep focus on the rebuilt selector, then advance naturally.
                    agent = page.get_by_label("Agent", exact=True)
                    agent.click()
                    page.keyboard.press("Escape")
                    agent.press("Home")
                    agent.press("ArrowDown")
                    expect(agent).to_have_value("grok")
                    expect(agent).to_be_focused()
                    agent.press("Home")
                    expect(agent).to_have_value("codex")
                    agent.press("Tab")
                    expect(page.get_by_label("Skill", exact=True)).to_be_focused()
                    screenshot(page, name, "selector-focus")
                    page.keyboard.press("Tab")
                    requirements = page.get_by_label("Requirements", exact=True)
                    expect(requirements).to_be_focused()
                    requirements.press("End")
                    requirements.press("Space")
                    page.keyboard.insert_text("Keep the lighting soft.")
                    assert "Keep the lighting soft." in widget_value(page, node_id, "requirements")
                    screenshot(page, name, "requirements-focus")
                    requirements.press("Tab")
                    expect(page.get_by_label("LoRA Trigger Words", exact=True)).to_be_focused()
                    screenshot(page, name, "trigger-focus")
                    page.locator(".arisu-workbench summary").click()
                    expect(page.get_by_label("Audio Context Length in Frames")).to_be_disabled()
                    screenshot(page, name, "motion-expanded")
                    page.locator(".arisu-workbench summary").click()
                    expect(page.get_by_role("button", name="Generation Results", exact=True)).to_be_enabled()
                    page.get_by_role("button", name="Generation Results", exact=True).click()
                    empty_results = page.get_by_role("dialog", name="Generation Results", exact=True)
                    empty_results.get_by_role("tab", name="Output Prompt", exact=True).click()
                    expect(empty_results.get_by_role("textbox", name="Output Prompt", exact=True)).to_have_value("")
                    expect(empty_results.get_by_role("button", name="Apply to Workbench")).to_be_disabled()
                    screenshot(page, name, "empty-results")
                    empty_results.get_by_role("button", name="Close", exact=True).click()
                    server.hold_generation = True
                    page.get_by_role("button", name="Generate Prompt", exact=True).click()
                    expect(page.locator(".arisu-workbench .status")).to_have_text("Generating prompt…")
                    screenshot(page, name, "generating")
                    assert page.locator(".arisu-workbench .status").evaluate(
                        "e => getComputedStyle(e, '::before').animationName === 'none'"
                    )
                    page.emulate_media(reduced_motion="no-preference")
                    assert page.locator(".arisu-workbench .status").evaluate(
                        "e => getComputedStyle(e, '::before').animationName !== 'none'"
                    )
                    page.emulate_media(reduced_motion="reduce")
                    page.get_by_role("button", name="Generation Results", exact=True).click()
                    activity = page.get_by_role("dialog", name="Generation Results", exact=True)
                    terminal = activity.get_by_label("Generation Activity", exact=True)
                    expect(terminal).to_contain_text("workbench.read_image")
                    assert len(terminal.inner_text()) > 10000
                    assert terminal.evaluate("e => e.scrollTop > 0 && e.scrollHeight - e.clientHeight - e.scrollTop < 30")
                    contained(page, ".arisu-activity-modal")
                    screenshot(page, name, "activity-following")
                    terminal.hover()
                    page.mouse.wheel(0, -10000)
                    expect(activity.get_by_role("button", name="Resume Auto-Scroll")).to_be_visible()
                    expect(terminal).to_contain_text("Live update 2")
                    assert terminal.evaluate("e => e.scrollTop < 30")
                    details = terminal.locator("details").first
                    expect(details).not_to_have_attribute("open", "")
                    expect(terminal).to_contain_text("Preserve the folded silhouette.")
                    assert '"type": "reasoning"' not in terminal.inner_text()
                    details.locator("summary").click()
                    expect(details).to_have_attribute("open", "")
                    expect(details).to_contain_text("Synthetic reference details")
                    details.locator("summary").click()
                    terminal.hover()
                    page.mouse.wheel(0, -10000)
                    screenshot(page, name, "activity-reading")
                    activity.get_by_role("button", name="Resume Auto-Scroll").click()
                    assert terminal.evaluate("e => e.scrollHeight - e.clientHeight - e.scrollTop < 30")
                    server.hold_generation = False
                    expect(activity.locator(".activity-state")).to_have_text("Output ready to apply")
                    expect(page.get_by_role("button", name="Generation Results", exact=True)).to_be_enabled()
                    screenshot(page, name, "activity-complete")
                    activity.get_by_role("button", name="Close", exact=True).click()
                    expect(page.get_by_role("dialog", name="Generation Results", exact=True)).to_have_count(0)
                    serialized = page.evaluate("JSON.stringify(window.comfyAPI.app.app.graph.serialize())")
                    assert DRAFT not in serialized and "Preserve the folded silhouette." not in serialized
                    page.get_by_role("button", name="Generation Results", exact=True).click()
                    expect(page.get_by_role("textbox", name="Output Prompt", exact=True)).to_have_value(DRAFT)
                    assert widget_value(page, node_id, "finalized_prompt") == "Original prompt"
                    contained(page, "dialog[open]")
                    screenshot(page, name, "review")
                    page.get_by_role("button", name="Apply to Workbench", exact=True).click()
                    expect(page.get_by_label("Finalized Prompt", exact=True)).to_have_value(DRAFT)
                    assert widget_value(page, node_id, "finalized_prompt") == DRAFT
                    page.get_by_role("dialog", name="Generation Results", exact=True).get_by_role(
                        "button", name="Close", exact=True
                    ).click()
                    page.get_by_role("button", name="Generate Prompt", exact=True).click()
                    expect(page.get_by_role("button", name="Apply Output", exact=True)).to_be_visible()
                    expect(page.get_by_role("dialog", name="Generation Results", exact=True)).to_have_count(0)
                    screenshot(page, name, "output-ready")
                    page.get_by_role("button", name="Apply Output", exact=True).click()
                    server.fail_generation = True
                    page.get_by_role("button", name="Generate Prompt", exact=True).click()
                    expect(page.locator(".arisu-workbench .status")).to_have_text("Simulated provider unavailable")
                    expect(page.get_by_role("button", name="Apply Output", exact=True)).to_have_count(0)
                    page.get_by_role("button", name="Generation Results", exact=True).click()
                    page.get_by_role("tab", name="Output Prompt", exact=True).click()
                    expect(page.get_by_role("textbox", name="Output Prompt", exact=True)).to_have_value("")
                    page.get_by_role("dialog", name="Generation Results", exact=True).get_by_role(
                        "button", name="Close", exact=True
                    ).click()
                    screenshot(page, name, "error")
                    # Long prose scrolls within the editor without moving the canvas or losing focus.
                    final = page.get_by_label("Finalized Prompt", exact=True)
                    long_prompt = "A paper boat follows the soft reflections across the pond. " * 160
                    final.fill(long_prompt)
                    final.press("Control+End")
                    expect(final).to_be_focused()
                    assert final.evaluate("e => e.scrollHeight > e.clientHeight && e.scrollTop > 0")
                    scale = page.evaluate("window.comfyAPI.app.app.canvas.ds.scale")
                    final.hover()
                    page.mouse.wheel(0, -200)
                    page.wait_for_function("e => e.scrollTop < e.scrollHeight - e.clientHeight - 30", arg=final.element_handle())
                    assert page.evaluate("window.comfyAPI.app.app.canvas.ds.scale") == scale
                    screenshot(page, name, "long-text")
                    # Wheel zoom and middle-button pan work over the Workbench's controls.
                    saved_view = page.evaluate(
                        "({scale: window.comfyAPI.app.app.canvas.ds.scale, offset: Array.from(window.comfyAPI.app.app.canvas.ds.offset)})"
                    )
                    page.get_by_label("Requirements", exact=True).hover()
                    page.mouse.wheel(0, 150)
                    page.wait_for_function("scale => window.comfyAPI.app.app.canvas.ds.scale !== scale", arg=scale)
                    offset = page.evaluate("Array.from(window.comfyAPI.app.app.canvas.ds.offset)")
                    page.mouse.down(button="middle")
                    page.mouse.move(425, 365, steps=5)
                    page.mouse.up(button="middle")
                    assert page.evaluate("Array.from(window.comfyAPI.app.app.canvas.ds.offset)") != offset
                    screenshot(page, name, "canvas")
                    page.evaluate(
                        "view => { const app = window.comfyAPI.app.app; app.canvas.ds.scale = view.scale; app.canvas.ds.offset[0] = view.offset[0]; app.canvas.ds.offset[1] = view.offset[1]; app.canvas.setDirty(true, true); }",
                        saved_view,
                    )
                    # Narrow the node with its real resize handle; the stacked editor stays reachable.
                    corner = page.evaluate(
                        """id => {
                        const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id), ds = app.canvas.ds;
                        const rect = app.canvas.canvas.getBoundingClientRect();
                        return [(node.pos[0] + node.size[0] + ds.offset[0]) * ds.scale + rect.left - 3,
                                (node.pos[1] + node.size[1] + ds.offset[1]) * ds.scale + rect.top - 3];
                        }""",
                        node_id,
                    )
                    page.mouse.move(*corner)
                    page.mouse.down()
                    page.mouse.move(corner[0] - 220, corner[1], steps=10)
                    page.mouse.up()
                    contained(page, ".arisu-workbench")
                    assert page.locator(".arisu-workbench .columns").evaluate(
                        "e => getComputedStyle(e).gridTemplateColumns.split(' ').length === 1"
                    )
                    page.get_by_label("Requirements", exact=True).click()
                    screenshot(page, name, "narrow-direction")
                    final.click()
                    final.press("Control+End")
                    expect(final).to_be_focused()
                    contained(page, ".arisu-workbench .final textarea")
                    assert widget_value(page, node_id, "finalized_prompt") == long_prompt
                    screenshot(page, name, "narrow-final")
                    # A fresh page resets the shared status cache and renders unavailable-agent controls.
                    server.available = False
                    page.reload()
                    page.wait_for_function("!!window.LiteGraph?.registered_node_types.ArisuMiniMaxH3PromptWorkbench")
                    add_node(page, WORKBENCH)
                    expect(page.get_by_role("button", name="Generate Prompt", exact=True)).to_be_disabled()
                    page.get_by_label("Finalized Prompt", exact=True).fill("Still editable offline")
                    screenshot(page, name, "unavailable")
                    page.get_by_role("button", name="Setup", exact=True).click()
                    expect(page.get_by_role("dialog", name="Prompt Workbench Agents")).to_be_visible()
                    contained(page, "dialog[open]")
                    terminal = page.get_by_label("Agent Logs", exact=True)
                    expect(terminal).to_contain_text("ABCD-EFGH")
                    assert terminal.bounding_box()["height"] > height * 0.35
                    link = terminal.get_by_role("link", name="https://example.test/device")
                    expect(link).to_have_attribute("target", "_blank")
                    expect(link).to_have_attribute("rel", "noopener noreferrer")
                    link.evaluate("e => e.addEventListener('click', event => {event.preventDefault(); e.dataset.clicked = 'yes';})")
                    link.click()
                    expect(link).to_have_attribute("data-clicked", "yes")
                    screenshot(page, name, "settings")
                    hover_button(
                        page, page.locator("dialog[open]").get_by_role("button", name="Close", exact=True), name, "agent-close-hover"
                    )
                    page.get_by_role("tab", name="Grok Build", exact=True).click()
                    expect(page.get_by_label("Grok Build Model", exact=True)).to_be_visible()
                    expect(page.get_by_label("Codex Model", exact=True)).to_have_count(0)
                    page.get_by_role("tab", name="Grok Build", exact=True).press("ArrowLeft")
                    expect(page.get_by_role("tab", name="Codex", exact=True)).to_be_focused()
                    expect(page.get_by_label("Codex Model", exact=True)).to_be_visible()
                    page.get_by_label("Codex Model", exact=True).click()
                    page.keyboard.press("Escape")
                    screenshot(page, name, "settings-focus")
                    page.keyboard.press("Tab")
                    assert page.evaluate("!!document.activeElement.closest('dialog[open]')")
                    page.keyboard.press("Escape")
                    expect(page.locator("dialog[open]")).to_have_count(0)
                    # Managing agents from Settings must keep the parent modal open.
                    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
                    settings = page.locator('[role="dialog"]').filter(has=page.get_by_text("Settings", exact=True))
                    expect(settings).to_be_visible()
                    settings.get_by_text("Arisu Nodes", exact=True).click()
                    screenshot(page, name, "settings-page")
                    hover_button(page, settings.get_by_role("button", name="Manage Agents…", exact=True), name, "settings-page-hover")
                    settings.get_by_role("button", name="Manage Agents…", exact=True).click()
                    agents = page.locator("dialog.arisu-agents[open][aria-label]")
                    expect(agents).to_be_visible()
                    agents.get_by_text("Activity", exact=True).click()
                    screenshot(page, name, "settings-parent")
                    expect(settings).to_be_visible()
                    agents.locator("#arisu-agent-codex").get_by_role("button", name="Remove Completely", exact=True).click()
                    confirmation = agents.locator("dialog[open]")
                    confirmation.get_by_role("button", name="Cancel", exact=True).click()
                    expect(settings).to_be_visible()
                    expect(agents).to_be_visible()
                    agents.get_by_role("button", name="Close", exact=True).click()
                    expect(agents).to_have_count(0)
                    expect(settings).to_be_visible()
                    expect(settings.get_by_role("button", name="Manage Agents…", exact=True)).to_be_focused()
                    toggle = settings.get_by_role("switch", name="Show Agents Shortcut")
                    toggle.click()
                    page.keyboard.press("Escape")
                    expect(settings).not_to_be_visible()
                    shortcut = page.get_by_role("button", name="Manage Agents", exact=True)
                    expect(shortcut).to_be_visible()
                    # Rebuild the shared toolbar groups as other extensions do during startup.
                    page.evaluate("""async () => {
                        const { app } = await import('/scripts/app.js');
                        const manager = document.createElement('button');
                        manager.textContent = 'Manager';
                        manager.className = 'comfy-btn';
                        app.menu.settingsGroup.append(manager);
                        app.menu.actionsGroup.update();
                    }""")
                    expect(shortcut).to_be_visible()
                    manager = page.get_by_role("button", name="Manager", exact=True)
                    shortcut_box = shortcut.bounding_box()
                    manager_box = manager.bounding_box()
                    assert shortcut_box["x"] + shortcut_box["width"] <= manager_box["x"]
                    expect(shortcut.locator("img")).to_be_visible()
                    assert shortcut.locator("img").evaluate("image => image.complete && image.naturalWidth > 0")
                    screenshot(page, name, "agents-shortcut")
                    hover_button(page, shortcut, name, "shortcut-hover")
                    shortcut.focus()
                    page.keyboard.press("Enter")
                    expect(agents).to_be_visible()
                    screenshot(page, name, "shortcut-modal")
                    page.keyboard.press("Escape")
                    expect(shortcut).to_be_focused()
                    page.reload()
                    expect(shortcut).to_be_visible()
                    page.evaluate("""async () => {
                        const { app } = await import('/scripts/app.js');
                        app.menu.settingsGroup.update();
                        app.menu.actionsGroup.update();
                    }""")
                    expect(shortcut).to_be_visible()
                    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
                    settings.get_by_text("Arisu Nodes", exact=True).click()
                    toggle.click()
                    page.keyboard.press("Escape")
                    expect(shortcut).to_have_count(0)

        finally:
            browser.close()
