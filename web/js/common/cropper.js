// The crop dialog of Load Image (Browse): a box dragged over the picked image.
//
// `cropImage(img, initial)` shows a loaded image in a native <dialog> with a
// crop box over it and resolves to the chosen box, `{ x, y, w, h }` in the
// image's own pixels, or `null` when the dialog is cancelled. A drag on the
// image draws a new box, a drag on the box moves it, and its eight handles
// resize it. An aspect ratio typed or picked in the bar (`16:9`, `1.5`, blank
// for free) fits the box to it and holds it through every drag; reset is the
// whole image, which the caller treats as no crop at all.
//
// Nothing here knows about nodes, widgets or routes: the caller loads the
// image and stores the result. The geometry is pure functions over integer
// rectangles inside the image; the pointer handlers only turn events into
// calls to them, so a drag can be replayed with plain objects.

import { el } from './dom.js';

const RATIO_PRESETS = ['1:1', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16'];
const RATIO_LIST_ID = 'arisu-cropper-ratios';
/** Each handle's place on the box as (x, y) fractions; a drag moves the sides it sits on and holds the others. */
const HANDLES = { nw: [0, 0], n: [0.5, 0], ne: [1, 0], e: [1, 0.5], se: [1, 1], s: [0.5, 1], sw: [0, 1], w: [0, 0.5] };
const MIN_SIDE = 1;

const STYLE = `
.arisu-cropper { width: min(1100px, 92vw); height: min(800px, 90vh); padding: 0; border: 1px solid var(--border-color, #444);
  border-radius: 14px; background: var(--comfy-menu-bg, #202020); color: var(--fg-color, #ddd); font-family: inherit;
  font-size: 13px; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55); overflow: hidden; }
.arisu-cropper[open] { display: flex; flex-direction: column; animation: arisu-cropper-pop 160ms ease-out; }
.arisu-cropper[open]::backdrop { background: rgba(0, 0, 0, 0.55); backdrop-filter: blur(3px); }
.arisu-cropper :where(button, input) { font: inherit; color: inherit; border: 1px solid var(--border-color, #444); border-radius: 8px;
  background: var(--comfy-input-bg, #333); transition: background-color 150ms ease, border-color 150ms ease; }
.arisu-cropper :where(button) { padding: 6px 12px; cursor: pointer; }
.arisu-cropper :where(input) { padding: 6px 10px; }
.arisu-cropper button:hover { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-cropper :focus-visible { outline: 2px solid var(--p-primary-color, #6ea8fe); outline-offset: 2px; }
.arisu-cropper input:focus-visible { outline: none; border-color: var(--p-primary-color, #6ea8fe); }
.arisu-cropper-bar { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #444); }
.arisu-cropper-bar label { color: var(--descrip-text, #999); }
.arisu-cropper-ratio { width: 96px; }
.arisu-cropper-readout { flex: 1; text-align: center; color: var(--descrip-text, #999); font-variant-numeric: tabular-nums; }
.arisu-cropper-apply { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-cropper-body { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 16px; background: #111; }
.arisu-cropper-stage { position: relative; display: inline-block; line-height: 0; overflow: hidden; touch-action: none; user-select: none;
  cursor: crosshair; }
.arisu-cropper-image { display: block; max-width: calc(min(1100px, 92vw) - 34px); max-height: calc(min(800px, 90vh) - 92px); }
.arisu-cropper-box { position: absolute; box-sizing: border-box; border: 1px solid #fff; outline: 1px solid rgba(0, 0, 0, 0.6);
  box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.5); cursor: move; }
.arisu-cropper-handle { position: absolute; box-sizing: border-box; width: 12px; height: 12px; margin: -6px; border-radius: 2px;
  background: #fff; border: 1px solid rgba(0, 0, 0, 0.6); }
@keyframes arisu-cropper-pop { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
@media (prefers-reduced-motion: reduce) {
  .arisu-cropper, .arisu-cropper::backdrop, .arisu-cropper * { animation: none !important; transition: none !important; }
}
`;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function fullRect(bounds) {
  return { x: 0, y: 0, w: bounds.w, h: bounds.h };
}

/** `rect` with whole-pixel sides of at least one pixel, shrunk and moved to lie inside `bounds`. */
function clampRect(rect, bounds) {
  const w = clamp(Math.round(rect.w), MIN_SIDE, bounds.w);
  const h = clamp(Math.round(rect.h), MIN_SIDE, bounds.h);
  return { x: clamp(Math.round(rect.x), 0, bounds.w - w), y: clamp(Math.round(rect.y), 0, bounds.h - h), w, h };
}

/** The largest box of `ratio` (width over height) inside `rect`, centred in it; `rect` itself when the ratio is free. */
function fitRatio(rect, ratio, bounds) {
  if (ratio == null) return rect;
  let w = rect.w;
  let h = w / ratio;
  if (h > rect.h) {
    h = rect.h;
    w = h * ratio;
  }
  return clampRect({ x: rect.x + (rect.w - w) / 2, y: rect.y + (rect.h - h) / 2, w, h }, bounds);
}

/** A new box between the pressed point and the pointer; with a ratio, the largest fitting one, held at the pressed corner. */
function rectFromDrag(start, point, ratio, bounds) {
  const extent = {
    x: Math.min(start.x, point.x),
    y: Math.min(start.y, point.y),
    w: Math.abs(point.x - start.x),
    h: Math.abs(point.y - start.y),
  };
  if (ratio == null) return clampRect(extent, bounds);
  const fitted = fitRatio(extent, ratio, bounds);
  const x = point.x < start.x ? start.x - fitted.w : start.x;
  const y = point.y < start.y ? start.y - fitted.h : start.y;
  return clampRect({ x, y, w: fitted.w, h: fitted.h }, bounds);
}

function moveRect(origin, dx, dy, bounds) {
  return clampRect({ x: origin.x + dx, y: origin.y + dy, w: origin.w, h: origin.h }, bounds);
}

/**
 * `origin` with the sides under `handle` dragged to `point`, the other sides held. With a ratio a corner keeps the
 * box inside the pointer's reach, an edge leads with its own axis, and the box shrinks rather than leave the image.
 */
function resizeRect(origin, handle, point, ratio, bounds) {
  const [ax, ay] = HANDLES[handle];
  const left = origin.x;
  const top = origin.y;
  const right = origin.x + origin.w;
  const bottom = origin.y + origin.h;
  const cx = left + origin.w / 2;
  const cy = top + origin.h / 2;
  let w = Math.max(MIN_SIDE, ax === 0 ? right - point.x : ax === 1 ? point.x - left : origin.w);
  let h = Math.max(MIN_SIDE, ay === 0 ? bottom - point.y : ay === 1 ? point.y - top : origin.h);
  if (ratio != null) {
    if (ax === 0.5) w = h * ratio;
    else if (ay === 0.5 || w / h > ratio) h = w / ratio;
    else w = h * ratio;
    const roomW = ax === 0 ? right : ax === 1 ? bounds.w - left : 2 * Math.min(cx, bounds.w - cx);
    const roomH = ay === 0 ? bottom : ay === 1 ? bounds.h - top : 2 * Math.min(cy, bounds.h - cy);
    const scale = Math.min(1, roomW / w, roomH / h);
    w *= scale;
    h *= scale;
  }
  const x = ax === 0 ? right - w : ax === 1 ? left : cx - w / 2;
  const y = ay === 0 ? bottom - h : ay === 1 ? top : cy - h / 2;
  return clampRect({ x, y, w, h }, bounds);
}

/** The width-over-height ratio of `text` (`16:9`, `16/9`, `1.78`), or `null` for free (blank, `free`, or nonsense). */
function parseRatio(text) {
  const value = text.trim().toLowerCase();
  if (!value || value === 'free') return null;
  const [w, h = '1'] = value.split(/[:/x]/);
  const ratio = Number(w) / Number(h);
  return Number.isFinite(ratio) && ratio > 0 ? ratio : null;
}

/**
 * Let the user crop `img`, a loaded image, starting from `initial` (`{ x, y, w, h }` in image pixels) or the whole
 * image; resolves to the applied box, or `null` when the dialog is cancelled.
 */
export function cropImage(img, initial) {
  const bounds = { w: img.naturalWidth, h: img.naturalHeight };
  let rect = initial ? clampRect(initial, bounds) : fullRect(bounds);
  let ratio = null;
  let drag = null;
  let result = null;

  const readout = el('output', { className: 'arisu-cropper-readout' });
  const ratioField = el('input', {
    className: 'arisu-cropper-ratio',
    type: 'text',
    placeholder: 'free',
    title: 'aspect ratio, width:height; blank for free',
    onchange: () => {
      ratio = parseRatio(ratioField.value);
      show(fitRatio(rect, ratio, bounds));
    },
  });
  ratioField.setAttribute('list', RATIO_LIST_ID);
  const handles = Object.entries(HANDLES).map(([handle, [ax, ay]]) =>
    el('div', { className: 'arisu-cropper-handle', handle, style: `left: ${ax * 100}%; top: ${ay * 100}%; cursor: ${handle}-resize;` }),
  );
  const box = el('div', { className: 'arisu-cropper-box' }, handles);
  img.className = 'arisu-cropper-image';
  img.draggable = false;
  const stage = el('div', { className: 'arisu-cropper-stage', onpointerdown, onpointermove, onpointerup, onpointercancel: onpointerup }, [
    img,
    box,
  ]);
  const dialog = el(
    'dialog',
    {
      className: 'arisu-cropper',
      onclick: (event) => (event.target === dialog ? dialog.close() : undefined),
    },
    [
      el('style', { textContent: STYLE }),
      el('div', { className: 'arisu-cropper-bar' }, [
        el('label', { textContent: 'ratio' }),
        ratioField,
        el(
          'datalist',
          { id: RATIO_LIST_ID },
          RATIO_PRESETS.map((value) => el('option', { value })),
        ),
        readout,
        el('button', { textContent: 'reset', title: 'the whole image: no crop', onclick: reset }),
        el('button', { textContent: 'cancel', onclick: () => dialog.close() }),
        el('button', { className: 'arisu-cropper-apply', textContent: 'apply', onclick: apply }),
      ]),
      el('div', { className: 'arisu-cropper-body' }, [stage]),
    ],
  );

  /** The pointer's place in image pixels, held inside the image. */
  function pointAt(event) {
    const frame = img.getBoundingClientRect();
    return {
      x: clamp(Math.round(((event.clientX - frame.left) / frame.width) * bounds.w), 0, bounds.w),
      y: clamp(Math.round(((event.clientY - frame.top) / frame.height) * bounds.h), 0, bounds.h),
    };
  }

  function show(next) {
    rect = next;
    const pct = (value, whole) => `${(value / whole) * 100}%`;
    box.style = `left: ${pct(rect.x, bounds.w)}; top: ${pct(rect.y, bounds.h)}; width: ${pct(rect.w, bounds.w)}; height: ${pct(rect.h, bounds.h)};`;
    readout.textContent = `${rect.w} × ${rect.h} at ${rect.x}, ${rect.y}`;
  }

  function onpointerdown(event) {
    if (event.button) return; // the primary button only
    const point = pointAt(event);
    const handle = event.target?.handle;
    const mode = handle ? 'resize' : event.target === box ? 'move' : 'draw';
    drag = { mode, handle, start: point, origin: rect };
    stage.setPointerCapture?.(event.pointerId);
    if (mode === 'draw') show(rectFromDrag(point, point, ratio, bounds));
  }

  function onpointermove(event) {
    if (!drag) return;
    const point = pointAt(event);
    if (drag.mode === 'move') show(moveRect(drag.origin, point.x - drag.start.x, point.y - drag.start.y, bounds));
    else if (drag.mode === 'resize') show(resizeRect(drag.origin, drag.handle, point, ratio, bounds));
    else show(rectFromDrag(drag.start, point, ratio, bounds));
  }

  function onpointerup() {
    drag = null;
  }

  function reset() {
    ratio = null;
    ratioField.value = '';
    show(fullRect(bounds));
  }

  function apply() {
    result = rect;
    dialog.close();
  }

  return new Promise((resolve) => {
    dialog.onclose = () => {
      dialog.remove();
      resolve(result);
    };
    document.body.append(dialog);
    dialog.showModal();
    show(rect);
  });
}
