// One workflow-provenance boundary shared by every file-selecting node.
import { app } from '../../../../scripts/app.js';

const owners = new Map();
const knownWorkflows = new WeakSet();
let context;
let queue = Promise.resolve();
const wrapped = new WeakSet();

export function registerSelectionOwner(type, owner) {
  owners.set(type, owner);
}
export function preservingSelections() {
  return context?.preserve === true;
}

function sanitize(data) {
  const copy = structuredClone(data);
  function visit(value) {
    if (!value || typeof value !== 'object') return;
    const owner = owners.get(value.type ?? value.class_type);
    if (owner) {
      const stored = value.widgets_values;
      for (const [name, position, replacement] of owner.fields) {
        if (Array.isArray(stored)) stored[position] = replacement;
        else if (stored && typeof stored === 'object') stored[name] = replacement;
        if (value.inputs && !Array.isArray(value.inputs)) value.inputs[name] = replacement;
      }
      delete value.imgs;
      delete value.images;
    }
    for (const child of Object.values(value)) visit(child);
  }
  visit(copy);
  return copy;
}

function invalidateGraph(graph, visited = new Set()) {
  if (!graph || visited.has(graph)) return;
  visited.add(graph);
  for (const node of graph.nodes ?? graph._nodes ?? []) owners.get(node.type)?.invalidate?.(node);
  for (const child of graph.subgraphs?.values() ?? []) invalidateGraph(child, visited);
}

export function installSelectionGuards() {
  for (const method of ['loadGraphData', 'loadApiJson']) {
    const original = app[method];
    if (!original || wrapped.has(original)) continue;
    const wrapper = function (...args) {
      const run = async () => {
        const current = app.extensionManager?.workflow?.activeWorkflow;
        if (current && typeof current === 'object') knownWorkflows.add(current);
        const workflow = method === 'loadGraphData' ? args[3] : undefined;
        const preserve = !!workflow && typeof workflow === 'object' && (workflow.isPersisted === true || knownWorkflows.has(workflow));
        invalidateGraph(app.rootGraph);
        context = { preserve };
        try {
          if (!preserve && args[0]) args[0] = sanitize(args[0]);
          const result = await original.apply(this, args);
          const active = app.extensionManager?.workflow?.activeWorkflow;
          if (active && typeof active === 'object') knownWorkflows.add(active);
          return result;
        } finally {
          context = undefined;
        }
      };
      const result = queue.then(run);
      queue = result.catch(() => {});
      return result;
    };
    wrapped.add(wrapper);
    app[method] = wrapper;
  }
}
