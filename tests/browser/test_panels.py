"""Real-browser regression journeys for the two custom MiniMax panels."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from playwright.sync_api import Page, expect, sync_playwright

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


def test_resource_studio():
    # One journey, repeated at two usable desktop viewports without multiplying test cases.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((1440, 900), (1024, 768)):
                name = f"studio-{width}"
                with FixtureServer() as server, browser_page(browser, server, name, width, height) as page:
                    node_id = add_node(page, STUDIO)
                    expect(page.locator(".arisu-studio")).to_be_visible()
                    contained(page, ".arisu-studio")
                    screenshot(page, name, "empty")
                    page.get_by_role("button", name="first frame", exact=True).click()
                    expect(page.locator("dialog[open]")).to_be_visible()
                    contained(page, "dialog[open]")
                    screenshot(page, name, "browse")
                    pick(page, "scene.png")
                    expect(page.locator(".arisu-studio img")).to_be_visible()
                    assert studio_state(page, node_id)["keyframes"]["first"]["path"] == "scene.png"
                    page.get_by_role("button", name="Crop", exact=True).click()
                    page.locator(".arisu-cropper-ratio").select_option("1:1")
                    contained(page, "dialog[open]")
                    screenshot(page, name, "crop")
                    page.get_by_role("button", name="apply", exact=True).click()
                    page.wait_for_function(
                        """id => {
                        const data = JSON.parse(window.comfyAPI.app.app.graph.getNodeById(id).widgets.find(w => w.name === 'resources_json').value);
                        return data.keyframes.first.crop?.width === data.keyframes.first.crop?.height;
                    }""",
                        arg=node_id,
                    )
                    crop = studio_state(page, node_id)["keyframes"]["first"]["crop"]
                    assert crop["width"] == crop["height"] and crop["width"] > 0
                    page.get_by_role("button", name="Browse references…", exact=True).click()
                    pick(page, "sound.wav")
                    expect(page.get_by_label("Start seconds")).to_be_visible()
                    page.get_by_label("Start seconds").fill("1")
                    page.get_by_label("Start seconds").press("Tab")
                    page.get_by_label("End seconds").fill("4")
                    page.get_by_label("End seconds").press("Tab")
                    contained(page, "dialog[open]")
                    screenshot(page, name, "clip")
                    page.get_by_role("button", name="Apply", exact=True).click()
                    expect(page.get_by_role("button", name="Edit audio sound.wav", exact=True)).to_be_visible()
                    assert studio_state(page, node_id)["references"][0]["clip"] == {"start": 1, "end": 4}
                    # More rows than the panel can display exercise real scrolling.
                    for index in range(2, 10):
                        page.get_by_role("button", name="Browse references…", exact=True).click()
                        pick(page, f"scene-{index}.png")
                        expect(page.get_by_role("button", name=f"Edit image scene-{index}.png", exact=True)).to_be_attached()
                    references = page.locator(".arisu-studio .references")
                    references.hover()
                    page.mouse.wheel(0, 600)
                    page.wait_for_function("document.querySelector('.arisu-studio .references').scrollTop > 0")
                    screenshot(page, name, "populated")
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
                    page.get_by_role("button", name="first frame", exact=True).hover()
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
                    expect(page.get_by_role("button", name="Manage agents", exact=True)).to_have_count(0)
                    node_id = add_node(page, WORKBENCH)
                    expect(page.get_by_role("button", name="Generate prompt", exact=True)).to_be_enabled()
                    contained(page, ".arisu-workbench")
                    page.get_by_label("Requirements", exact=True).fill("Follow a paper boat across a pond.")
                    page.get_by_label("LoRA trigger words", exact=True).fill("paper_art")
                    page.get_by_label("Finalized prompt", exact=True).fill("Original prompt")
                    screenshot(page, name, "editing")
                    page.get_by_role("button", name="Generate prompt", exact=True).click()
                    expect(page.locator(".arisu-workbench .status")).to_have_text("Generating prompt…")
                    screenshot(page, name, "generating")
                    expect(page.get_by_role("dialog", name="Review generated prompt")).to_be_visible()
                    expect(page.get_by_label("Generated prompt draft")).to_have_value(DRAFT)
                    assert widget_value(page, node_id, "finalized_prompt") == "Original prompt"
                    contained(page, "dialog[open]")
                    screenshot(page, name, "review")
                    page.get_by_role("button", name="Apply", exact=True).click()
                    expect(page.get_by_label("Finalized prompt", exact=True)).to_have_value(DRAFT)
                    assert widget_value(page, node_id, "finalized_prompt") == DRAFT
                    server.fail_generation = True
                    page.get_by_role("button", name="Generate prompt", exact=True).click()
                    expect(page.locator(".arisu-workbench .status")).to_have_text("Simulated provider unavailable")
                    screenshot(page, name, "error")
                    # A fresh page resets the shared status cache and renders unavailable-agent controls.
                    server.available = False
                    page.reload()
                    page.wait_for_function("!!window.LiteGraph?.registered_node_types.ArisuMiniMaxH3PromptWorkbench")
                    add_node(page, WORKBENCH)
                    expect(page.get_by_role("button", name="Generate prompt", exact=True)).to_be_disabled()
                    page.get_by_label("Finalized prompt", exact=True).fill("Still editable offline")
                    screenshot(page, name, "unavailable")
                    page.get_by_role("button", name="Setup", exact=True).click()
                    expect(page.get_by_role("dialog", name="Prompt Workbench agents")).to_be_visible()
                    contained(page, "dialog[open]")
                    screenshot(page, name, "settings")
                    page.keyboard.press("Tab")
                    assert page.evaluate("!!document.activeElement.closest('dialog[open]')")
                    page.keyboard.press("Escape")
                    expect(page.locator("dialog[open]")).to_have_count(0)
                    # Managing agents from Settings must keep the parent modal open.
                    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
                    settings = page.locator('[role="dialog"]').filter(has=page.get_by_text("Settings", exact=True))
                    expect(settings).to_be_visible()
                    settings.get_by_text("Arisu Nodes", exact=True).click()
                    settings.get_by_role("button", name="Manage agents…", exact=True).click()
                    agents = page.locator("dialog.arisu-agents[open][aria-label]")
                    expect(agents).to_be_visible()
                    agents.get_by_text("Activity", exact=True).click()
                    screenshot(page, name, "settings-parent")
                    expect(settings).to_be_visible()
                    agents.locator("#arisu-agent-codex").get_by_role("button", name="Remove completely", exact=True).click()
                    confirmation = agents.locator("dialog[open]")
                    confirmation.get_by_role("button", name="Cancel", exact=True).click()
                    expect(settings).to_be_visible()
                    expect(agents).to_be_visible()
                    agents.get_by_role("button", name="Close", exact=True).click()
                    expect(agents).to_have_count(0)
                    expect(settings).to_be_visible()
                    expect(settings.get_by_role("button", name="Manage agents…", exact=True)).to_be_focused()
                    toggle = settings.get_by_role("switch", name="Show Agents shortcut")
                    toggle.click()
                    page.keyboard.press("Escape")
                    expect(settings).not_to_be_visible()
                    shortcut = page.get_by_role("button", name="Manage agents", exact=True)
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
