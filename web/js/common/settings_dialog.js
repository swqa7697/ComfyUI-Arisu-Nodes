// A settings dialog for widgets a node keeps out of sight: a form in a native <dialog>.
//
// `editSettings(title, fields, values)` shows one row per field, seeded from `values`
// by field name, and resolves to the edited values, or `null` when the dialog is
// cancelled: cancel, ✕, Escape, or a click on the backdrop. A field is
// `{ name, kind, values, min, max, step, default, tooltip }`. `combo` is a <select>
// over `values`; `number` an <input type="number"> whose result is a rounded integer
// held to min..max (a blank or unreadable field keeps the value it opened with);
// `text` a text field; `color` a text field with a colour picker beside it, kept in
// sync both ways. reset puts every field back to its declared default; apply reads
// the controls back.
//
// Nothing here knows about nodes or widgets: the caller reads its widgets and writes
// the result. The colour helpers are pure functions over strings, in the forms
// core.parse_pad_color accepts on the other side: `r, g, b` (0-255, or 0-1 when a
// part has a decimal point), `#rgb` / `#rrggbb` / `#rrggbbaa`, one grey value. A
// colour name is left to the backend and leaves the picker where it is.

import { el } from './dom.js';

const HEX_COLOR = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;

const STYLE = `
.arisu-settings { width: min(460px, 92vw); padding: 0; border: 1px solid var(--border-color, #444); border-radius: 14px;
  background: var(--comfy-menu-bg, #202020); color: var(--fg-color, #ddd); font-family: inherit; font-size: 13px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55); overflow: hidden; }
.arisu-settings[open] { display: flex; flex-direction: column; animation: arisu-settings-pop 160ms ease-out; }
.arisu-settings[open]::backdrop { background: rgba(0, 0, 0, 0.55); backdrop-filter: blur(3px); }
.arisu-settings :where(button, input, select) { font: inherit; color: inherit; border: 1px solid var(--border-color, #444);
  border-radius: 8px; background: var(--comfy-input-bg, #333); transition: background-color 150ms ease, border-color 150ms ease; }
.arisu-settings :where(button) { padding: 6px 12px; cursor: pointer; }
.arisu-settings :where(input, select) { padding: 6px 10px; min-width: 0; }
.arisu-settings button:hover { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-settings :focus-visible { outline: 2px solid var(--p-primary-color, #6ea8fe); outline-offset: 2px; }
.arisu-settings :where(input, select):focus-visible { outline: none; border-color: var(--p-primary-color, #6ea8fe); }
.arisu-settings-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px;
  border-bottom: 1px solid var(--border-color, #444); }
.arisu-settings-title { margin: 0; font-size: 14px; font-weight: 600; }
.arisu-settings-body { display: grid; grid-template-columns: max-content 1fr; align-items: center; gap: 10px 12px; padding: 14px 16px; }
.arisu-settings-label { color: var(--descrip-text, #999); text-align: right; }
.arisu-settings-field { display: flex; gap: 8px; min-width: 0; }
.arisu-settings-field > :where(input, select) { flex: 1; }
.arisu-settings-swatch { flex: 0 0 38px; height: 32px; padding: 2px; cursor: pointer; }
.arisu-settings-bar { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--border-color, #444); }
.arisu-settings-spacer { flex: 1; }
.arisu-settings-apply { border-color: var(--p-primary-color, #6ea8fe); }
@keyframes arisu-settings-pop { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
@media (prefers-reduced-motion: reduce) {
  .arisu-settings, .arisu-settings::backdrop, .arisu-settings * { animation: none !important; transition: none !important; }
}
`;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function hexPair(channel) {
  return Math.round(clamp(channel, 0, 255))
    .toString(16)
    .padStart(2, '0');
}

/** `#rrggbb` for a colour text in any accepted numeric form, or `null` for a name or nonsense. */
function parseColor(text) {
  const value = text.trim();
  const hex = HEX_COLOR.exec(value);
  if (hex) {
    const digits = hex[1].length === 3 ? [...hex[1]].map((digit) => digit + digit).join('') : hex[1].slice(0, 6);
    return `#${digits.toLowerCase()}`;
  }
  const parts = value.split(',').map((part) => part.trim());
  if ((parts.length !== 1 && parts.length !== 3) || !parts.every((part) => part !== '' && Number.isFinite(Number(part)))) return null;
  const scale = parts.some((part) => part.includes('.')) ? 255 : 1;
  const channels = parts.map((part) => Number(part) * scale);
  const [r, g, b] = channels.length === 1 ? [channels[0], channels[0], channels[0]] : channels;
  return `#${hexPair(r)}${hexPair(g)}${hexPair(b)}`;
}

/** The text the picker writes for `#rrggbb`: `r, g, b` in 0-255, the backend's default form. */
function formatColor(hex) {
  return [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16)).join(', ');
}

/** The props `el()` assigns for a numeric bound, only when the field declares one: an undefined attribute would read "undefined". */
function bounds(field) {
  const props = {};
  for (const name of ['min', 'max', 'step']) if (field[name] != null) props[name] = String(field[name]);
  return props;
}

/** The control(s) for `field` seeded with `current`, with `get` reading the value back and `set` writing one in. */
function controlFor(field, current, id) {
  if (field.kind === 'combo') {
    const select = el(
      'select',
      { id },
      field.values.map((value) => el('option', { value, textContent: value })),
    );
    select.value = String(current);
    return { elements: [select], get: () => select.value || current, set: (value) => (select.value = String(value)) };
  }
  if (field.kind === 'number') {
    const input = el('input', { id, type: 'number', value: String(current), ...bounds(field) });
    const read = () => {
      const number = Math.round(Number(input.value));
      if (input.value.trim() === '' || !Number.isFinite(number)) return current;
      return clamp(number, field.min ?? Number.NEGATIVE_INFINITY, field.max ?? Number.POSITIVE_INFINITY);
    };
    return { elements: [input], get: read, set: (value) => (input.value = String(value)) };
  }
  const input = el('input', { id, type: 'text', value: String(current ?? '') });
  const set = (value) => (input.value = String(value ?? ''));
  if (field.kind !== 'color') return { elements: [input], get: () => input.value, set };
  const swatch = el('input', { type: 'color', className: 'arisu-settings-swatch', title: 'pick a colour' });
  const sync = () => {
    const hex = parseColor(input.value);
    if (hex) swatch.value = hex;
  };
  swatch.oninput = () => (input.value = formatColor(swatch.value));
  input.oninput = sync;
  sync();
  return {
    elements: [input, swatch],
    get: () => input.value,
    set: (value) => {
      set(value);
      sync();
    },
  };
}

/**
 * Let the user edit `fields` starting from `values` (by field name, the field's default when missing); resolves to the
 * edited values, or `null` when the dialog is cancelled.
 */
export function editSettings(title, fields, values) {
  let result = null;
  const controls = fields.map((field) => ({
    field,
    ...controlFor(field, values[field.name] ?? field.default, `arisu-settings-${field.name}`),
  }));
  const rows = controls.flatMap(({ field, elements }) => [
    el('label', {
      className: 'arisu-settings-label',
      htmlFor: `arisu-settings-${field.name}`,
      textContent: field.name,
      title: field.tooltip ?? '',
    }),
    el('div', { className: 'arisu-settings-field' }, elements),
  ]);
  const dialog = el(
    'dialog',
    {
      className: 'arisu-settings',
      onclick: (event) => (event.target === dialog ? dialog.close() : undefined),
    },
    [
      el('style', { textContent: STYLE }),
      el('div', { className: 'arisu-settings-head' }, [
        el('h2', { className: 'arisu-settings-title', textContent: title }),
        el('button', { textContent: '✕', title: 'close', onclick: () => dialog.close() }),
      ]),
      el('div', { className: 'arisu-settings-body' }, rows),
      el('div', { className: 'arisu-settings-bar' }, [
        el('button', {
          textContent: 'reset',
          title: 'the declared defaults',
          onclick: () => {
            for (const control of controls) control.set(control.field.default);
          },
        }),
        el('span', { className: 'arisu-settings-spacer' }),
        el('button', { textContent: 'cancel', onclick: () => dialog.close() }),
        el('button', {
          className: 'arisu-settings-apply',
          textContent: 'apply',
          onclick: () => {
            result = Object.fromEntries(controls.map((control) => [control.field.name, control.get()]));
            dialog.close();
          },
        }),
      ]),
    ],
  );
  return new Promise((resolve) => {
    dialog.onclose = () => {
      dialog.remove();
      resolve(result);
    };
    document.body.append(dialog);
    dialog.showModal();
  });
}
