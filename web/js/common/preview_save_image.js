// Preview & Save Image: a "save" button that writes the previewed images without queueing a run.
//
// A run only writes the preview to ComfyUI's temp directory, like Preview Image.
// The button posts the preview references the frontend already holds for the
// node (app.nodeOutputs) to the pack's /arisu/save_image route, which copies
// them under the output directory at `path`, upscaling first when the Upscale
// variant has a model selected. Nothing goes through the prompt queue.
//
// `path` and `upscale_model` are read from the widgets at click time, so editing
// them after a run changes where the next click saves. A widget fed by a link
// holds no value of its own; the route then gets the value the run recorded in
// the node's outputs.

import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { addButton } from './widgets.js';

const NODE_TYPES = ['ArisuPreviewSaveImage', 'ArisuPreviewSaveImageUpscale'];
const ROUTE = '/arisu/save_image';
const RECORDED_WIDGETS = ['path', 'upscale_model'];

function toast(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Preview & Save Image', detail, life: 8000 });
}

/** The node's last outputs: keyed by id in the root graph, by "<subgraph id>:<id>" inside a subgraph. */
function outputsOf(node) {
  const root = app.rootGraph ?? app.graph;
  const key = node.graph && node.graph !== root ? `${node.graph.id}:${node.id}` : String(node.id);
  return app.nodeOutputs?.[key];
}

function isLinked(node, name) {
  return node.inputs?.some((input) => input.widget?.name === name && input.link != null) ?? false;
}

function widgetValue(node, name, outputs) {
  const widget = node.widgets?.find((candidate) => candidate.name === name);
  if (!widget) return undefined;
  return isLinked(node, name) ? outputs[name]?.[0] : widget.value;
}

function savedName(file) {
  return file.subfolder ? `${file.subfolder}/${file.filename}` : file.filename;
}

async function save(node, button) {
  const outputs = outputsOf(node);
  if (!outputs?.images?.length) {
    toast('warn', 'Nothing to save yet: run the workflow first, then click save.');
    return;
  }
  const body = { images: outputs.images };
  for (const name of RECORDED_WIDGETS) {
    const value = widgetValue(node, name, outputs);
    if (value !== undefined) body[name] = value;
  }
  button.disabled = true;
  node.setDirtyCanvas(true, true);
  try {
    const response = await api.fetchApi(ROUTE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error ?? response.statusText);
    toast('success', `Saved ${data.saved.length} image(s): output/${data.saved.map(savedName).join(', output/')}`);
  } catch (error) {
    toast('error', `Save failed: ${error.message}`);
  } finally {
    button.disabled = false;
    node.setDirtyCanvas(true, true);
  }
}

app.registerExtension({
  name: 'Arisu.Common.PreviewSaveImage',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!NODE_TYPES.includes(nodeData.name)) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      const button = addButton(this, 'save', () => save(this, button));
    };
  },
});
