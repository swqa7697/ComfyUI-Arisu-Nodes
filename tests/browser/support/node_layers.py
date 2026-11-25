"""Exercise saved stacking order through the real frontend and settings page."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.browser.support.harness import screenshot


def inspect_node_layers(page: Page, name: str):
    """Keep a workflow without Arisu nodes layered across edits and restores."""
    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
    settings = page.locator('[role="dialog"]').filter(has=page.get_by_text("Settings", exact=True))
    settings.get_by_text("Arisu Nodes", exact=True).click()
    toggle = settings.get_by_role("switch", name="Save Node Layer Order")
    restore_toggle = settings.get_by_role("switch", name="Restore Node Layer Order")
    expect(toggle).not_to_be_checked()
    expect(restore_toggle).to_be_checked()
    screenshot(page, name, "node-layers-settings")
    toggle.click()
    expect(toggle).to_be_checked()
    page.keyboard.press("Escape")
    expect(settings).not_to_be_visible()

    ids = page.evaluate(
        """async () => {
        const app = window.comfyAPI.app.app;
        class LayerFixture extends LGraphNode {
            constructor() { super(); this.addInput('value', '*'); this.addOutput('value', '*'); }
        }
        LiteGraph.registerNodeType('LayerFixture', LayerFixture);
        await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[]});
        const make = (title, pos) => {
            const node = LiteGraph.createNode('LayerFixture');
            app.graph.add(node); node.title = title; node.pos = pos; node.size = [280,180];
            return node.id;
        };
        const ids = [make('Covered node', [100,170]), make('Covering node', [140,210]),
            make('Offscreen node', [5000,5000])];
        app.canvas.ds.scale = 1; app.canvas.ds.offset = [0,0]; app.canvas.setDirty(true,true);
        await app.loadGraphData(JSON.parse(JSON.stringify(app.rootGraph.serialize())));
        return ids;
    }"""
    )
    assert page.evaluate("() => window.comfyAPI.app.app.graph.nodes.every(n => !n.type.startsWith('Arisu'))")
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[1]
    assert not page.evaluate("() => window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.isModified")
    point = page.evaluate(
        """() => {
        const canvas = window.comfyAPI.app.app.canvas, rect = canvas.canvas.getBoundingClientRect();
        return [(220+canvas.ds.offset[0])*canvas.ds.scale+rect.left,
            (155+canvas.ds.offset[1])*canvas.ds.scale+rect.top];
    }"""
    )
    page.mouse.click(*point)
    page.wait_for_function("() => window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.isModified")
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[0]
    screenshot(page, name, "node-layers-front")

    # Selection alone must survive history and serialization, including the
    # offscreen node that a viewport-only implementation would silently lose.
    page.evaluate("() => window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.undo()")
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[1]
    page.evaluate("() => window.comfyAPI.app.app.extensionManager.workflow.activeWorkflow.changeTracker.redo()")
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[0]
    order = page.evaluate(
        """async () => {
        const app = window.comfyAPI.app.app;
        const saved = JSON.parse(JSON.stringify(app.rootGraph.serialize({sortNodes:true})));
        const order = saved.extra.arisu_node_layers.nodes;
        await app.loadGraphData(saved, true, true, app.extensionManager.workflow.activeWorkflow);
        return order;
    }"""
    )
    assert order == [ids[1], ids[2], ids[0]]
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[0]

    # Subgraph nodes need their own saved ordering even when their canvas has
    # never been visited. The public graph API supplies real layout stores.
    subgraph = page.evaluate(
        """async () => {
        const app = window.comfyAPI.app.app, graph = app.rootGraph;
        const children = ['Subgraph lower', 'Subgraph upper'].map(title => {
            const node = LiteGraph.createNode('LayerFixture');
            graph.add(node); node.title = title; node.pos = [900,900]; node.size = [240,120];
            return node;
        });
        const {subgraph} = graph.convertToSubgraph(new Set(children));
        const lower = subgraph.nodes.find(n => n.title === 'Subgraph lower');
        app.canvas.bringToFront.call({graph:subgraph}, lower);
        const saved = JSON.parse(JSON.stringify(graph.serialize({sortNodes:true})));
        const order = saved.extra.arisu_node_layers.subgraphs.find(item => item.id === subgraph.id)?.nodes;
        if (!order || order.at(-1) !== lower.id || order.length !== 2) throw Error('Subgraph order was not saved');
        await app.loadGraphData(saved, true, true, app.extensionManager.workflow.activeWorkflow);
        const restored = app.rootGraph.subgraphs.get(subgraph.id), target = restored.getNodeById(lower.id);
        if (restored.getNodeOnPos(target.pos[0]+30,target.pos[1]+40)?.id !== lower.id)
            throw Error('Subgraph order was not restored');
        return {id:subgraph.id, node:lower.id};
    }"""
    )

    # Switching actual workflow tabs must not substitute the other graph's
    # order when both documents reuse small integer node IDs.
    tabs = page.evaluate(
        """async () => {
        const app = window.comfyAPI.app.app, first = app.extensionManager.workflow.activeWorkflow;
        first.changeTracker.captureCanvasState();
        const firstName = first.filename;
        await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[]});
        const node = LiteGraph.createNode('LayerFixture'); app.graph.add(node); node.title = 'Other workflow';
        app.extensionManager.workflow.activeWorkflow.changeTracker.captureCanvasState();
        return [firstName, app.extensionManager.workflow.activeWorkflow.filename];
    }"""
    )
    page.get_by_text(tabs[0], exact=True).click()
    page.wait_for_function("""id => window.comfyAPI.app.app.graph.getNodeById(id)?.title === 'Covered node'""", arg=ids[0])
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[0]
    assert page.evaluate(
        """({id,node}) => {
        const graph = window.comfyAPI.app.app.rootGraph.subgraphs.get(id), target = graph.getNodeById(node);
        return graph.getNodeOnPos(target.pos[0]+30,target.pos[1]+40)?.id === node;
    }""",
        subgraph,
    )
    page.get_by_text(tabs[1], exact=True).click()
    page.wait_for_function("() => window.comfyAPI.app.app.graph.nodes.some(node => node.title === 'Other workflow')")
    page.get_by_text(tabs[0], exact=True).click()
    page.wait_for_function("id => window.comfyAPI.app.app.graph.getNodeById(id)?.title === 'Covered node'", arg=ids[0])
    screenshot(page, name, "node-layers-restored")

    # Vue uses its own pointer path. A real DOM node click must be captured by
    # the same persistence hook rather than relying on canvas-only wrappers.
    vue_enabled = page.evaluate("() => window.comfyAPI.app.app.extensionManager.setting.get('Comfy.VueNodes.Enabled')")
    page.evaluate("() => window.comfyAPI.app.app.extensionManager.setting.set('Comfy.VueNodes.Enabled',true)")
    expect(page.locator(f'[data-node-id="{ids[1]}"]')).to_be_visible()
    point = page.evaluate(
        """() => {
        const canvas = window.comfyAPI.app.app.canvas, rect = canvas.canvas.getBoundingClientRect();
        return [(405+canvas.ds.offset[0])*canvas.ds.scale+rect.left,
            (260+canvas.ds.offset[1])*canvas.ds.scale+rect.top];
    }"""
    )
    page.mouse.click(*point)
    page.wait_for_function("id => window.comfyAPI.app.app.graph.getNodeOnPos(180,240)?.id === id", arg=ids[1])
    page.evaluate(
        """async () => {
        const app = window.comfyAPI.app.app;
        await app.loadGraphData(JSON.parse(JSON.stringify(app.rootGraph.serialize({sortNodes:true}))),
            true,true,app.extensionManager.workflow.activeWorkflow);
    }"""
    )
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[1]
    screenshot(page, name, "node-layers-vue")
    page.evaluate("enabled => window.comfyAPI.app.app.extensionManager.setting.set('Comfy.VueNodes.Enabled',enabled)", vue_enabled)

    # The setting is reversible through the same UI and leaves the current
    # drawing untouched. Disabling immediately after a save must retain that
    # record even before the document has been reloaded.
    last_saved = page.evaluate(
        """id => {
        const app = window.comfyAPI.app.app;
        app.canvas.bringToFront(app.graph.getNodeById(id));
        return app.rootGraph.serialize().extra.arisu_node_layers;
    }""",
        ids[0],
    )
    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
    settings.get_by_text("Arisu Nodes", exact=True).click()
    expect(toggle).to_be_checked()
    toggle.click()
    expect(toggle).not_to_be_checked()
    page.keyboard.press("Escape")
    assert not page.evaluate("() => window.comfyAPI.app.app.extensionManager.setting.get('Arisu.Workflow.SaveNodeLayers')")
    assert (
        page.evaluate(
            """id => {
        const app = window.comfyAPI.app.app;
        app.canvas.sendToBack(app.graph.getNodeById(id));
        return app.rootGraph.serialize().extra.arisu_node_layers;
    }""",
            ids[0],
        )
        == last_saved
    )
    # With recording off, loading still restores the saved layers by default.
    saved = page.evaluate("() => JSON.parse(JSON.stringify(window.comfyAPI.app.app.rootGraph.serialize({sortNodes:true})))")
    page.evaluate("async data => window.comfyAPI.app.app.loadGraphData(data)", saved)
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[0]
    assert page.evaluate("() => window.comfyAPI.app.app.rootGraph.serialize().extra.arisu_node_layers") == last_saved

    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
    settings.get_by_text("Arisu Nodes", exact=True).click()
    restore_toggle.click()
    expect(restore_toggle).not_to_be_checked()
    expect(toggle).not_to_be_checked()
    page.keyboard.press("Escape")
    page.evaluate("async data => window.comfyAPI.app.app.loadGraphData(data)", saved)
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[1]
    assert page.evaluate("() => window.comfyAPI.app.app.rootGraph.serialize().extra.arisu_node_layers") == last_saved

    # Enabling restore does not rearrange the open canvas; it takes effect on load.
    page.get_by_role("button", name="Settings (Ctrl + ,)", exact=True).click()
    settings.get_by_text("Arisu Nodes", exact=True).click()
    restore_toggle.click()
    expect(restore_toggle).to_be_checked()
    expect(toggle).not_to_be_checked()
    page.keyboard.press("Escape")
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[1]
    page.evaluate("async data => window.comfyAPI.app.app.loadGraphData(data)", saved)
    assert page.evaluate("() => window.comfyAPI.app.app.graph.getNodeOnPos(180,240).id") == ids[0]
