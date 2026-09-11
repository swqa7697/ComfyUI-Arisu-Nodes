// Drive configuration, frontend expansion, and loadedGraphNode in their load order.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { extensionNamed, resetApp } from '../support/app.mjs';
import { resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/load_image.js';
import '../../../web/js/common/path_builder.js';
import '../../../web/js/common/node_size.js';

const extension = extensionNamed('Arisu.Common.NodeSize');

/** The frontend expands each configured node before notifying loadedGraphNode. */
function finishLoad(node) {
  const minimum = node.computeSize();
  node.setSize([Math.max(node.size[0], minimum[0]), Math.max(node.size[1], minimum[1])]);
  extension.loadedGraphNode(node);
}

test('workflow loads restore independent saved sizes after widget hiding and frontend expansion without changing interactive resizing', () => {
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
});
