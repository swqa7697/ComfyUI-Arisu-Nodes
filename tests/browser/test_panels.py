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
        if node_type == "ArisuMiniMaxH3ModelLoader" and page.viewport_size["width"] == 1024:
            # Frontend 1.52.7 locks the accessor and shrinks inside the setter,
            # before the callback. Exercise both differences on newer frontends.
            page.evaluate(
                """() => {
                const prototype = LiteGraph.registered_node_types.ArisuMiniMaxH3ModelLoader.prototype;
                const created = prototype.onNodeCreated;
                prototype.onNodeCreated = function () {
                    const mode = this.widgets.find(widget => widget.name === 'mode');
                    const node = this;
                    const value = Object.getOwnPropertyDescriptor(mode, 'value');
                    Object.defineProperty(mode, 'value', {
                        ...value, configurable: false,
                        set(next) {
                            value.set.call(this, next);
                            node.size[1] = node.computeSize([...node.size])[1];
                        },
                    });
                    return created.apply(this, arguments);
                };
            }"""
            )
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
        if node_type == "ArisuMiniMaxH3ModelLoader":
            inspect_loader(page, node_id, name)
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


def inspect_loader(page: Page, node_id: str, name: str):
    """Keep inactive controls visible and persist selections through real workflows."""
    result = page.evaluate(
        """async id => {
        const app = window.comfyAPI.app.app;
        let node = app.graph.getNodeById(id);
        const set = (name, value) => {
            const widget = node.widgets.find(w => w.name === name);
            widget.value = value; widget.callback?.(value);
        };
        const hybrid = () => Object.fromEntries(node.widgets.filter(w => w.name.startsWith('mode.')).map(w => [w.name,w.value]));
        const check = (actual, expected) => { if (JSON.stringify(actual) !== JSON.stringify(expected))
            throw Error(JSON.stringify({actual,expected})); };
        const controls = inactive => {
            check(node.widgets.map(w => w.name), ['mode','base_model','mode.overlay_model',
                'mode.block_start','mode.block_end','mode.include_final_adaln','weight_dtype']);
            for (const widget of node.widgets.filter(w => w.name.startsWith('mode.'))) {
                check(widget.disabled,inactive);
                check(widget.options.serialize,!inactive);
            }
        };
        controls(true);
        // Mode changes keep a user-sized node, including after workflow restore.
        node.setSize([node.size[0] + 80, node.size[1] + 100]);
        const size = Array.from(node.size);
        // A real MODEL link must retain its ID/socket throughout mode changes.
        class Sink extends LGraphNode { constructor() { super(); this.addInput('model','MODEL'); } }
        LiteGraph.registerNodeType('FixtureH3Sink', Sink);
        const sink = LiteGraph.createNode('FixtureH3Sink'); app.graph.add(sink);
        const link = node.connect(0, sink, 0), sinkId = sink.id;
        set('base_model','base.safetensors'); set('mode','hybrid');
        controls(false); check(Array.from(node.size),size);
        set('mode.overlay_model','overlay.safetensors'); set('mode.block_start',17);
        set('mode.block_end',19); set('mode.include_final_adaln',true);
        const expected = hybrid();
        const hybridPrompt = (await app.graphToPrompt()).output[id].inputs;
        check(hybridPrompt['mode.block_start'],17); check(hybridPrompt['mode.include_final_adaln'],true);
        set('mode','native');
        controls(true); check(hybrid(),expected); check(Array.from(node.size),size);
        const nativePrompt = (await app.graphToPrompt()).output[id].inputs;
        check(Object.keys(nativePrompt).sort(),['base_model','mode','weight_dtype']);
        const workflow = app.graph.serialize();
        // Older workflows carry only positional values. Mode reconstruction
        // must not shift the base/overlay selection or the block range.
        for (const savedNode of workflow.nodes) delete savedNode.widgets_values_named;
        await app.loadGraphData(workflow);
        node = app.graph.getNodeById(id);
        check(node.widgets.find(w=>w.name==='mode').value,'native');
        controls(true);
        set('mode','hybrid'); check(hybrid(),expected); check(Array.from(node.size),size);
        check(node.widgets.find(w=>w.name==='base_model').value,'base.safetensors');
        check(node.outputs[0].links,[link.id]); check(app.graph.getNodeById(sinkId).inputs[0].link,link.id);
        const tracker = app.extensionManager.workflow.activeWorkflow.changeTracker;
        tracker.captureCanvasState();
        set('mode','native'); tracker.captureCanvasState();
        await tracker.undo(); node=app.graph.getNodeById(id);
        check(node.widgets.find(w=>w.name==='mode').value,'hybrid'); check(hybrid(),expected);
        await tracker.redo(); node=app.graph.getNodeById(id);
        check(node.widgets.find(w=>w.name==='mode').value,'native');
        set('mode','hybrid'); check(hybrid(),expected);
        // A second workflow carries separate node properties even with reused IDs.
        const saved = app.graph.serialize();
        await app.loadGraphData({nodes:[],links:[],groups:[],version:0.4});
        const other=LiteGraph.createNode('ArisuMiniMaxH3ModelLoader');app.graph.add(other);
        node=other;set('mode','hybrid');set('mode.block_start',3);set('mode','native');
        await app.loadGraphData(saved);node=app.graph.getNodeById(id);check(hybrid(),expected);
        app.graph.remove(app.graph.getNodeById(sinkId));
        node.pos=[100,140];node.setDirtyCanvas(true,true);
        return {nativePrompt,hybridPrompt};
        }""",
        node_id,
    )
    assert result["nativePrompt"]["mode"] == "native"
    assert result["hybridPrompt"]["mode.block_end"] == 19
    page.get_by_text("Unsaved Workflow (3)", exact=True).click()
    page.wait_for_function(
        """() => window.comfyAPI.app.app.graph._nodes.find(n => n.type === 'ArisuMiniMaxH3ModelLoader')
            ?.properties.arisu_h3_hybrid?.block_start === 3"""
    )
    page.get_by_text("Unsaved Workflow (4)", exact=True).click()
    page.wait_for_function(
        """id => window.comfyAPI.app.app.graph.getNodeById(id)?.widgets.find(w => w.name === 'mode.block_start')?.value === 17""",
        arg=node_id,
    )
    screenshot(page, name, "h3-loader-hybrid")

    # Use the real canvas combo menu and try editing the now-disabled controls.
    def click_widget(widget_name: str):
        page.wait_for_function(
            """([id,name]) => Number.isFinite(window.comfyAPI.app.app.graph.getNodeById(id)
                .widgets.find(w=>w.name===name)?.last_y)""",
            arg=[node_id, widget_name],
        )
        point = page.evaluate(
            """([id,name]) => {
            const app=window.comfyAPI.app.app, node=app.graph.getNodeById(id), ds=app.canvas.ds;
            const widget=node.widgets.find(w=>w.name===name), rect=app.canvas.canvas.getBoundingClientRect();
            return [(node.pos[0]+node.size[0]/2+ds.offset[0])*ds.scale+rect.left,
                (node.pos[1]+widget.last_y+10+ds.offset[1])*ds.scale+rect.top];
            }""",
            [node_id, widget_name],
        )
        page.mouse.click(*point)

    size = page.evaluate("id => Array.from(window.comfyAPI.app.app.graph.getNodeById(id).size)", node_id)
    click_widget("mode")
    page.locator(".litecontextmenu .litemenu-entry").filter(has_text="native").click()
    assert widget_value(page, node_id, "mode") == "native"
    assert page.evaluate("id => Array.from(window.comfyAPI.app.app.graph.getNodeById(id).size)", node_id) == size
    for field in ["overlay_model", "block_start", "block_end", "include_final_adaln"]:
        value = widget_value(page, node_id, "mode." + field)
        click_widget("mode." + field)
        assert widget_value(page, node_id, "mode." + field) == value
        expect(page.locator(".litecontextmenu, .graphdialog")).to_have_count(0)
    screenshot(page, name, "h3-loader-native")
    click_widget("mode")
    page.locator(".litecontextmenu .litemenu-entry").filter(has_text="hybrid").click()
    assert page.evaluate("id => Array.from(window.comfyAPI.app.app.graph.getNodeById(id).size)", node_id) == size
    click_widget("mode.include_final_adaln")
    assert widget_value(page, node_id, "mode.include_final_adaln") is False


def inspect_set_get(page: Page):
    """Compare real frontend serialization using isolated KJNodes-compatible virtual nodes."""
    page.evaluate(
        """async () => {
        const app = window.comfyAPI.app.app;
        const { captureWorkbenchPrompt, effectiveBundles } = await import('/extensions/arisu/js/minimax_h3/settings_broadcast.js');
        class Setter extends LGraphNode { constructor() { super(); this.isVirtualNode = true; this.addInput('value', '*'); this.addOutput('value', '*'); this.addWidget('text', 'key', 'route', () => {}); } }
        class Getter extends LGraphNode { constructor() { super(); this.isVirtualNode = true; this.addOutput('value', '*'); this.addWidget('text', 'key', 'route', () => {}); } }
        Getter.prototype.getInputLink = function(slot) {
            const setter = this.graph._nodes.find(n => n.type === 'SetNode' && n.widgets[0].value === this.widgets[0].value);
            const id = setter?.inputs[slot]?.link;
            return this.graph.links.get?.(id) ?? this.graph.links[id];
        };
        class Source extends LGraphNode { constructor() { super(); this.comfyClass = 'FixtureSource'; this.addOutput('unused', '*'); this.addOutput('value', '*'); } }
        class Sink extends LGraphNode { constructor() { super(); this.comfyClass = 'FixtureSink'; this.addInput('value', '*'); } }
        for (const [name, ctor] of Object.entries({SetNode: Setter, GetNode: Getter, FixtureSource: Source, FixtureSink: Sink}))
            LiteGraph.registerNodeType(name, ctor);
        const create = type => { const node = LiteGraph.createNode(type); app.graph.add(node); return node; };
        const equal = (actual, expected) => {
            if (JSON.stringify(actual) !== JSON.stringify(expected)) throw Error(JSON.stringify({actual, expected}));
        };
        const definitions = await (await fetch('/object_info')).json();
        for (const type of Object.keys(definitions)) {
            app.graph.clear();
            const node = create(type);
            // Advertising is off: exercise explicit routing on every exposed input.
            for (const widget of node.widgets ?? []) if (widget.name.startsWith('advertise_')) widget.value = false;
            for (const name of (node.inputs ?? []).map(input => input.name)) {
                const index = node.inputs.findIndex(input => input.name === name);
                if (index < 0) continue; // Bundle ownership deliberately removes individual resource sockets.
                const source = create('FixtureSource'), setter = create('SetNode'), getter = create('GetNode');
                setter.widgets[0].value = getter.widgets[0].value = String(source.id);
                source.outputs[1].type = getter.outputs[0].type = setter.inputs[0].type = node.inputs[index].type;
                source.connect(1, setter, 0);
                getter.connect(0, node, index);
                if (node.inputs[index]?.link == null) throw Error(type + ': failed to connect ' + name);
                const prompt = await app.graphToPrompt();
                equal(prompt.output[node.id].inputs[name], [String(source.id), 1]);
                if (prompt.output[setter.id] || prompt.output[getter.id]) throw Error('Virtual node serialized');
                node.disconnectInput(node.inputs.findIndex(input => input.name === name));
                app.graph.remove(getter); app.graph.remove(setter); app.graph.remove(source);
            }
            for (let slot = 0; slot < (node.outputs ?? []).length; slot++) {
                const setter = create('SetNode'), getter = create('GetNode'), sink = create('FixtureSink');
                setter.inputs[0].type = setter.outputs[0].type = getter.outputs[0].type = sink.inputs[0].type = node.outputs[slot].type;
                node.connect(slot, setter, 0); getter.connect(0, sink, 0);
                setter.widgets[0].value = getter.widgets[0].value = String(setter.id);
                const prompt = await app.graphToPrompt();
                equal(prompt.output[sink.id].inputs.value, [String(node.id), slot]);
                setter.connect(0, sink, 0);
                equal((await app.graphToPrompt()).output[sink.id].inputs.value, [String(node.id), slot]);
                app.graph.remove(sink); app.graph.remove(getter); app.graph.remove(setter);
            }
        }
        app.graph.clear();
        const studio = create('ArisuMiniMaxH3ResourceStudio'), workbench = create('ArisuMiniMaxH3PromptWorkbench');
        const setter = create('SetNode'), getter = create('GetNode');
        setter.inputs[0].type = getter.outputs[0].type = studio.outputs[0].type;
        studio.connect(0, setter, 0);
        getter.connect(0, workbench, workbench.inputs.findIndex(input => input.name === 'resources'));
        setter.widgets[0].value = getter.widgets[0].value = 'resources';
        if (effectiveBundles(workbench).resources !== studio) throw Error('Missing Studio metadata');
        equal(captureWorkbenchPrompt(workbench).output[workbench.id].inputs.resources, [String(studio.id), 0]);
        const settings = create('ArisuMiniMaxH3VideoSettings'), advanced = create('ArisuMiniMaxH3HybridToVideoAdvanced');
        const settingsSet = create('SetNode'), settingsGet = create('GetNode');
        settingsSet.widgets[0].value = settingsGet.widgets[0].value = 'settings';
        settingsSet.inputs[0].type = settingsGet.outputs[0].type = settings.outputs[0].type;
        settings.connect(0, settingsSet, 0);
        settingsGet.connect(0, advanced, advanced.inputs.findIndex(input => input.name === 'video_settings'));
        await app.graphToPrompt();
        if (!advanced.widgets.find(w => w.name === 'width').disabled || advanced.widgets.find(w => w.name === 'target_width').disabled)
            throw Error('Incorrect routed settings ownership');
        const upscale = create('ArisuMiniMaxH3VideoSettingsUpscale');
        upscale.connect(0, settingsSet, 0);
        await new Promise(resolve => setTimeout(resolve, 0));
        if (!advanced.widgets.find(w => w.name === 'target_width').disabled) throw Error('Setter change did not refresh ownership');
        settings.connect(0, settingsSet, 0);
        await new Promise(resolve => setTimeout(resolve, 0));
        if (advanced.widgets.find(w => w.name === 'target_width').disabled) throw Error('Restored basic settings still own target size');
        settingsGet.widgets[0].value = 'missing'; settingsGet.widgets[0].callback();
        await new Promise(resolve => setTimeout(resolve, 0));
        if (effectiveBundles(advanced).settings) throw Error('Stale source after getter selection change');
        settingsGet.widgets[0].value = 'settings'; settingsGet.widgets[0].callback();
        await new Promise(resolve => setTimeout(resolve, 0));
        if (advanced.widgets.find(w => w.name === 'target_width').disabled) throw Error('Getter change did not refresh ownership');
        app.graph.clear();
    }"""
    )


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
                    inspect_set_get(page)
                    node_id = add_node(page, WORKBENCH)
                    expect(page.get_by_role("button", name="Generate Prompt", exact=True)).to_be_enabled()
                    contained(page, ".arisu-workbench")
                    page.get_by_label("Requirements", exact=True).fill("Follow a paper boat across a pond.")
                    page.get_by_label("LoRA Trigger Words", exact=True).fill("paper_art")
                    page.get_by_label("Finalized Prompt", exact=True).fill("Original prompt")
                    # Reopening a pre-switch workflow preserves positional fields and defaults motion on.
                    page.evaluate(
                        """id => {
                        const node = window.comfyAPI.app.app.graph.getNodeById(id);
                        const old = node.serialize();
                        const index = node.widgets.findIndex(widget => widget.name === 'motion_enabled');
                        old.widgets_values = old.widgets_values.slice(0, index);
                        node.widgets[index].value = false;
                        node.configure(old);
                        if (node.size[0] !== old.size[0] || node.size[1] !== old.size[1]) throw Error('Restoring workflow changed Workbench size');
                    }""",
                        node_id,
                    )
                    assert widget_value(page, node_id, "motion_enabled") is True
                    assert widget_value(page, node_id, "finalized_prompt") == "Original prompt"
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
                    toggle = page.get_by_role("checkbox", name="Enable motion context")
                    expect(toggle).to_be_checked()
                    expect(toggle).to_be_disabled()
                    # Locator.click intentionally rejects disabled labels; a physical click must remain inert.
                    label_bounds = page.locator(".motion-switch span").bounding_box()
                    page.mouse.click(label_bounds["x"] + label_bounds["width"] / 2, label_bounds["y"] + label_bounds["height"] / 2)
                    expect(toggle).to_be_checked()
                    assert page.locator(".arisu-workbench .context").evaluate("element => element.open")
                    screenshot(page, name, "motion-unwired")
                    # Use real graph wires: one alone leaves the switch disabled.
                    source_id = page.evaluate(
                        """id => {
                        const app = window.comfyAPI.app.app, node = app.graph.getNodeById(id);
                        const source = LiteGraph.createNode('FixtureSource');
                        source.pos = [-1000, -1000]; app.graph.add(source);
                        source.connect(0, node, node.inputs.findIndex(input => input.name === 'context_latent'));
                        return source.id;
                    }""",
                        node_id,
                    )
                    expect(toggle).to_be_disabled()
                    page.evaluate(
                        """([id, sourceId]) => {
                        const graph = window.comfyAPI.app.app.graph, node = graph.getNodeById(id);
                        graph.getNodeById(sourceId).connect(1, node, node.inputs.findIndex(input => input.name === 'vae'));
                    }""",
                        [node_id, source_id],
                    )
                    expect(toggle).to_be_enabled()
                    expect(page.get_by_label("Audio Context Length in Frames")).to_be_enabled()
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.captureCanvasState()")
                    page.locator(".motion-switch span").click()
                    expect(toggle).not_to_be_checked()
                    assert page.locator(".arisu-workbench .context").evaluate("element => element.open")
                    assert widget_value(page, node_id, "motion_enabled") is False
                    toggle.blur()
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.captureCanvasState()")
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.undo()")
                    assert widget_value(page, node_id, "motion_enabled") is True
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.redo()")
                    assert widget_value(page, node_id, "motion_enabled") is False
                    assert page.evaluate("id => window.comfyAPI.app.app.graph.getNodeById(id).size[0]", node_id) == 720
                    if not page.locator(".arisu-workbench .context").evaluate("element => element.open"):
                        page.locator(".arisu-workbench summary").click()
                    toggle = page.get_by_role("checkbox", name="Enable motion context")
                    screenshot(page, name, "motion-disabled")
                    toggle.check()
                    assert widget_value(page, node_id, "motion_enabled") is True
                    screenshot(page, name, "motion-expanded")
                    page.locator(".arisu-workbench summary > span").click()
                    assert not page.locator(".arisu-workbench .context").evaluate("element => element.open")
                    toggle.focus()
                    toggle.press("Space")
                    expect(toggle).not_to_be_checked()
                    assert not page.locator(".arisu-workbench .context").evaluate("element => element.open")
                    page.locator(".motion-switch span").click()
                    expect(toggle).to_be_checked()
                    assert not page.locator(".arisu-workbench .context").evaluate("element => element.open")
                    # Unwiring disables the switch without changing the saved choice.
                    page.evaluate(
                        """sourceId => {
                        const graph = window.comfyAPI.app.app.graph;
                        graph.remove(graph.getNodeById(sourceId));
                    }""",
                        source_id,
                    )
                    expect(toggle).to_be_disabled()
                    assert widget_value(page, node_id, "motion_enabled") is True
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
                    expect(page.locator(".arisu-workbench .generation-time")).to_have_text(" · Agent time 0:42")
                    screenshot(page, name, "generating")
                    # Context and output edits, including real frontend Undo/Redo, retain the job.
                    captured = server.generation_requests[-1]
                    release_count = sum("/arisu/workbench/release" in request for request in server.requests)
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.captureCanvasState()")
                    page.get_by_label("Requirements", exact=True).fill("Next generation should use a different camera angle.")
                    page.get_by_label("Finalized Prompt", exact=True).fill("Manual edit during generation")
                    page.get_by_label("Finalized Prompt", exact=True).blur()
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.captureCanvasState()")
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.undo()")
                    expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
                    page.evaluate("window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.redo()")
                    expect(page.get_by_label("Finalized Prompt", exact=True)).to_have_value("Manual edit during generation")
                    expect(page.get_by_role("button", name="Generate Prompt", exact=True)).to_be_disabled()
                    assert "Next generation" not in captured["options"]["requirements"]
                    assert sum("/arisu/workbench/release" in request for request in server.requests) == release_count
                    screenshot(page, name, "editing-during-generation")
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
                    expect(activity.locator("header .generation-time")).to_have_text("Agent time 0:42")
                    activity.get_by_role("tab", name="Output Prompt", exact=True).click()
                    expect(activity.locator("header .generation-time")).to_be_visible()
                    activity.get_by_role("tab", name="Activity", exact=True).click()
                    terminal = activity.get_by_label("Generation Activity", exact=True)
                    expect(terminal).to_contain_text("workbench.read_skill")
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
                    thoughts = terminal.locator(".log-analysis")
                    assert thoughts.evaluate_all("items => items.every(e => !e.closest('details'))")
                    expect(thoughts.filter(has_text="Inspecting the selected reference")).to_be_visible()
                    expect(thoughts.filter(has_text="Preserve the folded silhouette.")).to_be_visible()
                    response = terminal.locator("details").filter(has=page.locator("summary", has_text="Agent response"))
                    expect(response).to_have_count(1)
                    expect(response).not_to_have_attribute("open", "")
                    assert DRAFT not in terminal.inner_text()
                    response.locator("summary").scroll_into_view_if_needed()
                    screenshot(page, name, "response-collapsed")
                    response.locator("summary").click()
                    expect(response).to_have_attribute("open", "")
                    expect(response.locator(".log-content")).to_be_visible()
                    assert DRAFT in terminal.inner_text()
                    screenshot(page, name, "response-expanded")
                    response.locator("summary").click()
                    expect(response).not_to_have_attribute("open", "")
                    assert DRAFT not in terminal.inner_text()
                    assert '"type": "reasoning"' not in terminal.inner_text()
                    skill = terminal.locator("details").filter(has=page.locator("summary", has_text="workbench.read_skill"))
                    expect(skill).to_have_count(1)
                    expect(skill).not_to_have_attribute("open", "")
                    assert "Hidden file content" not in terminal.inner_text()
                    assert "private-image-bytes" not in terminal.text_content()
                    skill.locator("summary").click()
                    expect(skill).to_contain_text("[analysis] Hidden file content")
                    assert "Hidden file content" not in " ".join(terminal.locator(".log-analysis").all_text_contents())
                    screenshot(page, name, "skill-details")
                    skill.locator("summary").click()
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
                    expect(activity.locator("header .generation-time")).to_have_text("Agent time 1:18")
                    expect(page.locator(".arisu-workbench .generation-time")).to_have_text(" · Agent time 1:18")
                    screenshot(page, name, "activity-complete")
                    activity.get_by_role("button", name="Close", exact=True).click()
                    expect(page.get_by_role("dialog", name="Generation Results", exact=True)).to_have_count(0)
                    serialized = page.evaluate("JSON.stringify(window.comfyAPI.app.app.graph.serialize())")
                    assert DRAFT not in serialized and "Preserve the folded silhouette." not in serialized
                    page.get_by_role("button", name="Generation Results", exact=True).click()
                    expect(page.get_by_role("textbox", name="Output Prompt", exact=True)).to_have_value(DRAFT)
                    assert widget_value(page, node_id, "finalized_prompt") == "Manual edit during generation"
                    contained(page, "dialog[open]")
                    screenshot(page, name, "review")
                    page.get_by_role("button", name="Apply to Workbench", exact=True).click()
                    expect(page.get_by_label("Finalized Prompt", exact=True)).to_have_value(DRAFT)
                    assert widget_value(page, node_id, "finalized_prompt") == DRAFT
                    page.get_by_role("dialog", name="Generation Results", exact=True).get_by_role(
                        "button", name="Close", exact=True
                    ).click()
                    page.get_by_label("Finalized Prompt", exact=True).fill("Manual edit before the next draft")
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
