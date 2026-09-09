// Load Image (Browse): a "browse" button that picks an image file from any path on the host.
//
// The stock Load Image lists the top level of the input directory and brings
// other files in by uploading a copy there. This node holds a path instead;
// the button opens a directory browser fed by the pack's /arisu/browse route
// (subdirectories and image files by name) with thumbnails and the node
// preview served by /arisu/view. Picking a file writes its path into the
// `path` widget; the file is read in place at run time. Nothing is uploaded.
//
// The browser is a native <dialog>: it sits in the browser's top layer above
// the canvas and the frontend's own layers, traps focus, and closes on Escape,
// on the close button, or on a backdrop click. Every element is built through
// `el()`, so the dialog touches a small DOM surface. Motion and state live in
// the stylesheet: the dialog and its rows animate on keyframes, and the
// loading and picked states are ARIA attributes the CSS reads, so the script
// only assigns properties.
//
// The preview goes through `node.imgs`, which the classic node canvas draws
// below the widgets. The Vue node renderer ("Nodes 2.0") reads previews from
// its own store instead, so there the node shows none; the dialog still works.

import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { addButton } from './widgets.js';

const NODE_TYPE = 'ArisuLoadImage';
const PATH_WIDGET = 'path';
const BROWSE_ROUTE = '/arisu/browse';
const VIEW_ROUTE = '/arisu/view';
const THUMBNAIL_MAX = 256;
const PREVIEW_MAX = 1024;
/** The context-menu entry the frontend adds to every previewing node; see beforeRegisterNodeDef for why it goes. */
const MASK_EDITOR_ENTRY = /mask ?editor/i;

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
.arisu-browser button:disabled { opacity: 0.4; cursor: default; pointer-events: none; }
.arisu-browser :focus-visible { outline: 2px solid var(--p-primary-color, #6ea8fe); outline-offset: 2px; }
.arisu-browser input:focus-visible { outline: none; border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-bar { display: flex; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #444); }
.arisu-browser-bar button:hover { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-path { flex: 1; min-width: 0; }
.arisu-browser-body { display: flex; flex: 1; min-height: 0; transition: opacity 150ms ease; }
.arisu-browser-body[aria-busy="true"] { opacity: 0.45; pointer-events: none; transition-delay: 200ms; }
.arisu-browser-dirs, .arisu-browser-grid { overflow: auto; scrollbar-width: thin; scrollbar-color: var(--border-color, #444) transparent; }
.arisu-browser-dirs { width: 240px; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; padding: 8px;
  border-right: 1px solid var(--border-color, #444); }
.arisu-browser-dir { flex-shrink: 0; padding: 6px 10px; text-align: left; background: none; border-color: transparent;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arisu-browser-dir:hover { background: var(--comfy-input-bg, #333); }
.arisu-browser-dir::before { content: '\\1F4C1  '; }
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
.arisu-browser-dir, .arisu-browser-file { animation: arisu-rise 200ms ease-out backwards;
  animation-delay: min(calc(var(--i, 0) * 15ms), 240ms); }
.arisu-browser-empty { grid-column: 1 / -1; padding: 32px 12px; text-align: center; color: var(--descrip-text, #999);
  animation: arisu-fade 200ms ease-out; }
@keyframes arisu-pop { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
@keyframes arisu-fade { from { opacity: 0; } }
@keyframes arisu-rise { from { opacity: 0; transform: translateY(8px); } }
@media (prefers-reduced-motion: reduce) {
  .arisu-browser, .arisu-browser::backdrop, .arisu-browser * { animation: none !important; transition: none !important; }
}
`;

/** A pending preview per node, so a load that finishes after a newer pick cannot overwrite it. */
const previewTokens = new WeakMap();

function toast(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Load Image (Browse)', detail, life: 8000 });
}

/** A DOM element with `props` assigned and `children` appended; every element of the dialog is built here. */
function el(tag, props = {}, children = []) {
  const element = document.createElement(tag);
  Object.assign(element, props);
  element.append(...children);
  return element;
}

function pathWidget(node) {
  return node.widgets?.find((widget) => widget.name === PATH_WIDGET);
}

function isLinked(node, name) {
  return node.inputs?.some((input) => input.widget?.name === name && input.link != null) ?? false;
}

function joinPath(dir, name) {
  return dir.endsWith('/') || dir.endsWith('\\') ? `${dir}${name}` : `${dir}/${name}`;
}

/** LiteGraph separates menu groups with `null` entries, hence the guard. */
function notMaskEditor(option) {
  return !MASK_EDITOR_ENTRY.test(option?.content ?? '');
}

/** The view route's URL for `path`, bounded to `max` pixels; `bust` defeats the browser cache for a file that may have changed. */
function viewUrl(path, max, bust = false) {
  const params = new URLSearchParams({ path, max: String(max) });
  if (bust) params.set('t', String(Date.now()));
  return api.apiURL(`${VIEW_ROUTE}?${params}`);
}

/** Show `path` on the node once it has loaded; a failed load leaves no stale image behind. */
function showPreview(node, path) {
  const token = {};
  previewTokens.set(node, token);
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      if (previewTokens.get(node) === token) {
        node.imgs = [img];
        node.imageIndex = 0;
        node.previewMediaType = 'image';
        node.setDirtyCanvas(true, true);
      }
      resolve();
    };
    img.onerror = () => {
      if (previewTokens.get(node) === token) {
        node.imgs = undefined;
        node.setDirtyCanvas(true, true);
        toast('warn', `Cannot preview ${path}; check that the file still exists and is an image.`);
      }
      resolve();
    };
    img.src = viewUrl(path, PREVIEW_MAX, true);
  });
}

/** Write the picked file into the path widget the way a user edit would, then preview it. */
function pick(node, path) {
  const widget = pathWidget(node);
  if (!widget) return undefined;
  const previous = widget.value;
  widget.value = path;
  widget.callback?.(path);
  node.onWidgetChanged?.(PATH_WIDGET, path, previous, widget);
  node.setDirtyCanvas(true, true);
  if (isLinked(node, PATH_WIDGET)) toast('warn', 'path is fed by a link, so a run uses the linked value, not the picked file.');
  return showPreview(node, path);
}

async function openBrowser(node) {
  let listing = { path: '', parent: null, dirs: [], files: [] };

  const pathField = el('input', {
    className: 'arisu-browser-path',
    type: 'text',
    placeholder: 'directory path',
    onkeydown: (event) => (event.key === 'Enter' ? navigate(pathField.value) : undefined),
  });
  const upButton = el('button', { textContent: '↑ up', title: 'parent directory', onclick: () => navigate(listing.parent) });
  const filterField = el('input', { type: 'search', placeholder: 'filter names', oninput: () => render() });
  const dirList = el('div', { className: 'arisu-browser-dirs' });
  const grid = el('div', { className: 'arisu-browser-grid' });
  const panes = el('div', { className: 'arisu-browser-body' }, [dirList, grid]);
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
        el('button', { textContent: 'input dir', title: "ComfyUI's input directory", onclick: () => navigate('') }),
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

  /** `index` staggers the rise-in animation through the `--i` custom property the stylesheet reads. */
  function dirRow(name, index) {
    return el('button', {
      className: 'arisu-browser-dir',
      style: `--i: ${index}`,
      textContent: name,
      title: name,
      onclick: () => navigate(joinPath(listing.path, name)),
    });
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

  function render() {
    upButton.disabled = listing.parent == null;
    const current = pathWidget(node)?.value?.trim();
    const dirs = listing.dirs.filter(matches).map(dirRow);
    const files = listing.files.filter(matches).map((name, index) => fileCard(name, index, current));
    dirList.replaceChildren(...(dirs.length ? dirs : [empty('No folders')]));
    grid.replaceChildren(...(files.length ? files : [empty('No images here')]));
  }

  /** Fetch and show `path` (an empty path is the input directory); on failure the dialog stays for another try. */
  async function navigate(path) {
    if (path == null) return;
    panes.ariaBusy = 'true';
    try {
      const response = await api.fetchApi(`${BROWSE_ROUTE}?${new URLSearchParams({ path })}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error ?? response.statusText);
      listing = data;
      pathField.value = data.path;
      render();
    } catch (error) {
      toast('error', `Cannot open directory: ${error.message}`);
    } finally {
      panes.ariaBusy = 'false';
    }
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
    };

    // configure() has restored the widget values by the time it calls this: show the saved file again
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      const path = pathWidget(this)?.value?.trim();
      return path ? showPreview(this, path) : undefined;
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
