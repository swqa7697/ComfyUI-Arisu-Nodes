// Persist visual stacking independently of execution order and node-ID sorting.
import { app } from '../../../../scripts/app.js';

const SAVE_SETTING = 'Arisu.Workflow.SaveNodeLayers';
const RESTORE_SETTING = 'Arisu.Workflow.RestoreNodeLayers';
const KEY = 'arisu_node_layers';
const installed = new WeakMap();
const restoring = new WeakSet();
const warned = new WeakSet();

function report(graph) {
  if (warned.has(graph)) return;
  warned.add(graph);
  app.extensionManager?.toast?.add?.({
    severity: 'warn',
    summary: 'Node Layer Order',
    detail: 'Arisu could not read or restore the complete node layer order. Existing layer data was kept. Check frontend compatibility.',
    life: 10000,
  });
}

function graphNodes(graph) {
  return graph.nodes ?? graph._nodes ?? [];
}

function renderOrder(graph) {
  const canvas = app.canvas;
  if (typeof canvas?.computeVisibleNodes !== 'function' || typeof canvas?.bringToFront !== 'function') {
    throw new Error('Node layer API unavailable');
  }
  // Both renderers use the layout store through this canvas method. A separate
  // receiver includes offscreen nodes without changing the real canvas viewport.
  // Validate the full result so a frontend API change cannot silently lose layers.
  const nodes = canvas.computeVisibleNodes.call({
    graph,
    ctx: canvas.ctx,
    visible_area: [-Number.MAX_VALUE / 4, -Number.MAX_VALUE / 4, Number.MAX_VALUE / 2, Number.MAX_VALUE / 2],
  });
  const expected = new Set(graphNodes(graph));
  if (!Array.isArray(nodes) || nodes.length !== expected.size || new Set(nodes).size !== expected.size) {
    throw new Error('Incomplete node layer order');
  }
  for (const node of nodes) if (!expected.has(node)) throw new Error('Foreign node in layer order');
  return nodes;
}

function capture(root, data) {
  const subgraphs = [];
  // Subgraphs bypass onSerialize in current frontends. Keep their orders in the
  // root record, and do not mutate the shared extra object on a subgraph export.
  for (const definition of data.definitions?.subgraphs ?? []) {
    const graph = root.subgraphs?.get(definition.id);
    if (!graph) throw new Error('Subgraph unavailable');
    subgraphs.push({ id: definition.id, nodes: renderOrder(graph).map((node) => node.id) });
  }
  return { version: 1, nodes: renderOrder(root).map((node) => node.id), subgraphs };
}

function validOrder(value) {
  return (
    Array.isArray(value) &&
    value.every((id) => (typeof id === 'string' && id.length > 0) || (Number.isSafeInteger(id) && id >= 0)) &&
    new Set(value.map(String)).size === value.length
  );
}

function restore(root) {
  if (app.extensionManager?.setting?.get?.(RESTORE_SETTING) === false || restoring.has(root)) return;
  const record = root.extra?.[KEY];
  if (!record) return;
  if (
    record.version !== 1 ||
    !validOrder(record.nodes) ||
    !Array.isArray(record.subgraphs) ||
    !record.subgraphs.every((entry) => entry && typeof entry.id === 'string' && validOrder(entry.nodes)) ||
    new Set(record.subgraphs.map((entry) => entry.id)).size !== record.subgraphs.length
  ) {
    report(root);
    return;
  }
  restoring.add(root);
  try {
    const orders = [[root, record.nodes]];
    for (const entry of record.subgraphs) {
      const graph = root.subgraphs?.get(entry.id);
      if (graph) orders.push([graph, entry.nodes]);
    }
    // Read every graph before making changes. Missing/deleted IDs are harmless;
    // nodes added since the record remain above the restored nodes.
    const plans = orders.map(([graph, ids]) => {
      const current = renderOrder(graph);
      const remaining = new Map(current.map((node) => [String(node.id), node]));
      const ordered = [];
      for (const id of ids) {
        const node = remaining.get(String(id));
        if (node) ordered.push(node);
        remaining.delete(String(id));
      }
      ordered.push(...remaining.values());
      return { graph, current, ordered };
    });
    for (const { graph, current, ordered } of plans) {
      if (ordered.every((node, index) => node === current[index])) continue;
      for (const node of ordered) app.canvas.bringToFront.call({ graph }, node);
      if (!renderOrder(graph).every((node, index) => node === ordered[index])) throw new Error('Node layer restore failed');
    }
    app.canvas.setDirty?.(true, true);
  } catch {
    report(root);
  } finally {
    restoring.delete(root);
  }
}

function install() {
  const root = app.rootGraph;
  if (!root) return;
  const previous = installed.get(root);
  if (previous && previous === root.onSerialize) return;
  const onSerialize = root.onSerialize;
  const wrapper = function (data) {
    const result = onSerialize?.apply(this, arguments);
    if (app.extensionManager?.setting?.get?.(SAVE_SETTING) === true && !restoring.has(this) && !app.configuringGraph) {
      try {
        const record = capture(this, data);
        // Keep the last record with the live workflow too. Disabling the option
        // before a reload must not erase a record that was already saved.
        this.extra = { ...this.extra, [KEY]: structuredClone(record) };
        data.extra = { ...data.extra, [KEY]: record };
      } catch {
        report(this);
      }
    }
    return result;
  };
  root.onSerialize = wrapper;
  installed.set(root, wrapper);
}

app.registerExtension({
  name: 'Arisu.Common.NodeLayers',
  init: install,
  setup: install,
  beforeConfigureGraph: install,
  afterConfigureGraph() {
    install();
    restore(app.rootGraph);
  },
  settings: [
    {
      id: SAVE_SETTING,
      name: 'Save Node Layer Order',
      category: ['Arisu Nodes', 'Workflow', 'Save Node Layer Order'],
      type: 'boolean',
      defaultValue: false,
      tooltip: 'Record the current node overlap order when saving any workflow. Turning this off keeps existing layer records unchanged.',
      onChange(value) {
        if (value !== true) return;
        install();
        // Enabling starts with the current layout, rather than replaying a stale
        // record after edits made while the feature was disabled.
        if (!app.configuringGraph) app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.captureCanvasState?.();
      },
    },
    {
      id: RESTORE_SETTING,
      name: 'Restore Node Layer Order',
      category: ['Arisu Nodes', 'Workflow', 'Restore Node Layer Order'],
      type: 'boolean',
      defaultValue: true,
      tooltip:
        'Restore recorded node overlap order when loading any workflow, including subgraphs and history. Takes effect on the next load; does not enable recording.',
    },
  ],
});
