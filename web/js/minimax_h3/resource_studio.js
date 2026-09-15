// Legacy LiteGraph Resource Studio: persisted descriptions, transient editors, native sockets.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { cropImage, savedCropRatio } from '../common/cropper.js';
import { el } from '../common/dom.js';
import { AUDIO_ICON, browseResources, closeBrowser, posterUrl, VIDEO_ICON, viewUrl } from '../common/resource_browser.js';
import { installSelectionGuards, preservingSelections, registerSelectionOwner } from '../common/selection_context.js';
import { hideWidget } from '../common/widgets.js';
import { editClip } from './clip_editor.js';

const TYPE = 'ArisuMiniMaxH3ResourceStudio';
const EMPTY = '{"version":1,"keyframes":{"first":null,"last":null},"references":[]}';
const LIMITS = { image: 9, video: 3, audio: 3 };
// Bound of a video row's still: a 58 × 40 CSS pixel thumb at a 2× device pixel ratio.
const POSTER_MAX = 116;
const nodes = new WeakMap();
let activeEditor;
const STYLE = `
.arisu-studio{box-sizing:border-box;width:100%;height:100%;overflow:hidden;display:flex;flex-direction:column;gap:10px;padding:8px 10px 12px;
 font:11px/1.3 Arial,system-ui,sans-serif;--image:#64b5f6;--video:#d9a441;--audio:#b89be0;
 --surface:var(--comfy-input-bg,#2a2a2a);--row:var(--comfy-menu-bg,#333);--line:var(--border-color,#444);
 --label:var(--descrip-text,#999);--text:var(--input-text,#ccc);--dim:var(--descrip-text,#999);--strong:var(--fg-color,#fff);
 --hover:color-mix(in srgb,var(--row),var(--strong) 8%);color:var(--text);}
.arisu-studio *{box-sizing:border-box;}
.arisu-studio button{font:inherit;color:inherit;background:none;border:0;border-radius:2px;padding:0;cursor:pointer;}
.arisu-studio :focus-visible{outline:2px solid var(--image);outline-offset:-2px;}
.arisu-studio .status{font-size:10px;color:var(--dim);text-align:right;}
.arisu-studio .label{color:var(--label);line-height:20px;}
.arisu-studio .heading{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:24px;}
.arisu-studio .icons{display:flex;align-items:center;gap:4px;}
.arisu-studio .icon{width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;color:var(--label);font-size:15px;line-height:1;}
.arisu-studio .icon svg{width:13px;height:13px;}
.arisu-studio .icon.dot{font-size:12px;color:var(--kind,var(--image));}.arisu-studio .icon.off{color:var(--dim);}
.arisu-studio .icon:hover{color:var(--strong);background:var(--hover);}
.arisu-studio .layout{flex:1;min-height:0;display:grid;grid-template-columns:170px minmax(0,1fr);grid-template-rows:minmax(0,1fr);gap:10px;}
.arisu-studio .keyframes{display:flex;flex-direction:column;justify-content:space-between;gap:8px;}
.arisu-studio .keyframe{display:flex;flex-direction:column;gap:4px;min-width:0;}
.arisu-studio .picture{width:100%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;overflow:hidden;
 background:var(--surface);border:1px solid var(--line);border-radius:3px;color:var(--dim);}
.arisu-studio .picture:hover{border-color:var(--image);color:var(--text);}
.arisu-studio .picture img{width:100%;height:100%;object-fit:contain;}
.arisu-studio .filename{height:14px;line-height:14px;font-size:10px;color:var(--label);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.arisu-studio .filename.none{color:var(--dim);}
.arisu-studio .detail{font-size:11px;line-height:14px;color:var(--dim);font-variant-numeric:tabular-nums;}
.arisu-studio .muted{opacity:.5;}.arisu-studio .muted .filename,.arisu-studio .muted .name{text-decoration:line-through;}
.arisu-studio .section{display:flex;flex-direction:column;gap:4px;min-width:0;min-height:0;}
.arisu-studio .counts{display:flex;gap:8px;margin-left:auto;font-size:10px;line-height:20px;font-variant-numeric:tabular-nums;}
.arisu-studio .counts .image{color:var(--image);}.arisu-studio .counts .video{color:var(--video);}.arisu-studio .counts .audio{color:var(--audio);}
.arisu-studio .box{flex:1;min-height:0;display:flex;flex-direction:column;gap:5px;padding:6px;background:var(--surface);border:1px solid var(--line);}
.arisu-studio .box.empty{min-height:120px;align-items:center;justify-content:center;padding:14px 10px;text-align:center;color:var(--dim);line-height:1.5;}
.arisu-studio .references{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:5px;scrollbar-width:thin;}
.arisu-studio .reference{--kind:var(--image);display:flex;align-items:center;gap:7px;height:52px;flex:none;padding:0 5px 0 3px;background:var(--row);border-left:3px solid var(--kind);}
.arisu-studio .reference.video{--kind:var(--video);}.arisu-studio .reference.audio{--kind:var(--audio);}
.arisu-studio .reference.muted{border-left-color:rgba(120,126,132,.6);}
.arisu-studio .reference:focus-within,.arisu-studio .reference:hover{background:var(--hover);}
.arisu-studio .reference[data-dragging]{opacity:.4;}
.arisu-studio .reference[data-drop=before]{box-shadow:0 -4px 0 -1px var(--strong);}
.arisu-studio .reference[data-drop=after]{box-shadow:0 4px 0 -1px var(--strong);}
.arisu-studio .handle{width:14px;text-align:center;color:var(--dim);font-size:12px;cursor:grab;opacity:0;transition:opacity .12s;}
.arisu-studio .reference:focus-within .handle,.arisu-studio .reference:hover .handle{opacity:1;}.arisu-studio .handle:hover{color:var(--text);}
.arisu-studio .thumb{width:58px;height:40px;flex:none;display:flex;align-items:center;justify-content:center;object-fit:contain;color:var(--kind);
 background:color-mix(in srgb,var(--kind) 12%,transparent);border:1px solid color-mix(in srgb,var(--kind) 30%,transparent);}
.arisu-studio .thumb svg{width:16px;height:16px;}
.arisu-studio .reference.muted .thumb{background:var(--surface);}
.arisu-studio .edit{flex:1;min-width:0;text-align:left;}
.arisu-studio .edit > span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.arisu-studio .name{color:var(--text);font-size:12px;line-height:16px;}.arisu-studio .detail .lead{color:var(--text);}
.arisu-studio .move{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);}
.arisu-studio .move:focus{position:static;width:auto;height:auto;clip-path:none;}
.arisu-studio .browse{display:flex;align-items:center;justify-content:center;gap:5px;height:24px;padding:0 9px;flex:none;border-radius:3px;
 background:var(--hover);border:1px solid color-mix(in srgb,var(--line),var(--strong) 10%);color:var(--text);font-size:11px;}
.arisu-studio .browse::before{content:'+';font-size:12px;line-height:1;margin-top:-1px;}
.arisu-studio .browse:hover{background:color-mix(in srgb,var(--row),var(--strong) 12%);border-color:var(--label);color:var(--strong);}
`;
const CROP_ICON =
  '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">' +
  '<path d="M4 1.5H1.5V4"/><path d="M8 1.5h2.5V4"/><path d="M4 10.5H1.5V8"/><path d="M8 10.5h2.5V8"/><rect x="3.5" y="3.5" width="5" height="5"/></svg>';
// Row metadata formats; every time shown on the node keeps at most one decimal.
function clock(seconds) {
  const tenths = Math.round(seconds * 10);
  const total = Math.floor(tenths / 10);
  const fraction = tenths % 10;
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
  const rest = `${minutes}:${String(total % 60).padStart(2, '0')}${fraction ? `.${fraction}` : ''}`;
  return total >= 3600 ? `${Math.floor(total / 3600)}:${rest}` : rest;
}
function bytes(count) {
  if (count < 1024) return `${count} B`;
  if (count < 1024 ** 2) return `${Math.round(count / 1024)} KB`;
  const [unit, scale] = count < 1024 ** 3 ? ['MB', 1024 ** 2] : ['GB', 1024 ** 3];
  return `${(count / scale).toFixed(1)} ${unit}`;
}
function kilohertz(rate) {
  const value = rate / 1000;
  return `${Number.isInteger(value) ? value : value.toFixed(1)} kHz`;
}
function resourceId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // randomUUID requires a secure context; getRandomValues also works over HTTP.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function widget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}
// Wheel turns and middle-button drags over the panel reach the canvas, as they do over ComfyUI's multiline text
// widgets; left clicks and keys stay on the panel so a row press cannot drag the node and Delete cannot remove it.
function forwardToCanvas(body) {
  body.addEventListener('keydown', (event) => event.stopPropagation());
  body.addEventListener('pointerdown', (event) => {
    if (event.button === 1 || event.buttons === 4) app.canvas?.processMouseDown(event);
    event.stopPropagation();
  });
  body.addEventListener('pointermove', (event) => {
    if ((event.buttons & 4) === 4) app.canvas?.processMouseMove(event);
  });
  body.addEventListener('pointerup', (event) => {
    if (event.button === 1) app.canvas?.processMouseUp(event);
  });
  body.addEventListener('wheel', (event) => {
    event.preventDefault();
    app.canvas?.processMouseWheel(event);
  });
}
// An overflowing list keeps a plain vertical wheel for scrolling; Ctrl and horizontal turns still reach the canvas.
function keepScrollWheel(event) {
  const list = event.currentTarget;
  if (!event.ctrlKey && Math.abs(event.deltaX) <= Math.abs(event.deltaY) && list.scrollHeight > list.clientHeight) event.stopPropagation();
}
function toast(detail, severity = 'warn') {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Resource Studio', detail, life: 8000 });
}
function read(node) {
  const data = JSON.parse(widget(node, 'resources_json')?.value || EMPTY);
  if (data.version !== 1 || !data.keyframes || !Array.isArray(data.references)) throw new Error('Unsupported resource state');
  return data;
}
function invalidate(node) {
  const state = nodes.get(node);
  if (!state) return;
  state.generation++;
  state.controller?.abort();
  closeBrowser(node);
}
function cropKey(slot, id) {
  return slot ? `keyframe:${slot}` : `reference:${id}`;
}
function cropMode(item, ratio) {
  return { root: item.root, path: item.path, ratio: ratio?.split(' ')[0] || 'free' };
}
function commit(node, data, modes = node.properties?.arisu_crop_modes ?? {}) {
  // Keep modes attached to selections through reordering, and discard removed or replaced sources.
  const sources = new Map([
    ...Object.entries(data.keyframes).map(([slot, item]) => [cropKey(slot), item]),
    ...data.references.map((item) => [cropKey(null, item.id), item]),
  ]);
  node.graph?.beforeChange?.();
  node.properties ??= {};
  node.properties.arisu_crop_modes = Object.fromEntries(
    Object.entries(modes).filter(([key, entry]) => {
      const item = sources.get(key);
      return item?.kind === 'image' && entry?.root === item.root && entry?.path === item.path;
    }),
  );
  widget(node, 'resources_json').value = JSON.stringify(data);
  node.graph?.afterChange?.();
  invalidate(node);
  render(node);
  node.setDirtyCanvas(true, true);
}
function reset(node) {
  invalidate(node);
  widget(node, 'resources_json').value = EMPTY;
  if (node.properties) delete node.properties.arisu_crop_modes;
  const state = nodes.get(node);
  if (state) {
    state.info.clear();
    state.posters.clear();
    state.pending.clear();
    state.ratio = undefined;
  }
  render(node);
}
// A wired ratio reads the origin's widget of the output's name unless that widget is itself linked, in which case execution
// resolves it (null); an unwired input yields undefined.
function upstreamRatio(node) {
  const input = node.inputs?.find((entry) => (entry.widget?.name ?? entry.name) === 'aspect_ratio' && entry.link != null);
  if (!input) return undefined;
  const links = node.graph?.links;
  const link = links?.get?.(input.link) ?? links?.[input.link];
  const origin = link ? (node.graph?.nodes ?? node.graph?._nodes ?? []).find((entry) => String(entry.id) === String(link.origin_id)) : null;
  const name = origin?.outputs?.[link.origin_slot]?.name;
  const control = name ? widget(origin, name) : null;
  const linked = origin?.inputs?.some((entry) => (entry.widget?.name ?? entry.name) === name && entry.link != null);
  const value = control && !linked ? control.value : null;
  return typeof value === 'string' && /^\d+:\d+\b/.test(value) ? value : null;
}
function ratio(node) {
  if (node.arisuEffectiveAspect !== undefined) return node.arisuEffectiveAspect;
  const upstream = upstreamRatio(node);
  return upstream === undefined ? widget(node, 'aspect_ratio')?.value : upstream;
}
function cropFor(info, label) {
  const [w, h] = label.split(' ')[0].split(':').map(Number);
  const width = Math.max(1, Math.min(info.width, Math.floor((info.height * w) / h)));
  const height = Math.max(1, Math.min(info.height, Math.floor((info.width * h) / w)));
  return { left: Math.floor((info.width - width) / 2), top: Math.floor((info.height - height) / 2), width, height };
}
async function probe(item, signal) {
  const response = await api.fetchApi(`/arisu/resources/metadata?${new URLSearchParams({ root: item.root, path: item.path })}`, { signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Cannot inspect resource');
  return data;
}
async function imageAt(item, signal) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('Cannot decode image'));
    signal.addEventListener(
      'abort',
      () => {
        image.src = '';
        reject(new Error('Editor closed'));
      },
      { once: true },
    );
    image.src = viewUrl(item.path, undefined, true, '', item.root);
  });
}
function begin(node) {
  activeEditor?.abort();
  invalidate(node);
  const state = nodes.get(node);
  const controller = new AbortController();
  state.controller = controller;
  activeEditor = controller;
  const generation = state.generation;
  return { signal: controller.signal, current: () => !controller.signal.aborted && nodes.get(node)?.generation === generation };
}
function applyCard(node, slot, id, item, info, appliedRatio) {
  const data = read(node);
  if (slot) {
    data.keyframes[slot] = item;
  } else {
    const index = data.references.findIndex((card) => card.id === id);
    const count = data.references.filter((card) => card.id !== id && !card.muted && card.kind === item.kind).length;
    if (!item.muted && count >= LIMITS[item.kind]) {
      item.muted = true;
      toast('The active reference limit is reached; this card was added muted.');
    }
    if (index >= 0) data.references[index] = item;
    else {
      if (data.references.length >= 256) {
        toast('At most 256 reference cards can be stored.');
        return;
      }
      data.references.push(item);
    }
  }
  const state = nodes.get(node);
  state.info.set(item.id, info);
  for (const key of [...state.posters.keys()]) if (key.startsWith(`${item.id}|`)) state.posters.delete(key);
  const modes = { ...node.properties?.arisu_crop_modes };
  if (appliedRatio !== undefined) modes[cropKey(slot, item.id)] = cropMode(item, appliedRatio);
  commit(node, data, modes);
}
async function edit(node, item, slot) {
  const task = begin(node);
  try {
    const info = await probe(item, task.signal);
    if (!task.current()) return;
    if (slot && info.kind !== 'image') throw new Error('Keyframes require an image');
    const draft = { ...item, kind: info.kind };
    let appliedRatio;
    if (info.kind === 'image') {
      const image = await imageAt(item, task.signal);
      if (!task.current()) return;
      const current = ratio(node);
      const box = draft.crop;
      const result = await cropImage(
        image,
        {
          rect: box ? { x: box.left, y: box.top, w: box.width, h: box.height } : null,
          ratio: savedCropRatio(node.properties?.arisu_crop_modes?.[cropKey(slot, item.id)], item),
        },
        { aspectRatio: slot ? current : undefined, signal: task.signal },
      );
      if (!task.current() || !result.rect) return;
      appliedRatio = result.ratio;
      const { x, y, w, h } = result.rect;
      draft.crop = x === 0 && y === 0 && w === info.width && h === info.height ? null : { left: x, top: y, width: w, height: h };
      if (slot) draft.crop_basis_ratio = current ?? draft.crop_basis_ratio ?? null;
    } else {
      const result = await editClip(draft, info, { signal: task.signal });
      if (!task.current() || !result) return;
      Object.assign(draft, result);
    }
    const latest = await probe(item, task.signal);
    if (!task.current()) return;
    if (latest.revision !== info.revision) throw new Error('Source changed while editing; reselect it.');
    applyCard(node, slot, item.id, draft, info, appliedRatio);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}
async function browse(node, slot = null, replacing = null) {
  const task = begin(node);
  // A keyframe dialog marks the card it replaces; the reference dialog marks every card in the list.
  const marked = slot ? (replacing ? [replacing] : []) : read(node).references;
  const location = replacing ?? (!slot ? marked.at(-1) : null);
  const adapter = {
    widgets: [
      { name: 'root', value: location?.root ?? 'input' },
      { name: 'path', value: location?.path ?? '' },
    ],
  };
  await browseResources(adapter, {
    mixed: !slot,
    selected: (root, path) => marked.some((card) => card.root === root && card.path === path),
    signal: task.signal,
    isCurrent: task.current,
    onPick: async (path, root) => {
      try {
        const item = { id: replacing?.id ?? resourceId(), kind: 'image', root, path, muted: replacing?.muted ?? false };
        const info = await probe(item, task.signal);
        if (!task.current()) return;
        item.kind = info.kind;
        if (info.kind === 'image') {
          item.crop = slot && ratio(node) ? cropFor(info, ratio(node)) : null;
          if (slot) item.crop_basis_ratio = ratio(node);
          applyCard(node, slot, replacing?.id, item, info, slot ? (ratio(node) ?? '') : '');
        } else {
          if (info.kind === 'video') item.include_audio = info.has_audio;
          await edit(node, item, null);
        }
      } catch (error) {
        if (task.current()) toast(error.message, 'error');
      }
    },
  });
}
async function refreshRatio(node, resolvedRatio) {
  const state = nodes.get(node);
  if (!state) return;
  const effective = resolvedRatio ?? ratio(node);
  if (state.ratio === effective) {
    render(node);
    return;
  }
  state.ratio = effective;
  if (!effective) {
    render(node);
    return;
  }
  invalidate(node);
  const generation = state.generation;
  const data = read(node);
  const modes = { ...node.properties?.arisu_crop_modes };
  let changed = false;
  try {
    for (const key of ['first', 'last']) {
      const card = data.keyframes[key];
      if (!card || card.crop_basis_ratio === effective) continue;
      const info = state.info.get(card.id) ?? (await probe(card));
      if (state.generation !== generation) return;
      state.info.set(card.id, info);
      card.crop = cropFor(info, effective);
      card.crop_basis_ratio = effective;
      modes[cropKey(key)] = cropMode(card, effective);
      changed = true;
    }
    if (changed) commit(node, data, modes);
    else render(node);
  } catch (error) {
    if (state.generation === generation) toast(error.message, 'error');
  }
}
function cropParam(card) {
  return card.crop ? ['left', 'top', 'width', 'height'].map((key) => card.crop[key]).join(',') : '';
}
// Metadata lives only in memory; rows probe what a reload or workflow open dropped, once per card and source.
function describe(node, data) {
  const state = nodes.get(node);
  const key = (card) => `${card.id}|${card.root}|${card.path}`;
  const missing = [data.keyframes.first, data.keyframes.last, ...data.references].filter(
    (card) => card && !state.info.has(card.id) && !state.pending.has(key(card)),
  );
  if (!missing.length) return;
  for (const card of missing) state.pending.add(key(card));
  void (async () => {
    for (const card of missing) {
      const info = await probe(card).catch(() => null);
      if (nodes.get(node) !== state) return;
      if (!state.info.has(card.id)) state.info.set(card.id, info);
      state.pending.delete(key(card));
    }
    render(node);
  })();
}
function render(node) {
  const state = nodes.get(node);
  if (!state) return;
  let data;
  try {
    data = read(node);
  } catch (error) {
    state.body.replaceChildren(el('span', { textContent: error.message }));
    return;
  }
  const button = (text, action, title = text, className = 'icon') =>
    el('button', {
      className,
      textContent: text,
      title,
      ariaLabel: title,
      onclick: (event) => {
        event?.stopPropagation?.();
        return action();
      },
    });
  const muteButton = (card, action) =>
    button(card.muted ? '⦸' : '●', action, card.muted ? 'Unmute' : 'Mute', `icon dot${card.muted ? ' off' : ''}`);
  const mutate = (action) => {
    const next = read(node);
    action(next);
    commit(node, next);
  };
  const toggle = (card, slot) =>
    mutate((next) => {
      const target = slot ? next.keyframes[slot] : next.references.find((item) => item.id === card.id);
      if (
        target.muted &&
        !slot &&
        next.references.filter((item) => !item.muted && item.kind === target.kind).length >= LIMITS[target.kind]
      ) {
        toast('The active reference limit is reached.');
        return;
      }
      target.muted = !target.muted;
    });
  // The design's second line: dimensions, or the clip length beside the source length, then video resolution or audio rate, then file size.
  const details = (card) => {
    const info = state.info.get(card.id);
    const size = info ? bytes(info.size) : null;
    if (card.kind === 'image') {
      const box = card.crop ?? info;
      return { lead: box ? `${box.width}×${box.height}` : info === null ? '—' : '…', rest: size ? ` · ${size}` : '' };
    }
    const lead = card.clip ? clock(card.clip.end - card.clip.start) : '—';
    if (!info) return { lead, rest: info === null ? ' · —' : '' };
    return {
      lead,
      rest: ` / ${clock(info.duration)} · ${card.kind === 'video' ? `${info.width}×${info.height}` : kilohertz(info.rate)} · ${size}`,
    };
  };
  const keyframes = el(
    'div',
    { className: 'keyframes' },
    ['first', 'last'].map((key) => {
      const card = data.keyframes[key];
      const picture = el('button', {
        className: 'picture',
        textContent: card ? '' : 'Browse…',
        ariaLabel: `${key} frame`,
        onclick: () => browse(node, key, card),
      });
      const actions = [];
      if (card) {
        // The crop size and muted state moved off the panel into the canvas tooltip.
        const { lead, rest } = details(card);
        picture.title = `${lead}${rest}${card.muted ? ' · Muted' : ''}`;
        picture.append(el('img', { src: viewUrl(card.path, undefined, false, cropParam(card), card.root), alt: `${key} frame` }));
        const crop = button('', () => edit(node, card, key), 'Crop');
        crop.innerHTML = CROP_ICON;
        actions.push(
          crop,
          muteButton(card, () => toggle(card, key)),
          button(
            '×',
            () =>
              mutate((next) => {
                next.keyframes[key] = null;
              }),
            'Clear',
          ),
        );
      }
      return el('div', { className: `keyframe${card?.muted ? ' muted' : ''}` }, [
        el('div', { className: 'heading' }, [
          el('span', { className: 'label', textContent: `${key === 'first' ? 'First' : 'Last'} frame` }),
          ...(card ? [el('div', { className: 'icons' }, actions)] : []),
        ]),
        picture,
        el('div', { className: `filename${card ? '' : ' none'}`, textContent: card?.path.split('/').at(-1) ?? '— no file —' }),
      ]);
    }),
  );
  const move = (id, delta) => {
    mutate((next) => {
      const index = next.references.findIndex((card) => card.id === id);
      const target = Math.max(0, Math.min(next.references.length - 1, index + delta));
      next.references.splice(target, 0, ...next.references.splice(index, 1));
    });
    [...(state.body.querySelectorAll?.('.reference') ?? [])]
      .find((row) => row.dataset.cardId === id)
      ?.querySelector('.edit')
      ?.focus();
  };
  // Drag feedback lives on the rendered rows as data attributes; a drop or a cancelled drag clears both markers.
  const clearDrop = () => {
    if (state.dropRow) delete state.dropRow.dataset.drop;
    state.dropRow = null;
  };
  const endDrag = () => {
    clearDrop();
    if (state.dragRow) delete state.dragRow.dataset.dragging;
    state.dragRow = null;
    state.drag = null;
  };
  const references = el(
    'div',
    { className: 'references', onwheel: keepScrollWheel },
    data.references.map((card) => {
      const handle = el('span', { className: 'handle', textContent: '⠿', draggable: true, ariaHidden: 'true' });
      const icon = (markup) => {
        const span = el('span', { className: 'thumb', ariaHidden: 'true' });
        span.innerHTML = markup;
        return span;
      };
      // A video still is decoded once per card and clip start; re-renders move the loaded element.
      const poster = () => {
        const key = `${card.id}|${card.root}|${card.path}|${card.clip?.start}`;
        let image = state.posters.get(key);
        if (!image) {
          image = el('img', {
            className: 'thumb',
            alt: '',
            loading: 'lazy',
            src: posterUrl(card.root, card.path, card.clip?.start ?? 0, POSTER_MAX),
          });
          image.onerror = () => {
            state.posters.delete(key);
            image.replaceWith(icon(VIDEO_ICON));
          };
          state.posters.set(key, image);
        }
        return image;
      };
      const thumb =
        card.kind === 'image'
          ? el('img', {
              className: 'thumb',
              alt: '',
              loading: 'lazy',
              src: viewUrl(card.path, undefined, false, cropParam(card), card.root),
            })
          : card.kind === 'video'
            ? poster()
            : icon(AUDIO_ICON);
      const { lead, rest } = details(card);
      const row = el(
        'div',
        {
          className: `reference ${card.kind}${card.muted ? ' muted' : ''}`,
          // The pointer half of the hovered row decides whether the dragged card lands above or below it.
          ondragover: (event) => {
            event.preventDefault();
            if (!state.drag || state.drag === card.id) {
              clearDrop();
              return;
            }
            const rect = row.getBoundingClientRect();
            if (state.dropRow !== row) clearDrop();
            row.dataset.drop = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after';
            state.dropRow = row;
          },
          ondrop: (event) => {
            event.preventDefault();
            const side = row.dataset.drop ?? 'after';
            const id = state.drag;
            const from = data.references.findIndex((item) => item.id === id);
            const to = data.references.findIndex((item) => item.id === card.id);
            endDrag();
            if (from < 0 || from === to) return;
            const insert = (side === 'before' ? to : to + 1) - (from < to ? 1 : 0);
            if (insert !== from) move(id, insert - from);
          },
        },
        [
          handle,
          thumb,
          el('button', { className: 'edit', ariaLabel: `Edit ${card.kind} ${card.path}`, onclick: () => edit(node, card, null) }, [
            el('span', { className: 'name', textContent: card.path.split('/').at(-1) }),
            el('span', { className: 'detail' }, [el('span', { className: 'lead', textContent: lead }), el('span', { textContent: rest })]),
          ]),
          muteButton(card, () => toggle(card, null)),
          button(
            '×',
            () =>
              mutate((next) => {
                next.references = next.references.filter((item) => item.id !== card.id);
              }),
            'Remove',
          ),
          ...[-1, 1].map((delta) => button(delta < 0 ? 'Move up' : 'Move down', () => move(card.id, delta), undefined, 'move')),
        ],
      );
      row.dataset.cardId = card.id;
      handle.ondragstart = (event) => {
        state.drag = card.id;
        state.dragRow = row;
        row.dataset.dragging = '';
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', card.id);
        }
      };
      handle.ondragend = endDrag;
      return row;
    }),
  );
  const browseAll = button('Browse', () => browse(node), 'Browse references…', 'browse');
  const box = data.references.length
    ? el('div', { className: 'box' }, [references])
    : el('div', { className: 'box empty' }, [
        el('div', { textContent: 'no references yet' }),
        el('div', { textContent: 'image · video · audio' }),
      ]);
  // Only kinds with active references are counted; nothing active shows no counters.
  const counts = Object.keys(LIMITS)
    .map((kind) => [kind, data.references.filter((card) => card.kind === kind && !card.muted).length])
    .filter(([, count]) => count > 0);
  const status = ratio(node) ? '' : 'Aspect ratio will resolve during execution';
  const section = el('div', { className: 'section' }, [
    el('div', { className: 'heading' }, [
      el('span', { className: 'label', textContent: 'Media references' }),
      ...(counts.length
        ? [
            el(
              'span',
              { className: 'counts' },
              counts.map(([kind, count]) => el('span', { className: kind, textContent: `${kind} ${count}` })),
            ),
          ]
        : []),
      browseAll,
    ]),
    box,
  ]);
  state.body.replaceChildren(
    el('style', { textContent: STYLE }),
    el('output', { className: 'status', ariaLive: 'polite', hidden: !status, textContent: status }),
    el('div', { className: 'layout' }, [keyframes, section]),
  );
  describe(node, data);
}
registerSelectionOwner(TYPE, {
  properties: ['arisu_crop_modes'],
  fields: [
    ['resources_json', 2, EMPTY],
    ['advertise_resources', 1, false],
  ],
  invalidate,
});
app.registerExtension({
  name: 'Arisu.MiniMaxH3.ResourceStudio',
  init: installSelectionGuards,
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== TYPE) return;
    const chain = (name, fn) => {
      const original = nodeType.prototype[name];
      nodeType.prototype[name] = function (...args) {
        const result = original?.apply(this, args);
        fn.apply(this, args);
        return result;
      };
    };
    chain('onNodeCreated', function () {
      const body = el('div', { className: 'arisu-studio' });
      const state = { body, info: new Map(), posters: new Map(), pending: new Set(), generation: 0 };
      nodes.set(this, state);
      forwardToCanvas(body);
      const control = widget(this, 'resources_json');
      if (control) {
        control.options ??= {};
        control.options.socketless = true;
        hideWidget(this, control);
      }
      const dom = this.addDOMWidget('studio', 'arisu-studio', body, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 460,
      });
      dom.serialize = false;
      this.setSize([490, 550]);
      this.arisuRefreshAspect = () => refreshRatio(this);
      const aspect = widget(this, 'aspect_ratio');
      if (aspect) {
        const callback = aspect.callback;
        aspect.callback = (...args) => {
          callback?.apply(aspect, args);
          void refreshRatio(this);
        };
      }
      render(this);
    });
    chain('onResize', (size) => {
      size[0] = Math.max(440, size[0]);
    });
    chain('onConfigure', function () {
      invalidate(this);
      const linked = this.inputs?.some((input) => input.name === 'resources_json' && input.link != null);
      for (let i = (this.inputs?.length ?? 0) - 1; i >= 0; i--) if (this.inputs[i].name === 'resources_json') this.removeInput(i);
      if (linked) toast('Resource state wires were removed; reselect resources.');
      if (linked || !preservingSelections() || !app.configuringGraph) reset(this);
      else {
        render(this);
        void refreshRatio(this);
      }
    });
    chain('onConnectionsChange', function () {
      void refreshRatio(this);
    });
    chain('onRemoved', function () {
      invalidate(this);
      nodes.delete(this);
    });
    chain('onExecuted', function (message) {
      const feedback = message.arisu_resources?.[0];
      if (!feedback || feedback.state !== widget(this, 'resources_json')?.value) return;
      const data = read(this);
      const modes = { ...this.properties?.arisu_crop_modes };
      let changed = false;
      for (const key of ['first', 'last']) {
        const actual = feedback.keyframes[key],
          card = data.keyframes[key];
        if (!card || !actual || actual.id !== card.id) continue;
        card.crop = actual.crop ? Object.fromEntries(['left', 'top', 'width', 'height'].map((name, i) => [name, actual.crop[i]])) : null;
        if (card.crop_basis_ratio !== actual.crop_basis_ratio) modes[cropKey(key)] = cropMode(card, actual.crop_basis_ratio);
        card.crop_basis_ratio = actual.crop_basis_ratio;
        changed = true;
      }
      nodes.get(this).ratio = undefined;
      if (changed) commit(this, data, modes);
      void refreshRatio(this, feedback.aspect_ratio);
    });
  },
});
