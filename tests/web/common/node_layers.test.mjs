import assert from 'node:assert/strict';
import { test } from 'node:test';

import { app, extensionNamed, resetApp, settings, toastSeverities } from '../support/app.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/node_layers.js';

const extension = extensionNamed('Arisu.Common.NodeLayers');
const setting = extension.settings[0];
const restoreSetting = extension.settings[1];
const key = 'arisu_node_layers';

function graph(id, ids) {
  const result = makeGraph(id);
  result.extra = { otherExtension: { keep: true } };
  result.subgraphs = new Map();
  for (const id of ids) makeNode({ id, type: 'Note', graph: result });
  result.layers = [...result.nodes];
  result.getNodeById = (id) => result.nodes.find((node) => String(node.id) === String(id));
  result.save = function (sort = false) {
    const data = {
      nodes: this.nodes.map((node) => ({ id: node.id, type: node.type, order: 42 })),
      extra: { ...this.extra },
      definitions: { subgraphs: [...this.subgraphs.values()].map((child) => ({ id: child.id, extra: child.extra })) },
    };
    if (sort) data.nodes.sort((a, b) => a.id - b.id);
    this.onSerialize?.(data);
    return structuredClone(data);
  };
  return result;
}

function canvasFor(root) {
  return {
    graph: root,
    ctx: {},
    visible_area: [0, 0, 1000, 1000],
    computeVisibleNodes() {
      const [x, , width] = this.visible_area;
      return this.graph.layers.filter((node) => node.posX === undefined || (node.posX >= x && node.posX < x + width));
    },
    bringToFront(node) {
      const order = this.graph.layers;
      order.splice(order.indexOf(node), 1);
      order.push(node);
    },
    setDirty() {},
  };
}

function ids(graph) {
  return graph.layers.map((node) => node.id);
}

test('optional global layers round-trip independently of storage order, subgraphs, workflow ownership and disabled or incompatible frontends', () => {
  const root = graph('first', [30, 20, 10]);
  const child = graph('nested', [2, 1]);
  root.subgraphs.set(child.id, child);
  root.nodes[2].posX = 90000;
  resetApp(root);
  app.canvas = canvasFor(root);
  const calls = [];
  root.onSerialize = function (data) {
    calls.push(this);
    data.extra.existingHook = 'retained';
    return 'original result';
  };
  extension.init();
  const wrapped = root.onSerialize;
  extension.setup();
  assert.equal(root.onSerialize, wrapped);
  assert.equal(root.save().extra[key], undefined);
  assert.equal(calls.at(-1), root);

  settings[setting.id] = true;
  let snapshots = 0;
  app.extensionManager.workflow.activeWorkflow = { changeTracker: { captureCanvasState: () => snapshots++ } };
  setting.onChange(true);
  assert.equal(snapshots, 1);
  root.layers = [root.nodes[2], root.nodes[0], root.nodes[1]];
  child.layers.reverse();
  const saved = root.save(true);
  assert.deepEqual(saved.extra[key], { version: 1, nodes: [10, 30, 20], subgraphs: [{ id: 'nested', nodes: [1, 2] }] });
  assert.deepEqual(
    saved.nodes.map((node) => node.id),
    [10, 20, 30],
  );
  assert.ok(saved.nodes.every((node) => node.order === 42));
  assert.deepEqual(
    root.nodes.map((node) => node.id),
    [30, 20, 10],
  );
  assert.equal(saved.extra.existingHook, 'retained');
  assert.deepEqual(root.extra, { otherExtension: { keep: true }, [key]: saved.extra[key] });
  assert.deepEqual(child.extra, { otherExtension: { keep: true } });
  assert.deepEqual(app.canvas.visible_area, [0, 0, 1000, 1000]);
  // Turning off immediately after a save retains the record, even without a
  // reload. Editing an exported object cannot change the live workflow record.
  const retainedRoot = structuredClone(saved.extra[key]);
  settings[setting.id] = false;
  root.layers.reverse();
  assert.deepEqual(root.save().extra[key], retainedRoot);
  saved.extra[key].nodes.reverse();
  assert.deepEqual(root.extra[key], retainedRoot);
  saved.extra[key].nodes.reverse();
  root.layers.reverse();
  settings[setting.id] = true;

  // Loading/undo/redo and tab changes call the same hooks; each new graph gets
  // its own serializer. IDs may change from numeric to string in workflow JSON.
  const second = graph('second', [10, 20, 30, 40]);
  const restoredChild = graph('nested', [1, 2]);
  second.subgraphs.set(restoredChild.id, restoredChild);
  second.extra = structuredClone(saved.extra);
  second.extra[key].nodes = ['10', '999', '30', '20'];
  second.extra[key].subgraphs.push({ id: 'deleted-subgraph', nodes: [2, 1] });
  restoredChild.layers.reverse();
  app.rootGraph = second;
  app.graph = restoredChild;
  app.canvas.graph = restoredChild;
  extension.beforeConfigureGraph();
  extension.afterConfigureGraph();
  assert.deepEqual(ids(second), [10, 30, 20, 40]);
  assert.deepEqual(ids(restoredChild), [1, 2]);
  assert.equal(app.canvas.graph, restoredChild);
  assert.deepEqual(ids(root), [10, 30, 20]);

  for (const order of [
    [40, 30, 20, 10],
    [10, 30, 20, 40],
  ]) {
    second.extra[key].nodes = order;
    extension.afterConfigureGraph();
    assert.deepEqual(ids(second), order);
  }
  // Saving during configuration must not replace the still-pending restore.
  app.configuringGraph = true;
  second.layers.reverse();
  assert.deepEqual(second.save().extra[key], second.extra[key]);
  app.configuringGraph = false;
  extension.afterConfigureGraph();
  assert.deepEqual(ids(second), second.extra[key].nodes);

  // Both disabled means no capture or restore; re-enabling starts from the user's
  // current layout rather than applying a stale saved order.
  settings[setting.id] = false;
  settings[restoreSetting.id] = false;
  second.layers.reverse();
  const disabledOrder = ids(second);
  const retained = structuredClone(second.extra[key]);
  extension.afterConfigureGraph();
  assert.deepEqual(ids(second), disabledOrder);
  assert.deepEqual(second.save().extra[key], retained);
  settings[setting.id] = true;
  setting.onChange(true);
  assert.deepEqual(ids(second), disabledOrder);
  assert.deepEqual(second.save().extra[key].nodes, disabledOrder);
  assert.equal(snapshots, 2);

  // The switches are independent: read-only restores without rewriting the
  // stored record; write-only captures the current layout without applying it.
  for (const [save, restoreEnabled] of [
    [false, true],
    [true, false],
    [false, false],
    [true, true],
  ]) {
    settings[setting.id] = save;
    settings[restoreSetting.id] = restoreEnabled;
    second.extra[key] = { version: 1, nodes: [40, 30, 20, 10], subgraphs: [] };
    second.layers = [...second.nodes];
    extension.afterConfigureGraph();
    assert.deepEqual(ids(second), restoreEnabled ? [40, 30, 20, 10] : [10, 20, 30, 40]);
    second.layers.reverse();
    assert.deepEqual(second.save().extra[key].nodes, save ? ids(second) : [40, 30, 20, 10]);
  }
  // Missing settings use the requested defaults: restore on, save off.
  delete settings[setting.id];
  delete settings[restoreSetting.id];
  second.extra[key] = { version: 1, nodes: [40, 30, 20, 10], subgraphs: [] };
  second.layers = [...second.nodes];
  extension.afterConfigureGraph();
  assert.deepEqual(ids(second), [40, 30, 20, 10]);
  second.layers.reverse();
  assert.deepEqual(second.save().extra[key].nodes, [40, 30, 20, 10]);
  settings[setting.id] = true;
  second.layers = disabledOrder.map((id) => second.getNodeById(id));

  // Malformed records cannot rearrange any graph, including valid siblings.
  for (const record of [
    { version: 2, nodes: [10], subgraphs: [] },
    { version: 1, nodes: [10, '10'], subgraphs: [] },
    { version: 1, nodes: [null], subgraphs: [] },
    { version: 1, nodes: [10], subgraphs: [{ id: 'nested', nodes: [1, 1] }] },
    {
      version: 1,
      nodes: [10],
      subgraphs: [
        { id: 'nested', nodes: [] },
        { id: 'nested', nodes: [] },
      ],
    },
  ]) {
    second.extra[key] = record;
    extension.afterConfigureGraph();
    assert.deepEqual(ids(second), disabledOrder);
  }
  assert.deepEqual(toastSeverities(), ['warn']);

  // Existing metadata survives failed reads, with one visible warning rather
  // than a toast per automatic snapshot. No partial root/subgraph record writes.
  const incompatible = graph('incompatible', [1, 2]);
  incompatible.extra[key] = { version: 1, nodes: [2, 1], subgraphs: [] };
  app.rootGraph = incompatible;
  extension.beforeConfigureGraph();
  app.canvas.computeVisibleNodes = function () {
    return this.graph.layers.slice(1);
  };
  for (let index = 0; index < 3; index++) assert.deepEqual(incompatible.save().extra[key], incompatible.extra[key]);
  extension.afterConfigureGraph();
  assert.deepEqual(ids(incompatible), [1, 2]);
  assert.deepEqual(toastSeverities(), ['warn', 'warn']);

  // Old workflows have no stored order and keep their normal initial stacking.
  const old = graph('old', [2, 1]);
  app.rootGraph = old;
  app.canvas = canvasFor(old);
  extension.afterConfigureGraph();
  assert.deepEqual(ids(old), [2, 1]);
  assert.deepEqual(old.save().extra[key].nodes, [2, 1]);
});
