// Path Builder: show one text field, grow and shrink with the "+ field" / "- field" button row.
//
// The backend declares every field (a V3 node must list its input ids up
// front), so this script only hides the ones past the current count. The count
// lives in node.properties so it survives save and reload; a hidden field is
// cleared so stale text never reaches the join.
//
// A hidden field also loses its input socket. The frontend keeps a socket for
// every widget input and positions it from the widget's last y, so a hidden
// widget's socket would sit on the button row, still accepting a STRING link
// whose value would reach the join in place of the cleared text.
import { app } from "../../../../scripts/app.js";
import { addButtonRow } from "./widgets.js";

const NODE_TYPE = "ArisuPathBuilder";
const COUNT_PROPERTY = "arisuSegments";
const FIELD_PREFIX = "segment_";
// LiteGraph's RenderShape.HollowCircle, the socket shape of an optional input.
const OPTIONAL_SOCKET_SHAPE = 7;

/**
 * The `input.widget` descriptors of removed sockets, per node. The frontend
 * hangs a private config getter on that object; keeping it lets a field shown
 * again in the same session keep primitive-node type matching.
 */
const removedDescriptors = new WeakMap();

function fieldIndex(widget) {
  return Number(widget.name.slice(FIELD_PREFIX.length));
}

function fieldWidgets(node) {
  return (node.widgets ?? []).filter((widget) => widget.name.startsWith(FIELD_PREFIX)).sort((a, b) => fieldIndex(a) - fieldIndex(b));
}

function socketIndex(node, name) {
  return (node.inputs ?? []).findIndex((input) => input.widget?.name === name);
}

function currentCount(node) {
  const stored = Number(node.properties?.[COUNT_PROPERTY]);
  return Number.isFinite(stored) && stored >= 1 ? stored : 1;
}

/** The stored count, raised to cover every field that holds text or a link (older or hand-edited workflows). */
function restoredCount(node) {
  return fieldWidgets(node).reduce((count, widget) => {
    const linked = node.inputs?.[socketIndex(node, widget.name)]?.link != null;
    return linked || String(widget.value ?? "").trim() ? Math.max(count, fieldIndex(widget)) : count;
  }, currentCount(node));
}

function removeSocket(node, name) {
  const index = socketIndex(node, name);
  if (index === -1) return;
  if (!removedDescriptors.has(node)) removedDescriptors.set(node, new Map());
  removedDescriptors.get(node).set(name, node.inputs[index].widget);
  // disconnects the link and renumbers the links of the sockets after it
  node.removeInput(index);
}

function addSocket(node, name) {
  if (socketIndex(node, name) !== -1) return;
  const template = (node.inputs ?? []).find((input) => input.widget?.name.startsWith(FIELD_PREFIX));
  node.addInput(name, template?.type ?? "STRING", {
    shape: template?.shape ?? OPTIONAL_SOCKET_SHAPE,
    localized_name: name,
    widget: removedDescriptors.get(node)?.get(name) ?? { name },
  });
}

function applyCount(node, count) {
  const widgets = fieldWidgets(node);
  const clamped = Math.min(Math.max(1, count), widgets.length);
  node.properties[COUNT_PROPERTY] = clamped;
  for (const widget of widgets) {
    const hidden = fieldIndex(widget) > clamped;
    if (hidden && !widget.hidden) widget.value = "";
    widget.hidden = hidden;
    if (hidden) removeSocket(node, widget.name);
    else addSocket(node, widget.name);
  }
  node.setSize(node.computeSize());
  node.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: "Arisu.Common.PathBuilder",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      addButtonRow(this, [
        { label: "+ field", onClick: () => applyCount(this, currentCount(this) + 1) },
        { label: "- field", onClick: () => applyCount(this, currentCount(this) - 1) },
      ]);
      applyCount(this, 1);
    };

    // configure() has restored properties, widget values, and the saved sockets by the time it calls this
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      applyCount(this, restoredCount(this));
    };
  },
});
