// Widget helpers shared by the pack's frontend scripts. No extension is
// registered here; ComfyUI loads the file like any other, which is harmless.

// The stock button widget's outer margin, and the gap between the cells of a row.
const MARGIN = 15;
const GAP = 4;

/** A button widget that is never written into the saved workflow. */
export function addButton(node, label, onClick) {
  const widget = node.addWidget("button", label, null, onClick);
  widget.serialize = false;
  widget.options.serialize = false;
  return widget;
}

function cellWidth(width, count) {
  return (width - 2 * MARGIN - GAP * (count - 1)) / count;
}

/**
 * One widget row holding several buttons side by side, never written into the saved workflow.
 *
 * LiteGraph lays widgets out one per row, so the row is a custom widget that
 * draws every button itself, in the stock button's colours, and maps a click
 * to the cell under it. `buttons` is `[{ label, onClick }]`.
 */
export function addButtonRow(node, buttons) {
  const widget = node.addCustomWidget({
    type: "arisu_button_row",
    name: buttons.map((button) => button.label).join(" / "),
    value: null,
    options: { serialize: false },
    draw(ctx, _node, width, y, height) {
      const { LiteGraph } = globalThis;
      const cell = cellWidth(width, buttons.length);
      const { fillStyle, strokeStyle, textAlign } = ctx;
      buttons.forEach((button, index) => {
        const x = MARGIN + index * (cell + GAP);
        ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
        ctx.fillRect(x, y, cell, height);
        ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR;
        ctx.strokeRect(x, y, cell, height);
        ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
        ctx.textAlign = "center";
        ctx.fillText(button.label, x + cell / 2, y + height * 0.7);
      });
      Object.assign(ctx, { fillStyle, strokeStyle, textAlign });
    },
    mouse(event, pos, owner) {
      // the canvas reports the press and the release; act once
      if (event.type !== "pointerdown") return false;
      const cell = cellWidth(owner.size[0], buttons.length);
      const index = Math.min(buttons.length - 1, Math.max(0, Math.floor((pos[0] - MARGIN) / (cell + GAP))));
      buttons[index].onClick();
      return true;
    },
  });
  widget.serialize = false;
  return widget;
}
