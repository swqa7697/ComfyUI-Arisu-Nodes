// Drive configuration, frontend expansion, and loadedGraphNode in their load order.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { app, extensionNamed, resetApp } from '../support/app.mjs';
import { resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/load_image.js';
import '../../../web/js/common/path_builder.js';
import '../../../web/js/common/node_size.js';
import '../../../web/js/minimax_h3/settings_broadcast.js';

const extension = extensionNamed('Arisu.Common.NodeSize');

/** The frontend expands each configured node before notifying loadedGraphNode. */
function finishLoad(node) {
  const minimum = node.computeSize();
  node.setSize([Math.max(node.size[0], minimum[0]), Math.max(node.size[1], minimum[1])]);
  extension.loadedGraphNode(node);
}

test('workflow loads restore independent saved sizes after widget hiding and frontend expansion without changing interactive resizing', async () => {
  const root = makeGraph();
  const subgraph = makeGraph('nested');
  resetApp(root);
  resetDom();
  const configured = [];
  const Hybrid = {
    prototype: {
      onConfigure(info) {
        configured.push([this, info]);
        return 'configured';
      },
    },
  };
  extension.beforeRegisterNodeDef(Hybrid, { name: 'ArisuMiniMaxH3HybridToVideo' });
  const Load = { prototype: {} };
  extensionNamed('Arisu.Common.LoadImage').beforeRegisterNodeDef(Load, { name: 'ArisuLoadImage' });
  extension.beforeRegisterNodeDef(Load, { name: 'ArisuLoadImage' });

  const hybrid = makeNode({ id: 1, type: 'ArisuMiniMaxH3HybridToVideo', graph: root });
  hybrid.computeSize = () => [300, 500];
  const load = makeNode({
    id: 1,
    type: 'ArisuLoadImage',
    graph: subgraph,
    widgets: ['path', 'crop', 'root'].map((name) => ({ name, value: '' })),
    inputs: [{ name: 'path' }, { name: 'crop' }, { name: 'root' }],
  });
  load.computeSize = () => [300, 120];
  Load.prototype.onNodeCreated.call(load);
  for (const [hybridSize, loadSize] of [
    [
      [300, 180],
      [650, 700],
    ],
    [
      [320, 190],
      [720, 800],
    ],
  ]) {
    const info = { size: [...hybridSize] };
    hybrid.setSize([...hybridSize]);
    assert.equal(Hybrid.prototype.onConfigure.call(hybrid, info), 'configured');
    assert.deepEqual(configured.at(-1), [hybrid, info]);
    // Keep a copy: configuration callbacks may mutate the serialized array later.
    info.size[1] = 999;
    load.setSize([...loadSize]);
    Load.prototype.onConfigure.call(load, { size: [...loadSize] });
    assert.deepEqual(load.size, [300, 120]);
    assert.equal(load.inputs.length, 0);
    finishLoad(load);
    finishLoad(hybrid);
    assert.deepEqual(hybrid.size, hybridSize);
    assert.deepEqual(load.size, loadSize);
  }

  // A consumed restore must not undo a later manual resize or widget-hiding resize.
  hybrid.setSize([400, 200]);
  extension.loadedGraphNode(hybrid);
  assert.deepEqual(hybrid.size, [400, 200]);
  Load.prototype.onConfigure.call(load, {});
  extension.loadedGraphNode(load);
  assert.deepEqual(load.size, [300, 120]);

  // Missing or malformed sizes discard any prior pending restore and keep normal sizing.
  for (const size of [undefined, null, [], [100], [100, 200, 300], [0, 200], [-1, 200], [100, Infinity], [NaN, 200], ['100', 200]]) {
    Hybrid.prototype.onConfigure.call(hybrid, { size: [600, 700] });
    Hybrid.prototype.onConfigure.call(hybrid, { size });
    hybrid.setSize([300, 180]);
    finishLoad(hybrid);
    assert.deepEqual(hybrid.size, [300, 500], `size=${String(size)}`);
  }

  // Hook registration in the opposite order still restores after Path Builder's layout.
  const Path = { prototype: {} };
  extension.beforeRegisterNodeDef(Path, { name: 'ArisuPathBuilder' });
  extensionNamed('Arisu.Common.PathBuilder').beforeRegisterNodeDef(Path, { name: 'ArisuPathBuilder' });
  const path = makeNode({
    id: 2,
    type: 'ArisuPathBuilder',
    graph: root,
    widgets: ['segment_1', 'segment_2'].map((name) => ({ name, value: '' })),
    inputs: [{ name: 'segment_1' }, { name: 'segment_2' }],
  });
  path.computeSize = () => [300, 60 + 24 * path.widgets.filter((widget) => !widget.hidden).length];
  Path.prototype.onNodeCreated.call(path);
  const compact = [...path.size];
  Path.prototype.onConfigure.call(path, { size: [600, 400] });
  finishLoad(path);
  assert.deepEqual(path.size, [600, 400]);
  const row = path.widgets.at(-1);
  row.mouse({ type: 'pointerdown' }, [20, 0], path);
  assert.deepEqual(path.size, [300, compact[1] + 24]);
  row.mouse({ type: 'pointerdown' }, [path.size[0] - 20, 0], path);
  assert.deepEqual(path.size, compact);

  // The pack-wide hook also covers nodes with no other frontend extension.
  const Plain = { prototype: {} };
  extension.beforeRegisterNodeDef(Plain, { name: 'ArisuExtractLastImages' });
  const plain = makeNode({ id: 3, type: 'ArisuExtractLastImages', graph: root });
  Plain.prototype.onConfigure.call(plain, { size: [450, 90] });
  finishLoad(plain);
  assert.deepEqual(plain.size, [450, 90]);

  const original = () => 'unrelated';
  const Other = { prototype: { onConfigure: original } };
  extension.beforeRegisterNodeDef(Other, { name: 'PreviewImage' });
  assert.equal(Other.prototype.onConfigure, original);
  const other = makeNode({ id: 4, type: 'PreviewImage', graph: root });
  extension.loadedGraphNode(other);
  assert.deepEqual(other.size, [300, 100]);

  // Advertising settles after loadedGraphNode. Classic canvas can expand a compact
  // node in the intervening frames while LiteGraph's array merge retains old slots.
  const broadcast = extensionNamed('Arisu.MiniMaxH3.SettingsBroadcast');
  const resourceRoot = makeGraph();
  const resourceSubgraph = makeGraph('resource-subgraph');
  resourceRoot.subgraphs = new Map([[resourceSubgraph.id, resourceSubgraph]]);
  resetApp(resourceRoot);
  app.configuringGraph = true;
  const Studio = { prototype: {} };
  broadcast.beforeRegisterNodeDef(Studio, { name: 'ArisuMiniMaxH3ResourceStudio' });
  const studio = makeNode({
    id: 10,
    type: 'ArisuMiniMaxH3ResourceStudio',
    graph: resourceRoot,
    widgets: [{ name: 'advertise_resources', value: true }],
  });
  Studio.prototype.onAdded.call(studio);
  const consumers = [
    ['ArisuMiniMaxH3HybridToVideo', resourceRoot],
    ['ArisuMiniMaxH3HybridToVideoAdvanced', resourceRoot],
    ['ArisuMiniMaxH3HybridToVideo', resourceSubgraph],
  ].map(([type, graph], index) => {
    const definition = { prototype: {} };
    // Both hook registration orders must capture and restore the same dimensions.
    if (index === 0) extension.beforeRegisterNodeDef(definition, { name: type });
    broadcast.beforeRegisterNodeDef(definition, { name: type });
    if (index !== 0) extension.beforeRegisterNodeDef(definition, { name: type });
    const inputs = [
      { name: 'clip', link: null },
      { name: 'resources', link: graph === resourceSubgraph ? 100 : null },
      { name: 'first_frame', link: null },
      { name: 'ref_images.ref_image_0', link: null },
    ];
    const node = makeNode({ id: index + 11, type, graph, inputs });
    node.computeSize = () => [300, 140 + 20 * node.inputs.length];
    definition.prototype.onAdded.call(node);
    return { node, definition, inputs };
  });
  const previousFrame = globalThis.requestAnimationFrame;
  const frames = [];
  globalThis.requestAnimationFrame = (callback) => frames.push(callback);
  async function frame() {
    for (const callback of frames.splice(0)) callback();
    await Promise.resolve();
  }
  function configureResources(height) {
    app.configuringGraph = true;
    for (const [index, { node, definition, inputs }] of consumers.entries()) {
      node.inputs = structuredClone(inputs);
      // cloneObject copies saved indices without truncating the schema array.
      Object.assign(node.inputs, structuredClone(inputs.slice(0, 2)));
      definition.prototype.onConfigure.call(node, { size: [420 + index * 30, height] });
      finishLoad(node);
    }
    return broadcast.afterConfigureGraph();
  }
  async function settleResources(loading) {
    await frame();
    await frame();
    await loading;
    app.configuringGraph = false;
  }
  try {
    for (const height of [180, 700]) {
      const loading = configureResources(height);
      // Simulate the canvas's grow-only arrangement while extra slots still exist.
      for (const { node } of consumers) node.setSize([node.size[0], Math.max(node.size[1], node.computeSize()[1])]);
      await frame();
      assert(consumers.every(({ node }) => node.inputs.length === 4));
      await frame();
      await loading;
      app.configuringGraph = false;
      for (const [index, { node }] of consumers.entries()) {
        assert.deepEqual(
          node.inputs.map((input) => input.name),
          ['clip', 'resources'],
        );
        assert.deepEqual(node.size, [420 + index * 30, height]);
        node.setSize([500 + index, 240]);
      }
      assert.equal(studio.widgets[0].value, true);
      await broadcast.afterConfigureGraph();
      await frame();
      for (const [index, { node }] of consumers.entries()) assert.deepEqual(node.size, [500 + index, 240]);
    }

    // A new configure invalidates an older restore even when ownership stays on.
    const older = configureResources(180);
    const newer = configureResources(650);
    await settleResources(Promise.all([older, newer]));
    assert(consumers.every(({ node }) => node.size[1] === 650));

    // Turning advertising off before cleanup must keep the new fitted height.
    const released = configureResources(700);
    app.configuringGraph = false;
    studio.widgets[0].value = false;
    studio.widgets[0].callback(false);
    await settleResources(released);
    assert.deepEqual(consumers[0].node.size, [420, 220]);
    assert.equal(consumers[0].node.inputs.length, 4);
    assert.deepEqual(consumers[2].node.size, [480, 700]);

    // Removal and graph replacement discard both deferred cleanup and restoration.
    studio.widgets[0].value = true;
    const removed = configureResources(700);
    const detached = consumers[0];
    detached.definition.prototype.onRemoved.call(detached.node);
    resourceRoot.nodes.splice(resourceRoot.nodes.indexOf(detached.node), 1);
    detached.node.graph = null;
    detached.node.setSize([510, 260]);
    await settleResources(removed);
    assert.deepEqual(detached.node.size, [510, 260]);
    assert.equal(detached.node.inputs.length, 4);
    consumers.shift();
    const replaced = configureResources(700);
    resetApp(makeGraph());
    for (const { node } of consumers) node.setSize([530, 270]);
    await settleResources(replaced);
    for (const { node } of consumers) {
      assert.deepEqual(node.size, [530, 270]);
      assert.equal(node.inputs.length, 4);
    }
  } finally {
    if (previousFrame === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = previousFrame;
    app.configuringGraph = false;
  }
});
