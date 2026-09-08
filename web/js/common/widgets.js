// Widget helpers shared by the pack's frontend scripts. No extension is
// registered here; ComfyUI loads the file like any other, which is harmless.

/** A button widget that is never written into the saved workflow. */
export function addButton(node, label, onClick) {
  const widget = node.addWidget("button", label, null, onClick);
  widget.serialize = false;
  widget.options.serialize = false;
  return widget;
}
