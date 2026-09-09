// Load Image (Browse): a "browse" button that picks an image file from any path on the host.
//
// The stock Load Image lists the top level of the input directory and brings
// other files in by uploading a copy there. This node holds a path instead;
// the button opens a directory browser fed by the pack's /arisu/browse route
// with thumbnails and the node preview served by /arisu/view. Picking a file
// writes its path into the `path` widget; the file is read in place at run
// time. Nothing is uploaded.
//
// The left pane is a directory tree the way a system file explorer draws one:
// the roots are the user's home and the mounted disks the route reports, plus
// an ad-hoc root for the chain to a directory outside them (a typed path, or
// an install under /opt). A listing carries its ancestor chain, so the tree
// opens expanded down to the current directory; a click from inside the tree
// asks for no chain (`tree=0`), since it already has one. Clicking a row
// navigates, the chevron only expands, and "collapse" folds everything but the
// chain to the current directory. The filter box narrows the image cards only.
//
// The browser is a native <dialog>: it sits in the browser's top layer above
// the canvas and the frontend's own layers, traps focus, and closes on Escape,
// on the close button, or on a backdrop click. Every element is built through
// `el()`, so the dialog touches a small DOM surface. Motion and state live in
// the stylesheet: the dialog pops in, the image cards rise once when a
// directory is entered (never on a tree click or a filter keystroke, and the
// tree rows never animate), and the loading and picked states are ARIA
// attributes the CSS reads, so the script only assigns properties.
//
// A second button, `crop…`, opens the crop dialog of cropper.js on the picked
// file. The result lives in the node's `crop` input, `left,top,width,height`
// in pixels of the upright image, which this script hides: the dialog is its
// editor and the preview shows its effect. A blank crop is the whole image, so
// applying the whole image or pressing reset stores nothing, and picking
// another file drops the crop of the previous one. Nothing is uploaded: the
// run crops in memory and the preview asks /arisu/view for the cropped pixels.
//
// The preview goes through `node.imgs`, which the classic node canvas draws
// below the widgets. The frontend captions it with the loaded image's own
// size, so the preview loads the file itself (cropped by the route when a crop
// is set) and falls back to a thumbnail only for a format the browser cannot
// decode. The Vue node renderer ("Nodes 2.0") reads previews from its own
// store instead, so there the node shows none; the dialogs still work.

import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { cropImage } from './cropper.js';
import { el } from './dom.js';
import { addButton, hideWidget, setWidget } from './widgets.js';

const NODE_TYPE = 'ArisuLoadImage';
const PATH_WIDGET = 'path';
const CROP_WIDGET = 'crop';
const BROWSE_ROUTE = '/arisu/browse';
const VIEW_ROUTE = '/arisu/view';
const THUMBNAIL_MAX = 256;
/** The preview's fallback bound, for a file the browser cannot decode itself (TIFF, for one). */
const PREVIEW_MAX = 1024;
/** The context-menu entry the frontend adds to every previewing node; see beforeRegisterNodeDef for why it goes. */
const MASK_EDITOR_ENTRY = /mask ?editor/i;
/** Tree icons by row kind: the home root, a mounted disk, an ad-hoc root for a path outside them, a folder. */
const ICONS = { home: '\u{1F3E0}', disk: '\u{1F4BE}', adhoc: '\u{1F5A5}', folder: '\u{1F4C1}' };

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

function isLinked(node, name) {
  return node.inputs?.some((input) => input.widget?.name === name && input.link != null) ?? false;
}

function joinPath(dir, name) {
  return dir.endsWith('/') || dir.endsWith('\\') ? `${dir}${name}` : `${dir}/${name}`;
}

/** Whether `path` is `dir` or lies inside it. */
function isWithin(path, dir) {
  return path === dir || path.startsWith(joinPath(dir, ''));
}

/** LiteGraph separates menu groups with `null` entries, hence the guard. */
function notMaskEditor(option) {
  return !MASK_EDITOR_ENTRY.test(option?.content ?? '');
}

/**
 * The view route's URL for `path`: the file itself, or a rendering bounded to `max` pixels and cut to `crop`
 * (the widget text) when given; `bust` defeats the browser cache for a file that may have changed.
 */
function viewUrl(path, max, bust = false, crop = '') {
  const params = new URLSearchParams({ path });
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
  if (!path) return;
  const crop = cropWidget(node)?.value?.trim() ?? '';
  const token = {};
  previewTokens.set(node, token);
  // the file itself, so the frontend's caption shows its real size; a format the browser cannot decode gets a thumbnail
  const img = (await loadImage(viewUrl(path, undefined, true, crop))) ?? (await loadImage(viewUrl(path, PREVIEW_MAX, true, crop)));
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
function pick(node, path) {
  const widget = pathWidget(node);
  if (!widget) return undefined;
  const crop = cropWidget(node);
  if (crop && widget.value !== path) crop.value = '';
  setWidget(node, widget, path);
  if (isLinked(node, PATH_WIDGET)) toast('warn', 'path is fed by a link, so a run uses the linked value, not the picked file.');
  return showPreview(node);
}

/** Open the crop dialog on the picked file and keep its result in the hidden crop widget. */
async function openCropper(node) {
  const path = pathWidget(node)?.value?.trim();
  const crop = cropWidget(node);
  if (!path || !crop) {
    toast('warn', 'Pick an image first.');
    return;
  }
  // the file itself: the crop is in its pixels, and a thumbnail would not tell how many there are
  const img = await loadImage(viewUrl(path, undefined, true));
  if (!img) {
    toast('warn', `Cannot crop ${path}: the browser cannot decode this file.`);
    return;
  }
  const rect = await cropImage(img, parseCrop(crop.value));
  if (!rect) return;
  setWidget(node, crop, formatCrop(rect, img));
  await showPreview(node);
}

async function openBrowser(node) {
  let listing = { path: '', parent: null, dirs: [], files: [], ancestors: [] };
  let places = { input: '', output: '' };
  /** The tree roots by path, `{ label, kind }`: the route's roots, plus ad-hoc ones for the dialog's lifetime. */
  const roots = new Map();
  /** Every directory the tree has seen, by path: `{ dirs, expanded }`, `dirs` null until listed. */
  const tree = new Map();
  /** The directory the tree last scrolled to, so expanding a folder leaves the list where it is. */
  let scrolledTo = null;

  const pathField = el('input', {
    className: 'arisu-browser-path',
    type: 'text',
    placeholder: 'directory path',
    onkeydown: (event) => (event.key === 'Enter' ? navigate(pathField.value) : undefined),
  });
  const upButton = el('button', { textContent: '↑ up', title: 'parent directory', onclick: () => navigate(listing.parent) });
  const filterField = el('input', { type: 'search', placeholder: 'filter images', oninput: () => renderGrid(false) });
  const outputPlace = el('button', {
    textContent: 'output dir',
    title: "ComfyUI's output directory",
    onclick: () => navigate(places.output),
  });
  const treeList = el('div', { className: 'arisu-browser-tree-list' });
  const treePane = el('div', { className: 'arisu-browser-tree' }, [
    el('div', { className: 'arisu-browser-places' }, [
      el('button', { textContent: 'input dir', title: "ComfyUI's input directory", onclick: () => navigate('') }),
      outputPlace,
    ]),
    el('div', { className: 'arisu-browser-tree-head' }, [
      el('span', { textContent: 'Folders' }),
      el('button', { textContent: 'collapse', title: 'collapse every folder but the current one', onclick: () => collapseAll() }),
    ]),
    treeList,
  ]);
  const grid = el('div', { className: 'arisu-browser-grid' });
  const panes = el('div', { className: 'arisu-browser-body' }, [treePane, grid]);
  const dialog = el(
    'dialog',
    {
      className: 'arisu-browser',
      onclose: () => dialog.remove(),
      onclick: (event) => (event.target === dialog ? dialog.close() : undefined),
    },
    [
      el('style', { textContent: STYLE }),
      el('div', { className: 'arisu-browser-bar' }, [
        pathField,
        upButton,
        filterField,
        el('button', { textContent: '✕', title: 'close', onclick: () => dialog.close() }),
      ]),
      panes,
    ],
  );

  function matches(name) {
    return name.toLowerCase().includes(filterField.value.trim().toLowerCase());
  }

  function empty(text) {
    return el('div', { className: 'arisu-browser-empty', textContent: text });
  }

  function treeNode(path) {
    let state = tree.get(path);
    if (!state) {
      state = { dirs: null, expanded: false };
      tree.set(path, state);
    }
    return state;
  }

  /** Fetch the listing of `path` (an empty path is the input directory); `withTree` asks for the ancestor chain too. */
  async function fetchListing(path, withTree) {
    const params = new URLSearchParams({ path });
    if (!withTree) params.set('tree', '0');
    const response = await api.fetchApi(`${BROWSE_ROUTE}?${params}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error ?? response.statusText);
    return data;
  }

  /** Take a listing's roots, places and chain into the tree; the chain and the listed directory open. */
  function absorb(data) {
    (data.roots ?? []).forEach((root, index) => {
      if (!roots.has(root.path)) roots.set(root.path, { label: root.label, kind: index === 0 ? 'home' : 'disk' });
    });
    places = data.places ?? places;
    const chain = data.ancestors ?? [];
    const top = chain[0]?.path ?? data.path;
    if (![...roots.keys()].some((root) => isWithin(top, root))) roots.set(top, { label: top, kind: 'adhoc' });
    for (const level of chain) Object.assign(treeNode(level.path), { dirs: level.dirs, expanded: true });
    Object.assign(treeNode(data.path), { dirs: data.dirs, expanded: true });
  }

  /** The rows for `path` and, when it is expanded, its subdirectories, depth first. */
  function treeRows(path, label, kind, depth) {
    const state = treeNode(path);
    const known = state.dirs != null;
    const toggle = el('button', {
      className: 'arisu-browser-tree-toggle',
      title: state.expanded ? 'collapse' : 'expand',
      ariaExpanded: state.expanded ? 'true' : 'false',
      disabled: known && state.dirs.length === 0,
      onclick: () => expand(path),
    });
    const row = el(
      'button',
      {
        className: 'arisu-browser-tree-row',
        title: path,
        ariaCurrent: path === listing.path ? 'true' : null,
        onclick: () => navigate(path, false),
      },
      [el('span', { textContent: ICONS[kind] }), el('span', { textContent: label })],
    );
    const rows = [el('div', { className: 'arisu-browser-tree-node', style: `--depth: ${depth}` }, [toggle, row])];
    if (state.expanded && known) {
      for (const name of state.dirs) rows.push(...treeRows(joinPath(path, name), name, 'folder', depth + 1));
    }
    return rows;
  }

  function renderTree() {
    outputPlace.disabled = !places.output;
    const rows = [];
    for (const [path, root] of roots) rows.push(...treeRows(path, root.label, root.kind, 0));
    treeList.replaceChildren(...rows);
    if (listing.path === scrolledTo) return;
    scrolledTo = listing.path;
    rows.find((row) => row.children[1].ariaCurrent === 'true')?.scrollIntoView?.({ block: 'nearest' });
  }

  /** A thumbnail card; the card holding `current`, the path already in the widget, is outlined. */
  function fileCard(name, index, current) {
    const full = joinPath(listing.path, name);
    const onclick = () => {
      dialog.close();
      return pick(node, full);
    };
    // onload is assigned before src: a cached thumbnail fires load as soon as src is set
    const thumbnail = el('img', {
      loading: 'lazy',
      alt: name,
      onload: (event) => {
        event.target.className = 'arisu-loaded';
      },
      src: viewUrl(full, THUMBNAIL_MAX),
    });
    const props = {
      className: 'arisu-browser-file',
      style: `--i: ${index}`,
      title: full,
      ariaCurrent: full === current ? 'true' : null,
      onclick,
    };
    return el('button', props, [thumbnail, el('span', { textContent: name })]);
  }

  /**
   * The image cards of the current directory, narrowed by the filter box; folders are never filtered.
   * `fresh` marks a directory just entered, the one time the cards rise into place.
   */
  function renderGrid(fresh) {
    const current = pathWidget(node)?.value?.trim();
    const files = listing.files.filter(matches).map((name, index) => fileCard(name, index, current));
    grid.className = fresh ? 'arisu-browser-grid arisu-fresh' : 'arisu-browser-grid';
    grid.replaceChildren(...(files.length ? files : [empty('No images here')]));
  }

  function render() {
    upButton.disabled = listing.parent == null;
    renderGrid(true);
    renderTree();
  }

  /** Show `path`; on failure the dialog stays for another try. A click inside the tree needs no chain. */
  async function navigate(path, withTree = true) {
    if (path == null) return;
    panes.ariaBusy = 'true';
    try {
      const data = await fetchListing(path, withTree);
      listing = data;
      absorb(data);
      pathField.value = data.path;
      render();
    } catch (error) {
      toast('error', `Cannot open directory: ${error.message}`);
    } finally {
      panes.ariaBusy = 'false';
    }
  }

  /** Toggle the subdirectories of `path` in the tree, listing them first when they are not known yet. */
  async function expand(path) {
    const state = treeNode(path);
    if (!state.expanded && state.dirs == null) {
      try {
        state.dirs = (await fetchListing(path, false)).dirs;
      } catch (error) {
        toast('error', `Cannot open directory: ${error.message}`);
        return;
      }
    }
    state.expanded = !state.expanded;
    renderTree();
  }

  /** Fold every folder except the current directory and the chain leading to it. */
  function collapseAll() {
    for (const [path, state] of tree) state.expanded = isWithin(listing.path, path);
    renderTree();
  }

  document.body.append(dialog);
  dialog.showModal();
  // open where the current file lives (the route lists a file's directory); fall back to the input directory
  const start = pathWidget(node)?.value?.trim() ?? '';
  await navigate(start);
  if (start && listing.path === '') await navigate('');
}

app.registerExtension({
  name: 'Arisu.Common.LoadImage',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      addButton(this, 'browse', () => openBrowser(this));
      addButton(this, 'crop…', () => openCropper(this));
      hideCrop(this);
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
