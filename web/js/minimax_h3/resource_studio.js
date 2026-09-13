// Legacy LiteGraph Resource Studio: persisted descriptions, transient editors, native sockets.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { cropImage } from '../common/cropper.js';
import { el } from '../common/dom.js';
import { browseResources, closeBrowser, viewUrl } from '../common/resource_browser.js';
import { installSelectionGuards, preservingSelections, registerSelectionOwner } from '../common/selection_context.js';
import { hideWidget } from '../common/widgets.js';
import { editClip } from './clip_editor.js';

const TYPE = 'ArisuMiniMaxH3ResourceStudio';
const EMPTY = '{"version":1,"keyframes":{"first":null,"last":null},"references":[]}';
const LIMITS = { image: 9, video: 3, audio: 3 };
const nodes = new WeakMap();
let activeEditor;
const STYLE = `
.arisu-studio{box-sizing:border-box;width:100%;height:100%;overflow:hidden;display:flex;flex-direction:column;gap:10px;padding:6px 10px 10px;
 font:11px/1.3 Arial,system-ui,sans-serif;--image:#7fd1c1;--video:#d9a441;--audio:#b89be0;
 --surface:var(--comfy-input-bg,#2a2a2a);--row:var(--comfy-menu-bg,#333);--line:var(--border-color,#444);
 --label:var(--descrip-text,#999);--text:var(--input-text,#ccc);--dim:#777;--strong:var(--fg-color,#fff);
 --hover:color-mix(in srgb,var(--row),var(--strong) 8%);color:var(--text);}
.arisu-studio *{box-sizing:border-box;}
.arisu-studio button{font:inherit;color:inherit;background:none;border:0;border-radius:2px;padding:0;cursor:pointer;}
.arisu-studio :focus-visible{outline:2px solid var(--image);outline-offset:1px;}
.arisu-studio .status{font-size:10px;color:var(--dim);text-align:right;}
.arisu-studio .label{color:var(--label);}
.arisu-studio .heading{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:16px;}
.arisu-studio .icons{display:flex;align-items:center;gap:4px;}
.arisu-studio .icon{width:16px;height:16px;display:inline-flex;align-items:center;justify-content:center;color:var(--label);font-size:13px;line-height:1;}
.arisu-studio .icon svg{width:11px;height:11px;}
.arisu-studio .icon.dot{font-size:10px;color:var(--image);}.arisu-studio .icon.off{color:var(--dim);}
.arisu-studio .icon:hover{color:var(--strong);background:var(--hover);}
.arisu-studio .keyframes{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.arisu-studio .keyframe{display:flex;flex-direction:column;gap:4px;min-width:0;}
.arisu-studio .picture{width:100%;aspect-ratio:1;max-height:180px;display:flex;align-items:center;justify-content:center;overflow:hidden;
 background:var(--surface);border:1px solid var(--line);border-radius:0;color:var(--dim);}
.arisu-studio .picture:hover{border-color:var(--image);color:var(--text);}
.arisu-studio .picture img{width:100%;height:100%;object-fit:contain;}
.arisu-studio .filename{font-size:10px;color:var(--label);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.arisu-studio .filename.none{color:var(--dim);}
.arisu-studio .detail{font-size:9.5px;color:var(--dim);font-variant-numeric:tabular-nums;}
.arisu-studio .muted{opacity:.5;}.arisu-studio .muted .filename,.arisu-studio .muted .name{text-decoration:line-through;}
.arisu-studio .section{display:flex;flex-direction:column;gap:4px;flex:1;min-height:0;}
.arisu-studio .counts{display:flex;gap:8px;font-size:10px;}
.arisu-studio .counts .image{color:var(--image);}.arisu-studio .counts .video{color:var(--video);}.arisu-studio .counts .audio{color:var(--audio);}
.arisu-studio .box{flex:1;min-height:0;display:flex;flex-direction:column;gap:4px;padding:6px;background:var(--surface);border:1px solid var(--line);}
.arisu-studio .box.empty{align-items:center;justify-content:center;gap:8px;padding:14px 10px;text-align:center;color:var(--dim);line-height:1.5;}
.arisu-studio .references{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:4px;scrollbar-width:thin;}
.arisu-studio .reference{--kind:var(--image);display:flex;align-items:center;gap:7px;padding:5px 5px 5px 3px;background:var(--row);border-left:3px solid var(--kind);}
.arisu-studio .reference.video{--kind:var(--video);}.arisu-studio .reference.audio{--kind:var(--audio);}
.arisu-studio .reference.muted{border-left-color:rgba(120,126,132,.6);}
.arisu-studio .reference:hover{background:var(--hover);}
.arisu-studio .handle{width:12px;text-align:center;color:var(--dim);font-size:10px;cursor:grab;opacity:0;transition:opacity .12s;}
.arisu-studio .reference:hover .handle{opacity:1;}.arisu-studio .handle:hover{color:var(--text);}
.arisu-studio .thumb{width:36px;height:24px;flex:none;object-fit:contain;background:color-mix(in srgb,var(--kind) 12%,transparent);border:1px solid color-mix(in srgb,var(--kind) 30%,transparent);}
.arisu-studio .edit{flex:1;min-width:0;text-align:left;}
.arisu-studio .edit span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.arisu-studio .name{color:var(--text);}
.arisu-studio .move{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);}
.arisu-studio .move:focus{position:static;width:auto;height:auto;clip-path:none;}
.arisu-studio .browse{display:flex;align-items:center;justify-content:center;gap:6px;height:28px;padding:0 12px;flex:none;border-radius:4px;
 background:var(--row);border:1px solid var(--line);color:var(--text);font-size:11.5px;}
.arisu-studio .browse::before{content:'+';font-size:13px;line-height:1;margin-top:-1px;}
.arisu-studio .browse:hover{background:var(--hover);border-color:var(--label);color:var(--strong);}
@media(prefers-color-scheme:light){.arisu-studio{--image:#267c6b;--video:#986600;--audio:#7950aa;--dim:#666;}}
`;
const CROP_ICON =
  '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">' +
  '<path d="M4 1.5H1.5V4"/><path d="M8 1.5h2.5V4"/><path d="M4 10.5H1.5V8"/><path d="M8 10.5h2.5V8"/><rect x="3.5" y="3.5" width="5" height="5"/></svg>';
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
function commit(node, data) {
  node.graph?.beforeChange?.();
  widget(node, 'resources_json').value = JSON.stringify(data);
  node.graph?.afterChange?.();
  invalidate(node);
  render(node);
  node.setDirtyCanvas(true, true);
}
function reset(node) {
  invalidate(node);
  widget(node, 'resources_json').value = EMPTY;
  const state = nodes.get(node);
  if (state) {
    state.info.clear();
    state.ratio = undefined;
  }
  render(node);
}
function ratio(node) {
  if (node.arisuEffectiveAspect !== undefined) return node.arisuEffectiveAspect;
  if (node.inputs?.some((input) => input.name === 'aspect_ratio' && input.link != null)) return null;
  return widget(node, 'aspect_ratio')?.value;
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
function applyCard(node, slot, id, item, info) {
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
  nodes.get(node).info.set(item.id, info);
  commit(node, data);
}
async function edit(node, item, slot) {
  const task = begin(node);
  try {
    const info = await probe(item, task.signal);
    if (!task.current()) return;
    if (slot && info.kind !== 'image') throw new Error('Keyframes require an image');
    const draft = { ...item, kind: info.kind };
    if (info.kind === 'image') {
      const image = await imageAt(item, task.signal);
      if (!task.current()) return;
      const current = ratio(node);
      const box = draft.crop;
      const result = await cropImage(
        image,
        { rect: box ? { x: box.left, y: box.top, w: box.width, h: box.height } : null, ratio: '' },
        { aspectRatio: slot ? current : undefined, signal: task.signal },
      );
      if (!task.current() || !result.rect) return;
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
    applyCard(node, slot, item.id, draft, info);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}
async function browse(node, slot = null, replacing = null) {
  const task = begin(node);
  const adapter = {
    widgets: [
      { name: 'root', value: replacing?.root ?? 'input' },
      { name: 'path', value: replacing?.path ?? '' },
    ],
  };
  await browseResources(adapter, {
    mixed: !slot,
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
          applyCard(node, slot, replacing?.id, item, info);
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
  const previous = state.ratio;
  state.ratio = effective;
  if (!effective) {
    render(node);
    return;
  }
  invalidate(node);
  const generation = state.generation;
  const data = read(node);
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
      changed = true;
    }
    if (changed) {
      commit(node, data);
      if (previous) toast('Aspect ratio changed; keyframes were auto-cropped.', 'info');
    } else render(node);
  } catch (error) {
    if (state.generation === generation) toast(error.message, 'error');
  }
}
function cropParam(card) {
  return card.crop ? ['left', 'top', 'width', 'height'].map((key) => card.crop[key]).join(',') : '';
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
  const details = (card) => {
    const info = state.info.get(card.id);
    const size =
      card.kind === 'image'
        ? card.crop
          ? `${card.crop.width} × ${card.crop.height}`
          : info
            ? `${info.width} × ${info.height}`
            : 'Original crop'
        : `${card.clip?.start.toFixed(3)}–${card.clip?.end.toFixed(3)}s`;
    return `${size}${card.muted ? ' · Muted' : ''}`;
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
        onclick: () => (card ? edit(node, card, key) : browse(node, key)),
      });
      const actions = [];
      if (card) {
        picture.append(el('img', { src: viewUrl(card.path, undefined, false, cropParam(card), card.root), alt: `${key} frame` }));
        const crop = button('', () => edit(node, card, key), 'Crop');
        crop.innerHTML = CROP_ICON;
        actions.push(
          crop,
          button('↻', () => browse(node, key, card), 'Replace'),
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
        ...(card ? [el('div', { className: 'detail', textContent: details(card) })] : []),
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
  const references = el(
    'div',
    { className: 'references' },
    data.references.map((card) => {
      const handle = el('span', {
        className: 'handle',
        textContent: '⠿',
        draggable: true,
        ariaHidden: 'true',
        ondragstart: (event) => {
          state.drag = card.id;
          event.dataTransfer?.setData('text/plain', card.id);
        },
      });
      const thumb =
        card.kind === 'image'
          ? el('img', {
              className: 'thumb',
              alt: '',
              loading: 'lazy',
              src: viewUrl(card.path, undefined, false, cropParam(card), card.root),
            })
          : el('span', { className: 'thumb', ariaHidden: 'true' });
      const row = el(
        'div',
        {
          className: `reference ${card.kind}${card.muted ? ' muted' : ''}`,
          ondragover: (event) => event.preventDefault(),
          ondrop: (event) => {
            event.preventDefault();
            if (!state.drag) return;
            const from = data.references.findIndex((item) => item.id === state.drag);
            const to = data.references.findIndex((item) => item.id === card.id);
            if (from >= 0) move(state.drag, to - from);
            state.drag = null;
          },
        },
        [
          handle,
          thumb,
          el('button', { className: 'edit', ariaLabel: `Edit ${card.kind} ${card.path}`, onclick: () => edit(node, card, null) }, [
            el('span', { className: 'name', textContent: card.path.split('/').at(-1) }),
            el('span', { className: 'detail', textContent: details(card) }),
          ]),
          button('↻', () => browse(node, null, card), 'Replace'),
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
      return row;
    }),
  );
  const browseAll = button('Browse resources…', () => browse(node), undefined, 'browse');
  const box = data.references.length
    ? el('div', { className: 'box' }, [references, browseAll])
    : el('div', { className: 'box empty' }, [
        el('div', { textContent: 'no references yet' }),
        el('div', { textContent: 'image · video · audio' }),
        browseAll,
      ]);
  const status = ratio(node)
    ? node.arisuAspectSource
      ? `Aspect ratio from ${node.arisuAspectSource}`
      : ''
    : 'Aspect ratio will resolve during execution';
  state.body.replaceChildren(
    el('style', { textContent: STYLE }),
    el('output', { className: 'status', ariaLive: 'polite', hidden: !status, textContent: status }),
    keyframes,
    el('div', { className: 'section' }, [
      el('div', { className: 'heading' }, [
        el('span', { className: 'label', textContent: 'Media references' }),
        ...(data.references.length
          ? [
              el(
                'span',
                { className: 'counts' },
                Object.keys(LIMITS).map((kind) =>
                  el('span', {
                    className: kind,
                    textContent: `${kind} ${data.references.filter((card) => card.kind === kind && !card.muted).length}`,
                  }),
                ),
              ),
            ]
          : []),
      ]),
      box,
    ]),
  );
}
registerSelectionOwner(TYPE, {
  fields: [
    ['resources_json', 2, EMPTY],
    ['advertise', 1, false],
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
      const state = { body, info: new Map(), generation: 0 };
      nodes.set(this, state);
      for (const event of ['pointerdown', 'wheel', 'keydown']) body.addEventListener(event, (event) => event.stopPropagation());
      const control = widget(this, 'resources_json');
      if (control) {
        control.options ??= {};
        control.options.socketless = true;
        hideWidget(this, control);
      }
      const dom = this.addDOMWidget('studio', 'arisu-studio', body, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 430,
        getMaxHeight: () => 620,
      });
      dom.serialize = false;
      this.setSize([400, 600]);
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
      size[0] = Math.max(360, size[0]);
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
      let changed = false;
      for (const key of ['first', 'last']) {
        const actual = feedback.keyframes[key],
          card = data.keyframes[key];
        if (!card || !actual || actual.id !== card.id) continue;
        card.crop = actual.crop ? Object.fromEntries(['left', 'top', 'width', 'height'].map((name, i) => [name, actual.crop[i]])) : null;
        card.crop_basis_ratio = actual.crop_basis_ratio;
        changed = true;
      }
      nodes.get(this).ratio = undefined;
      if (changed) commit(this, data);
      void refreshRatio(this, feedback.aspect_ratio);
    });
  },
});
