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
// `el()`, so the dialog touches a small DOM surface.
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

const STYLE = `
.arisu-browser { width: min(1100px, 92vw); height: min(760px, 88vh); padding: 0; border: 1px solid var(--border-color, #444);
  border-radius: 8px; background: var(--comfy-menu-bg, #202020); color: var(--fg-color, #ddd); font-family: inherit; font-size: 13px; }
.arisu-browser[open] { display: flex; flex-direction: column; }
.arisu-browser::backdrop { background: rgba(0, 0, 0, 0.6); }
.arisu-browser button { background: var(--comfy-input-bg, #333); color: inherit; border: 1px solid var(--border-color, #444);
  border-radius: 4px; padding: 4px 8px; cursor: pointer; font: inherit; }
.arisu-browser button:disabled { opacity: 0.4; cursor: default; }
.arisu-browser input { background: var(--comfy-input-bg, #333); color: inherit; border: 1px solid var(--border-color, #444);
  border-radius: 4px; padding: 4px 6px; font: inherit; }
.arisu-browser-bar { display: flex; gap: 6px; padding: 8px; border-bottom: 1px solid var(--border-color, #444); }
.arisu-browser-path { flex: 1; min-width: 0; }
.arisu-browser-body { display: flex; flex: 1; min-height: 0; }
.arisu-browser-dirs { width: 220px; overflow: auto; display: flex; flex-direction: column; gap: 2px; padding: 6px;
  border-right: 1px solid var(--border-color, #444); }
.arisu-browser-dir { text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arisu-browser-dir::before { content: '\\1F4C1  '; }
.arisu-browser-grid { flex: 1; overflow: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px;
  padding: 8px; align-content: start; }
.arisu-browser-file { display: flex; flex-direction: column; gap: 4px; padding: 4px; }
.arisu-browser-file img { width: 100%; aspect-ratio: 1; object-fit: contain; background: #111; border-radius: 4px; }
.arisu-browser-file span { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
      el('div', { className: 'arisu-browser-body' }, [dirList, grid]),
    ],
  );

  function matches(name) {
    return name.toLowerCase().includes(filterField.value.trim().toLowerCase());
  }

  function dirRow(name) {
    return el('button', {
      className: 'arisu-browser-dir',
      textContent: name,
      title: name,
      onclick: () => navigate(joinPath(listing.path, name)),
    });
  }

  function render() {
    upButton.disabled = listing.parent == null;
    dirList.replaceChildren(...listing.dirs.filter(matches).map(dirRow));
    grid.replaceChildren(
      ...listing.files.filter(matches).map((name) => {
        const full = joinPath(listing.path, name);
        const onclick = () => {
          dialog.close();
          return pick(node, full);
        };
        return el('button', { className: 'arisu-browser-file', title: full, onclick }, [
          el('img', { src: viewUrl(full, THUMBNAIL_MAX), loading: 'lazy', alt: name }),
          el('span', { textContent: name }),
        ]);
      }),
    );
  }

  /** Fetch and show `path` (an empty path is the input directory); on failure the dialog stays for another try. */
  async function navigate(path) {
    if (path == null) return;
    try {
      const response = await api.fetchApi(`${BROWSE_ROUTE}?${new URLSearchParams({ path })}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error ?? response.statusText);
      listing = data;
      pathField.value = data.path;
      render();
    } catch (error) {
      toast('error', `Cannot open directory: ${error.message}`);
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
  },
});
