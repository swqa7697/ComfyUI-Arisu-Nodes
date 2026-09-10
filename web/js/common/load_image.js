// Browse and crop raster images beneath server-configured roots. Paths and bookmarks are relative.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { cropImage } from './cropper.js';
import { closeOnBackdropClick, el } from './dom.js';
import { addButton, hideWidget, setWidget } from './widgets.js';

const NODE_TYPE = 'ArisuLoadImage';
const PATH_WIDGET = 'path';
const CROP_WIDGET = 'crop';
const BROWSE_ROUTE = '/arisu/browse';
const VIEW_ROUTE = '/arisu/view';
const THUMBNAIL_MAX = 256;
/** The hidden ComfyUI setting holding the browser's saved directories, an array of {root, path} locations. */
const SAVED_PATHS_SETTING = 'Arisu.LoadImage.SavedLocations';
/** The fallback bound if a full-resolution raster response cannot be loaded. */
const PREVIEW_MAX = 1024;
/** The context-menu entry the frontend adds to every previewing node; see beforeRegisterNodeDef for why it goes. */
const MASK_EDITOR_ENTRY = /mask ?editor/i;
const ICONS = { root: '\u{1F4BE}', folder: '\u{1F4C1}', saved: '\u{1F4CC}' };

const STYLE = `
.arisu-browser { width: min(1100px, 92vw); height: min(760px, 88vh); padding: 0; border: 1px solid var(--border-color, #444);
  border-radius: 14px; background: var(--comfy-menu-bg, #202020); color: var(--fg-color, #ddd); font-family: inherit;
  font-size: 13px; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55); overflow: hidden; }
.arisu-browser[open] { display: flex; flex-direction: column; animation: arisu-pop 220ms cubic-bezier(0.2, 0.8, 0.2, 1); }
.arisu-browser[open]::backdrop { background: rgba(0, 0, 0, 0.55); backdrop-filter: blur(3px); animation: arisu-fade 220ms ease-out; }
.arisu-browser :where(button, input) { font: inherit; color: inherit; border: 1px solid var(--border-color, #444); border-radius: 8px;
  background: var(--comfy-input-bg, #333); transition: background-color 150ms ease, border-color 150ms ease, transform 150ms ease,
  box-shadow 150ms ease; }
.arisu-browser :where(button) { padding: 6px 12px; cursor: pointer; }
.arisu-browser :where(input) { padding: 6px 10px; }
.arisu-browser button:active { transform: scale(0.97); }
.arisu-browser-tree button:active { transform: none; }
.arisu-browser button:disabled { opacity: 0.4; cursor: default; pointer-events: none; }
.arisu-browser :focus-visible { outline: 2px solid var(--p-primary-color, #6ea8fe); outline-offset: 2px; }
.arisu-browser input:focus-visible { outline: none; border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-bar { display: flex; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #444); }
.arisu-browser-bar button:hover { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-path { flex: 1; min-width: 0; }
.arisu-browser-body { display: flex; flex: 1; min-height: 0; transition: opacity 150ms ease; }
.arisu-browser-body[aria-busy="true"] { opacity: 0.45; pointer-events: none; transition-delay: 200ms; }
.arisu-browser-tree, .arisu-browser-grid { overflow: auto; scrollbar-width: thin; scrollbar-color: var(--border-color, #444) transparent; }
.arisu-browser-tree { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; padding: 8px;
  border-right: 1px solid var(--border-color, #444); }
.arisu-browser-places { display: flex; gap: 6px; padding-bottom: 8px; }
.arisu-browser-places button { flex: 1; padding: 5px 8px; font-size: 12px; }
.arisu-browser-places button:hover { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-tree-head { display: flex; justify-content: space-between; align-items: center; padding: 4px 6px;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--descrip-text, #999); }
.arisu-browser-tree-head button { padding: 2px 8px; font-size: 11px; text-transform: none; letter-spacing: 0; }
.arisu-browser-saved { display: flex; align-items: center; flex-shrink: 0; }
.arisu-browser-saved-remove { width: 22px; height: 26px; padding: 0; flex-shrink: 0; background: none; border-color: transparent;
  color: var(--descrip-text, #999); }
.arisu-browser-saved-remove:hover { color: inherit; }
.arisu-browser-tree-node { display: flex; align-items: center; flex-shrink: 0; padding-left: calc(var(--depth, 0) * 14px); }
.arisu-browser-tree-toggle { width: 22px; height: 26px; padding: 0; flex-shrink: 0; background: none; border-color: transparent;
  color: var(--descrip-text, #999); }
.arisu-browser-tree-toggle::before { content: '\\25B8'; display: inline-block; transition: transform 150ms ease; }
.arisu-browser-tree-toggle[aria-expanded="true"]::before { transform: rotate(90deg); }
.arisu-browser-tree-toggle:disabled { visibility: hidden; }
.arisu-browser-tree-row { flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; padding: 4px 8px; text-align: left;
  background: none; border-color: transparent; }
.arisu-browser-tree-row span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arisu-browser-tree-row:hover { background: var(--comfy-input-bg, #333); }
.arisu-browser-tree-row[aria-current="true"] { background: var(--comfy-input-bg, #333); border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-grid { flex: 1; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; padding: 12px;
  align-content: start; }
.arisu-browser-file { display: flex; flex-direction: column; gap: 6px; padding: 6px; border-color: transparent; }
.arisu-browser-file:hover { transform: translateY(-2px); border-color: var(--p-primary-color, #6ea8fe);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35); }
.arisu-browser-file[aria-current="true"] { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-file[aria-current="true"] span, .arisu-browser-file:hover span { color: inherit; }
.arisu-browser-file img { width: 100%; aspect-ratio: 1; object-fit: contain; background: #111; border-radius: 6px; opacity: 0;
  transition: opacity 250ms ease; }
.arisu-browser-file img.arisu-loaded { opacity: 1; }
.arisu-browser-file span { font-size: 12px; color: var(--descrip-text, #999); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; transition: color 150ms ease; }
.arisu-fresh .arisu-browser-file { animation: arisu-rise 160ms ease-out backwards; animation-delay: min(calc(var(--i, 0) * 10ms), 120ms); }
.arisu-browser-empty { grid-column: 1 / -1; padding: 32px 12px; text-align: center; color: var(--descrip-text, #999);
  animation: arisu-fade 200ms ease-out; }
@keyframes arisu-pop { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
@keyframes arisu-fade { from { opacity: 0; } }
@keyframes arisu-rise { from { opacity: 0; transform: translateY(4px); } }
@media (prefers-reduced-motion: reduce) {
  .arisu-browser, .arisu-browser::backdrop, .arisu-browser * { animation: none !important; transition: none !important; }
}
`;

/** A pending preview per node, so a load that finishes after a newer pick cannot overwrite it. */
const previewTokens = new WeakMap();
/** The aspect ratio the crop dialog last showed, per node, as `{ path, ratio }` with the file it was chosen for; dropped when the node's file changes. */
const cropRatios = new WeakMap();

function toast(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Load Image (Browse)', detail, life: 8000 });
}

function pathWidget(node) {
  return node.widgets?.find((widget) => widget.name === PATH_WIDGET);
}

function cropWidget(node) {
  return node.widgets?.find((widget) => widget.name === CROP_WIDGET);
}

/** The `{ x, y, w, h }` box the crop widget holds, or `null` when it is blank or malformed. */
function parseCrop(text) {
  const fields = (text ?? '').split(',').map((field) => Number(field.trim()));
  if (fields.length !== 4 || !fields.every(Number.isInteger)) return null;
  const [x, y, w, h] = fields;
  return { x, y, w, h };
}

/** The widget text for `rect`: blank when it covers `img` whole, since a full crop is no crop. */
function formatCrop(rect, img) {
  const whole = rect.x === 0 && rect.y === 0 && rect.w === img.naturalWidth && rect.h === img.naturalHeight;
  return whole ? '' : [rect.x, rect.y, rect.w, rect.h].join(',');
}

/** Keep the crop widget out of sight: the crop dialog is its editor, and the preview shows its effect. */
function hideCrop(node) {
  const widget = cropWidget(node);
  if (widget) hideWidget(node, widget);
}

/** The saved directories, from the user's ComfyUI settings. */
function savedPaths() {
  const value = app.extensionManager?.setting?.get?.(SAVED_PATHS_SETTING);
  return Array.isArray(value)
    ? value.filter((entry) => entry && typeof entry.root === 'string' && typeof entry.path === 'string' && relativePath(entry.path))
    : [];
}

function storeSavedPaths(paths) {
  return app.extensionManager?.setting?.set?.(SAVED_PATHS_SETTING, paths);
}

function isLinked(node, name) {
  return node.inputs?.some((input) => input.widget?.name === name && input.link != null) ?? false;
}

function rootWidget(node) {
  return node.widgets?.find((widget) => widget.name === 'root');
}

function rootValue(node) {
  return rootWidget(node)?.value ?? 'input';
}

/** Client-side migration hint only; the server is the security boundary. */
function relativePath(path) {
  return !/^[\\/~]|^[a-z]:/i.test(path) && !path.replaceAll('\\', '/').split('/').includes('..');
}

function joinPath(dir, name) {
  return dir ? `${dir}/${name}` : name;
}

function isWithin(path, dir) {
  return dir === '' || path === dir || path.startsWith(`${dir}/`);
}

function locationKey(root, path) {
  return JSON.stringify([root, path]);
}

function locationLabel(root, path) {
  return `${root}:${path || '/'}`;
}

/** LiteGraph separates menu groups with `null` entries, hence the guard. */
function notMaskEditor(option) {
  return !MASK_EDITOR_ENTRY.test(option?.content ?? '');
}

/**
 * The view route's URL for `path`: full-resolution pixels, or pixels bounded to `max` and cut to `crop`
 * (the widget text) when given; `bust` defeats the browser cache for a file that may have changed.
 */
function viewUrl(path, max, bust = false, crop = '', root = 'input') {
  const params = new URLSearchParams({ root, path });
  if (max != null) params.set('max', String(max));
  if (crop) params.set('crop', crop);
  if (bust) params.set('t', String(Date.now()));
  return api.apiURL(`${VIEW_ROUTE}?${params}`);
}

/** The image at `url` once loaded, or `null` when the browser cannot load it. */
function loadImage(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/** Show the widgets' file, cropped as they say, on the node once it has loaded; a failed load leaves no stale image behind. */
async function showPreview(node) {
  const path = pathWidget(node)?.value?.trim();
  if (!path || !relativePath(path)) {
    previewTokens.set(node, {});
    node.imgs = undefined;
    node.setDirtyCanvas(true, true);
    if (path) toast('warn', 'Reselect this image with Browse under a configured root; absolute paths are no longer accepted.');
    return;
  }
  const root = rootValue(node);
  const crop = cropWidget(node)?.value?.trim() ?? '';
  const token = {};
  previewTokens.set(node, token);
  // Full-resolution raster pixels preserve the caption size; a failed render gets a bounded retry.
  const img =
    (await loadImage(viewUrl(path, undefined, true, crop, root))) ?? (await loadImage(viewUrl(path, PREVIEW_MAX, true, crop, root)));
  if (previewTokens.get(node) !== token) return;
  if (img) {
    node.imgs = [img];
    node.imageIndex = 0;
    node.previewMediaType = 'image';
  } else {
    node.imgs = undefined;
    toast('warn', `Cannot preview ${path}; check that the file still exists and is an image.`);
  }
  node.setDirtyCanvas(true, true);
}

/** Write the picked file into the path widget the way a user edit would, then preview it; another file drops the old crop. */
function pick(node, path, root) {
  const widget = pathWidget(node);
  if (!widget) return undefined;
  const crop = cropWidget(node);
  if (widget.value !== path || rootValue(node) !== root) {
    if (crop) crop.value = '';
    cropRatios.delete(node);
  }
  const rootField = rootWidget(node);
  if (rootField && rootField.value !== root) setWidget(node, rootField, root);
  setWidget(node, widget, path);
  if (isLinked(node, PATH_WIDGET) || isLinked(node, 'root')) toast('warn', 'The root or path is linked; a run uses its linked value.');
  return showPreview(node);
}

/** Open the crop dialog on the picked file and keep its result in the hidden crop widget, and its ratio for next time. */
async function openCropper(node) {
  const path = pathWidget(node)?.value?.trim();
  const crop = cropWidget(node);
  if (!path || !relativePath(path) || !crop) {
    toast('warn', 'Pick an image first.');
    return;
  }
  // Full-resolution raster pixels keep crop coordinates aligned with node execution.
  const root = rootValue(node);
  const img = await loadImage(viewUrl(path, undefined, true, '', root));
  if (!img) {
    toast('warn', `Cannot crop ${path}: the browser cannot decode this file.`);
    return;
  }
  // a path typed into the field never passes through pick(): a ratio chosen for another file starts over as free
  const remembered = cropRatios.get(node);
  if (remembered && (remembered.path !== path || remembered.root !== root)) cropRatios.delete(node);
  const { rect, ratio } = await cropImage(img, { rect: parseCrop(crop.value), ratio: cropRatios.get(node)?.ratio ?? '' });
  cropRatios.set(node, { root, path, ratio });
  if (!rect || pathWidget(node)?.value?.trim() !== path || rootValue(node) !== root) return;
  setWidget(node, crop, formatCrop(rect, img));
  await showPreview(node);
}

async function openBrowser(node) {
  let listing = { root: rootValue(node), path: '', parent: null, dirs: [], files: [], ancestors: [] };
  let loaded = false;
  let navigation = 0;
  const roots = new Map();
  const tree = new Map();
  const pathField = el('input', {
    className: 'arisu-browser-path',
    type: 'text',
    placeholder: 'path relative to selected root',
    onkeydown: (event) => (event.key === 'Enter' ? navigate(listing.root, pathField.value) : undefined),
  });
  const upButton = el('button', { textContent: '↑ up', onclick: () => navigate(listing.root, listing.parent) });
  const filterField = el('input', { type: 'search', placeholder: 'filter images', oninput: () => renderGrid(false) });
  const saveButton = el('button', { textContent: '+ save', onclick: savePath });
  const savedList = el('div', { className: 'arisu-browser-saved-list' });
  const treeList = el('div', { className: 'arisu-browser-tree-list' });
  const treePane = el('div', { className: 'arisu-browser-tree' }, [
    el('div', { className: 'arisu-browser-places' }, [
      el('button', { textContent: 'input dir', onclick: () => navigate('input', '') }),
      el('button', { textContent: 'output dir', onclick: () => navigate('output', '') }),
    ]),
    el('div', { className: 'arisu-browser-tree-head' }, [el('span', { textContent: 'Saved' }), saveButton]),
    savedList,
    el('div', { className: 'arisu-browser-tree-head' }, [
      el('span', { textContent: 'Folders' }),
      el('button', { textContent: 'collapse', onclick: collapseAll }),
    ]),
    treeList,
  ]);
  const grid = el('div', { className: 'arisu-browser-grid' });
  const panes = el('div', { className: 'arisu-browser-body' }, [treePane, grid]);
  const dialog = el('dialog', { className: 'arisu-browser', onclose: () => dialog.remove() }, [
    el('style', { textContent: STYLE }),
    el('div', { className: 'arisu-browser-bar' }, [
      pathField,
      upButton,
      filterField,
      el('button', { textContent: '✕', onclick: () => dialog.close() }),
    ]),
    panes,
  ]);
  closeOnBackdropClick(dialog);

  function treeNode(root, path) {
    const key = locationKey(root, path);
    if (!tree.has(key)) tree.set(key, { root, path, dirs: null, expanded: false });
    return tree.get(key);
  }

  async function fetchListing(root, path, withTree) {
    const params = new URLSearchParams({ root, path });
    if (!withTree) params.set('tree', '0');
    const response = await api.fetchApi(`${BROWSE_ROUTE}?${params}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error ?? response.statusText);
    return data;
  }

  function absorb(data) {
    for (const root of data.roots) roots.set(root.id, root.label);
    for (const level of data.ancestors) Object.assign(treeNode(data.root, level.path), { dirs: level.dirs, expanded: true });
    Object.assign(treeNode(data.root, data.path), { dirs: data.dirs, expanded: true });
  }

  function current(root, path) {
    return loaded && root === listing.root && path === listing.path;
  }

  function treeRows(root, path, label, depth) {
    const state = treeNode(root, path);
    const toggle = el('button', {
      className: 'arisu-browser-tree-toggle',
      ariaExpanded: state.expanded ? 'true' : 'false',
      disabled: state.dirs?.length === 0,
      onclick: () => expand(root, path),
    });
    const row = el(
      'button',
      {
        className: 'arisu-browser-tree-row',
        title: locationLabel(root, path),
        ariaCurrent: current(root, path) ? 'true' : null,
        onclick: () => navigate(root, path, false),
      },
      [el('span', { textContent: path ? ICONS.folder : ICONS.root }), el('span', { textContent: label })],
    );
    const rows = [el('div', { className: 'arisu-browser-tree-node', style: `--depth: ${depth}` }, [toggle, row])];
    if (state.expanded && state.dirs) {
      for (const name of state.dirs) rows.push(...treeRows(root, joinPath(path, name), name, depth + 1));
    }
    return rows;
  }

  function renderTree() {
    treeList.replaceChildren(...[...roots].flatMap(([id, label]) => treeRows(id, '', label, 0)));
  }

  function savedRow(location) {
    const { root, path } = location;
    const row = el(
      'button',
      {
        className: 'arisu-browser-tree-row',
        title: locationLabel(root, path),
        ariaCurrent: current(root, path) ? 'true' : null,
        onclick: () => navigate(root, path),
      },
      [el('span', { textContent: ICONS.saved }), el('span', { textContent: locationLabel(root, path) })],
    );
    const remove = el('button', {
      className: 'arisu-browser-saved-remove',
      textContent: '✕',
      onclick: async () => {
        await storeSavedPaths(savedPaths().filter((saved) => locationKey(saved.root, saved.path) !== locationKey(root, path)));
        renderSaved();
      },
    });
    return el('div', { className: 'arisu-browser-saved' }, [row, remove]);
  }

  function renderSaved() {
    const saved = savedPaths();
    saveButton.disabled = !loaded || saved.some(({ root, path }) => current(root, path));
    savedList.replaceChildren(...saved.map(savedRow));
  }

  async function savePath() {
    if (saveButton.disabled) return;
    await storeSavedPaths([...savedPaths(), { root: listing.root, path: listing.path }]);
    renderSaved();
  }

  function renderGrid(fresh) {
    const files = listing.files.filter((name) => name.toLowerCase().includes(filterField.value.trim().toLowerCase()));
    const cards = files.map((name, index) => {
      const path = joinPath(listing.path, name);
      const root = listing.root;
      const thumbnail = el('img', {
        loading: 'lazy',
        alt: name,
        onload: (event) => {
          event.target.className = 'arisu-loaded';
        },
        src: viewUrl(path, THUMBNAIL_MAX, false, '', root),
      });
      return el(
        'button',
        {
          className: 'arisu-browser-file',
          style: `--i: ${index}`,
          title: locationLabel(root, path),
          ariaCurrent: root === rootValue(node) && path === pathWidget(node)?.value?.trim() ? 'true' : null,
          onclick: () => {
            dialog.close();
            return pick(node, path, root);
          },
        },
        [thumbnail, el('span', { textContent: name })],
      );
    });
    grid.className = fresh ? 'arisu-browser-grid arisu-fresh' : 'arisu-browser-grid';
    grid.replaceChildren(...(cards.length ? cards : [el('div', { className: 'arisu-browser-empty', textContent: 'No images here' })]));
  }

  async function navigate(root, path, withTree = true) {
    if (path == null) return;
    const token = ++navigation;
    panes.ariaBusy = 'true';
    try {
      const data = await fetchListing(root, path, withTree);
      if (token !== navigation || !dialog.open) return;
      listing = data;
      loaded = true;
      absorb(data);
      pathField.value = data.path;
      pathField.title = `Relative to ${data.root}`;
      upButton.disabled = data.parent == null;
      renderGrid(true);
      renderSaved();
      renderTree();
    } catch (error) {
      if (token === navigation) toast('error', `Cannot open directory: ${error.message}`);
    } finally {
      if (token === navigation) panes.ariaBusy = 'false';
    }
  }

  async function expand(root, path) {
    const state = treeNode(root, path);
    if (!state.expanded && state.dirs == null) {
      try {
        state.dirs = (await fetchListing(root, path, false)).dirs;
      } catch (error) {
        toast('error', `Cannot open directory: ${error.message}`);
        return;
      }
    }
    state.expanded = !state.expanded;
    renderTree();
  }

  function collapseAll() {
    for (const state of tree.values()) state.expanded = state.root === listing.root && isWithin(listing.path, state.path);
    renderTree();
  }

  document.body.append(dialog);
  dialog.showModal();
  renderSaved();
  const start = pathWidget(node)?.value?.trim() ?? '';
  if (!relativePath(start)) toast('warn', 'Reselect this image under a configured root; absolute paths are no longer accepted.');
  await navigate(rootValue(node), relativePath(start) ? start : '');
  if (!loaded) await navigate('input', '');
}

app.registerExtension({
  name: 'Arisu.Common.LoadImage',
  // hidden: edited from the browse dialog, persisted per ComfyUI user by the frontend's settings store
  settings: [{ id: SAVED_PATHS_SETTING, name: 'Load Image (Browse): saved browse paths', type: 'hidden', defaultValue: [] }],
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      addButton(this, 'browse', () => openBrowser(this));
      addButton(this, 'crop…', () => openCropper(this));
      hideCrop(this);
      const root = rootWidget(this);
      if (root) {
        const node = this;
        const callback = root.callback;
        root.callback = function () {
          callback?.apply(this, arguments);
          const crop = cropWidget(node);
          if (crop) crop.value = '';
          cropRatios.delete(node);
          return showPreview(node);
        };
      }
    };

    // configure() has restored the widget values, and the saved sockets, by the time it calls this: show the saved file again
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      hideCrop(this);
      return showPreview(this);
    };

    // The frontend installs getExtraMenuOptions on every node class before extensions see it, and
    // once a node previews (`node.imgs`) it adds "Open in MaskEditor" ("| Image Canvas" in newer
    // builds). The mask editor cannot work here: it loads the file by a `filename` query parameter
    // and saves by uploading into input/ and writing a widget named `image`, while this node holds
    // a `path` read in place. LiteGraph builds the menu from both the `options` array the hook
    // mutates and the list it returns, so the entry is dropped from each.
    const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (_canvas, options) {
      const extra = getExtraMenuOptions?.apply(this, arguments);
      options.splice(0, options.length, ...options.filter(notMaskEditor));
      return Array.isArray(extra) ? extra.filter(notMaskEditor) : extra;
    };
  },
});
