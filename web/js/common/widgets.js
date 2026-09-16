// Widget helpers shared by the pack's frontend scripts. No extension is
// registered here; ComfyUI loads the file like any other, which is harmless.

// The stock button widget's outer margin, and the gap between the cells of a row.
const MARGIN = 15;
const GAP = 4;
const pointerPositions = new WeakMap();

/** Track node-local hover without capturing gestures or changing click handlers. */
function trackPointer(node) {
  if (pointerPositions.has(node)) return;
  pointerPositions.set(node, null);
  node.redraw_on_mouse = true;
  const move = node.onMouseMove;
  node.onMouseMove = function (_event, position) {
    pointerPositions.set(this, position);
    return move?.apply(this, arguments);
  };
  const leave = node.onMouseLeave;
  node.onMouseLeave = function () {
    pointerPositions.set(this, null);
    this.setDirtyCanvas(true, false);
    return leave?.apply(this, arguments);
  };
}

function drawButton(ctx, node, label, x, y, width, height, disabled = false, clicked = false) {
  const { LiteGraph } = globalThis;
  const pointer = pointerPositions.get(node);
  const hovered = !disabled && pointer && pointer[0] >= x && pointer[0] <= x + width && pointer[1] >= y && pointer[1] <= y + height;
  ctx.save();
  ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
  ctx.fillRect(x, y, width, height);
  if (hovered || clicked) {
    const alpha = ctx.globalAlpha;
    ctx.globalAlpha *= clicked ? 0.18 : 0.08;
    ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
    ctx.fillRect(x, y, width, height);
    ctx.globalAlpha = alpha;
  }
  ctx.strokeStyle = hovered ? LiteGraph.WIDGET_TEXT_COLOR : LiteGraph.WIDGET_OUTLINE_COLOR;
  ctx.strokeRect(x, y, width, height);
  ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
  ctx.textAlign = 'center';
  ctx.fillText(label, x + width / 2, y + height * 0.7);
  ctx.restore();
}

/** A button widget that is never written into the saved workflow. */
export function addButton(node, label, onClick) {
  trackPointer(node);
  const widget = node.addWidget('button', label, null, onClick);
  widget.draw = function (ctx, owner, width, y, height) {
    drawButton(
      ctx,
      owner,
      this.label || this.name,
      MARGIN,
      y,
      width - 2 * MARGIN,
      height,
      this.disabled || this.computedDisabled,
      this.clicked,
    );
    this.clicked = false;
  };
  widget.serialize = false;
  widget.options.serialize = false;
  return widget;
}

/** Write `value` into `widget` the way a user edit does: the value, its callback, the node's hook, a repaint. */
export function setWidget(node, widget, value) {
  const previous = widget.value;
  widget.value = value;
  widget.callback?.(value);
  node.onWidgetChanged?.(widget.name, value, previous, widget);
  node.setDirtyCanvas(true, true);
}

/**
 * Keep `widget` out of sight and take away its socket; the node shrinks to fit.
 *
 * The classic canvas skips a widget flagged `hidden`, the Vue renderer ("Nodes 2.0")
 * reads `options.hidden`, so both are set. The socket goes because the frontend
 * keeps one for every widget input and would still accept a link into it, feeding
 * the run a value nobody can see (see path_builder.js). Neither flag is saved: a
 * loaded workflow needs hiding again in `onConfigure`.
 */
export function hideWidget(node, widget) {
  widget.hidden = true;
  widget.options ??= {};
  widget.options.hidden = true;
  const socket = node.inputs?.findIndex((input) => (input.widget?.name ?? input.name) === widget.name) ?? -1;
  if (socket !== -1) node.removeInput(socket);
  node.setSize(node.computeSize());
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
  trackPointer(node);
  const widget = node.addCustomWidget({
    type: 'arisu_button_row',
    name: buttons.map((button) => button.label).join(' / '),
    value: null,
    options: { serialize: false },
    draw(ctx, owner, width, y, height) {
      const cell = cellWidth(width, buttons.length);
      buttons.forEach((button, index) => {
        drawButton(ctx, owner, button.label, MARGIN + index * (cell + GAP), y, cell, height, this.disabled || this.computedDisabled);
      });
    },
    mouse(event, pos, owner) {
      // the canvas reports the press and the release; act once
      if (event.type !== 'pointerdown') return false;
      const cell = cellWidth(owner.size[0], buttons.length);
      const index = Math.min(buttons.length - 1, Math.max(0, Math.floor((pos[0] - MARGIN) / (cell + GAP))));
      buttons[index].onClick();
      return true;
    },
  });
  widget.serialize = false;
  return widget;
}
