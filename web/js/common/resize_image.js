// Resize Image: a "settings…" button that opens the node's resize options in a dialog.
//
// Only `width` and `height` matter at a glance; the other five inputs (the resampling
// method, how proportions are kept, the pad colour, the crop position, the pixel grid)
// change rarely and would double the node's height. This script hides them, the way
// load_image.js hides its crop, and the button edits them in the dialog of
// settings_dialog.js. They stay ordinary widgets: saved with the workflow, sent with
// the prompt, and restored by a loaded workflow, whose `onConfigure` hides them again.
//
// A hidden widget also loses its socket (see path_builder.js for why): the settings are
// edited here, not fed by links. The dialog's controls come from the node definition,
// so a combo lists what the backend declares and a number keeps its declared bounds;
// nothing about the options is repeated here.
//
// The preview needs no code: the node returns its result as a ui preview, which the
// frontend draws on the node in both renderers.

import { app } from '../../../../scripts/app.js';
import { editSettings } from './settings_dialog.js';
import { addButton, hideWidget, setWidget } from './widgets.js';

const NODE_TYPE = 'ArisuResizeImage';
const TITLE = 'Resize Image settings';
/** The widgets the dialog edits, in its row order. */
const CONFIG_WIDGETS = ['upscale_method', 'keep_proportion', 'pad_color', 'crop_position', 'divisible_by'];
const COLOR_WIDGETS = new Set(['pad_color']);

/** The dialog's fields from the node definition, whose inputs are `[type or choices, options]`. */
function fieldsFrom(nodeData) {
  const inputs = { ...nodeData.input?.required, ...nodeData.input?.optional };
  return CONFIG_WIDGETS.filter((name) => name in inputs).map((name) => {
    const [type, options = {}] = inputs[name];
    const combo = Array.isArray(type);
    const kind = combo ? 'combo' : type === 'INT' ? 'number' : COLOR_WIDGETS.has(name) ? 'color' : 'text';
    return {
      name,
      kind,
      values: combo ? type : [],
      min: options.min,
      max: options.max,
      step: options.step,
      default: options.default ?? (combo ? type[0] : ''),
      tooltip: options.tooltip,
    };
  });
}

function configWidgets(node) {
  return CONFIG_WIDGETS.map((name) => node.widgets?.find((widget) => widget.name === name)).filter(Boolean);
}

function hideConfig(node) {
  for (const widget of configWidgets(node)) hideWidget(node, widget);
}

/** Open the dialog on the widgets' values; apply writes the fields that changed, the way a user edit would. */
async function openSettings(node, fields) {
  const widgets = configWidgets(node);
  const values = Object.fromEntries(widgets.map((widget) => [widget.name, widget.value]));
  const edited = await editSettings(TITLE, fields, values);
  if (!edited) return;
  for (const widget of widgets) {
    if (widget.name in edited && edited[widget.name] !== widget.value) setWidget(node, widget, edited[widget.name]);
  }
}

app.registerExtension({
  name: 'Arisu.Common.ResizeImage',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;
    const fields = fieldsFrom(nodeData);

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      addButton(this, 'settings…', () => openSettings(this, fields));
      hideConfig(this);
    };

    // configure() has restored the widget values and the saved sockets by the time it calls this
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      hideConfig(this);
    };
  },
});
