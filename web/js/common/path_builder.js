// Path Builder: show one text field, grow and shrink with "+ field" / "- field".
//
// The backend declares every field (a V3 node must list its input ids up
// front), so this script only hides the ones past the current count. The count
// lives in node.properties so it survives save and reload; a hidden field is
// cleared so stale text never reaches the join.
import { app } from "../../../scripts/app.js";

const NODE_TYPE = "ArisuPathBuilder";
const COUNT_PROPERTY = "arisuSegments";
const FIELD_PREFIX = "segment_";

function fieldIndex(widget) {
  return Number(widget.name.slice(FIELD_PREFIX.length));
}

function fieldWidgets(node) {
  return (node.widgets ?? []).filter((widget) => widget.name.startsWith(FIELD_PREFIX)).sort((a, b) => fieldIndex(a) - fieldIndex(b));
}

function currentCount(node) {
  const stored = Number(node.properties?.[COUNT_PROPERTY]);
  return Number.isFinite(stored) && stored >= 1 ? stored : 1;
}

/** The stored count, raised to cover every field that holds text (older or hand-edited workflows). */
function restoredCount(node) {
  return fieldWidgets(node).reduce(
    (count, widget) => (String(widget.value ?? "").trim() ? Math.max(count, fieldIndex(widget)) : count),
    currentCount(node),
  );
}

function applyCount(node, count) {
  const widgets = fieldWidgets(node);
  const clamped = Math.min(Math.max(1, count), widgets.length);
  node.properties[COUNT_PROPERTY] = clamped;
  for (const widget of widgets) {
    const hidden = fieldIndex(widget) > clamped;
    if (hidden && !widget.hidden) widget.value = "";
    widget.hidden = hidden;
  }
  node.setSize(node.computeSize());
  node.setDirtyCanvas(true, true);
}

function addButton(node, label, onClick) {
  const widget = node.addWidget("button", label, null, onClick);
  widget.serialize = false;
  widget.options.serialize = false;
  return widget;
}

app.registerExtension({
  name: "Arisu.Common.PathBuilder",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      addButton(this, "+ field", () => applyCount(this, currentCount(this) + 1));
      addButton(this, "- field", () => applyCount(this, currentCount(this) - 1));
      applyCount(this, 1);
    };

    // configure() has restored properties and widget values by the time it calls this
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      applyCount(this, restoredCount(this));
    };
  },
});
