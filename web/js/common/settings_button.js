// A settings button for widgets a node keeps out of sight, shared by the pack's scripts.
//
// Some inputs change rarely and would double a node's height. `installSettingsButton`
// hides them, the way load_image.js hides its crop, and adds a button that edits them in
// the dialog of settings_dialog.js. They stay ordinary widgets: saved with the workflow,
// sent with the prompt, and restored by a loaded workflow, whose `onConfigure` hides them
// again.
//
// A hidden widget also loses its socket (see path_builder.js for why): the settings are
// edited here, not fed by links. The dialog's controls come from the node definition, so
// a combo lists what the backend declares and a number keeps its declared bounds; nothing
// about the options is repeated in the scripts. A combo arrives in one of two shapes: V3
// declares it as `["COMBO", { options }]`, the V1 form is `[[choices], options]`.

import { editSettings } from './settings_dialog.js';
import { addButton, hideWidget, setWidget } from './widgets.js';

/** The dialog's fields for `names` from the node definition, whose inputs are `[type or choices, options]`. */
function fieldsFrom(nodeData, names, colorWidgets) {
  const inputs = { ...nodeData.input?.required, ...nodeData.input?.optional };
  return names
    .filter((name) => name in inputs)
    .map((name) => {
      const [type, options = {}] = inputs[name];
      const choices = Array.isArray(type) ? type : type === 'COMBO' ? (options.options ?? []) : null;
      const kind = choices ? 'combo' : type === 'INT' ? 'number' : colorWidgets.has(name) ? 'color' : 'text';
      return {
        name,
        kind,
        values: choices ?? [],
        min: options.min,
        max: options.max,
        step: options.step,
        default: options.default ?? choices?.[0] ?? '',
        tooltip: options.tooltip,
      };
    });
}

function configWidgets(node, names) {
  return names.map((name) => node.widgets?.find((widget) => widget.name === name)).filter(Boolean);
}

function hideConfig(node, names) {
  for (const widget of configWidgets(node, names)) hideWidget(node, widget);
}

/** Open the dialog on the widgets' values; apply writes the fields that changed, the way a user edit would. */
async function openSettings(node, names, title, fields) {
  const widgets = configWidgets(node, names);
  const values = Object.fromEntries(widgets.map((widget) => [widget.name, widget.value]));
  const edited = await editSettings(title, fields, values);
  if (!edited) return;
  for (const widget of widgets) {
    if (widget.name in edited && edited[widget.name] !== widget.value) setWidget(node, widget, edited[widget.name]);
  }
}

/**
 * Wrap `nodeType`'s hooks so every node hides the `widgets` named and gets a `label` button that edits them in a
 * dialog titled `title`, in that order; `colorWidgets` names the text widgets that get a colour picker.
 */
export function installSettingsButton(nodeType, nodeData, { label, title, widgets, colorWidgets = [] }) {
  const fields = fieldsFrom(nodeData, widgets, new Set(colorWidgets));

  const onNodeCreated = nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated = function () {
    onNodeCreated?.apply(this, arguments);
    addButton(this, label, () => openSettings(this, widgets, title, fields));
    hideConfig(this, widgets);
  };

  // configure() has restored the widget values and the saved sockets by the time it calls this
  const onConfigure = nodeType.prototype.onConfigure;
  nodeType.prototype.onConfigure = function () {
    onConfigure?.apply(this, arguments);
    hideConfig(this, widgets);
  };
}
