// Plain-object doubles for the LiteGraph objects the pack's scripts touch: a graph,
// its nodes, and their widgets, inputs, and outputs. The colour constants are what
// widgets.js reads off the global when it draws a button row.
globalThis.LiteGraph = {
  WIDGET_BGCOLOR: '#222',
  WIDGET_OUTLINE_COLOR: '#666',
  WIDGET_TEXT_COLOR: '#ddd',
};

export function makeGraph(id = 'root') {
  return { id, nodes: [] };
}

/**
 * A node double, listed in `graph` when one is given.
 *
 * `widgets` are `{ name, value }`; `inputs` are `{ name, link, widget }`, where
 * `widget.name` is how LiteGraph pairs a socket with its widget (defaults to the
 * input's own name); `outputs` are names.
 */
export function makeNode({ id, type, graph = null, widgets = [], inputs = [], outputs = [] }) {
  const node = {
    id,
    type,
    graph,
    mode: 0,
    size: [300, 100],
    properties: {},
    widgets: widgets.map((widget) => ({ ...widget })),
    inputs: inputs.map((input) => ({ type: 'STRING', link: null, widget: { name: input.name }, ...input })),
    outputs: outputs.map((name) => ({ name })),
    addWidget(widgetType, name, value, callback, options) {
      const widget = { type: widgetType, name, value, callback, options: options ?? {} };
      this.widgets.push(widget);
      return widget;
    },
    addDOMWidget(name, type, element, options) {
      const widget = { name, type, element, options };
      this.widgets.push(widget);
      return widget;
    },
    addCustomWidget(widget) {
      this.widgets.push(widget);
      return widget;
    },
    addInput(name, inputType, extra) {
      this.inputs.push({ name, type: inputType, link: null, ...extra });
    },
    removeInput(index) {
      this.inputs.splice(index, 1);
    },
    disconnectInput(index) {
      this.inputs[index].link = null;
    },
    setSize(size) {
      this.size = size;
      this.onResize?.(size);
    },
    computeSize() {
      return this.size;
    },
    setDirtyCanvas() {},
  };
  graph?.nodes.push(node);
  return node;
}
