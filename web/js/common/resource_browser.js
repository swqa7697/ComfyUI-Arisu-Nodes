// Shared contained Browse dialog for Load Image and Resource Studio.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { closeOnBackdropClick, el } from './dom.js';

const PATH_WIDGET = 'path';
const browserDialogs = new WeakMap();
function pathWidget(node) {
  return node.widgets?.find((widget) => widget.name === PATH_WIDGET);
}
function toast(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Browse resources', detail, life: 8000 });
}
export function closeBrowser(node) {
  browserDialogs.get(node)?.close();
  browserDialogs.delete(node);
}
const BROWSE_ROUTE = '/arisu/browse';
const VIEW_ROUTE = '/arisu/view';
const ROOTS_ROUTE = '/arisu/roots';
const THUMBNAIL_MAX = 256;
/** The hidden ComfyUI setting holding the browser's saved directories, an array of {root, path, name?} locations. */
export const SAVED_PATHS_SETTING = 'Arisu.LoadImage.SavedLocations';
export const DEFAULT_ROOT_SETTING = {
  id: 'Arisu.LoadImage.DefaultRoot',
  category: ['Arisu Nodes', 'LoadImage'],
  name: 'Load Image (Browse): default location',
  type: 'combo',
  defaultValue: 'input',
  options: ['input', 'output'],
  tooltip: 'Starting root when Browse opens without a selected image. Saved paths are not included.',
};
let rootsDiscovered = false;

/** Populate settings without scanning directories. Retry a failed discovery on Browse. */
export async function discoverRoots() {
  rootsDiscovered = false;
  try {
    const response = await api.fetchApi(ROOTS_ROUTE);
    if (!response.ok) return;
    const data = await response.json();
    const options = data.roots.map(({ id, label }) => ({ value: id, text: label }));
    DEFAULT_ROOT_SETTING.options = options;
    // Update the registered definition so the settings panel observes the change reactively.
    const registered = app.ui?.settings?.settingsLookup?.[DEFAULT_ROOT_SETTING.id];
    if (registered) registered.options = options;
    rootsDiscovered = true;
  } catch {
    // Built-in choices remain usable; a later Browse retries discovery.
  }
}

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
.arisu-browser-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #444); }
.arisu-browser-bar button { flex-shrink: 0; white-space: nowrap; }
.arisu-browser-bar input { min-width: 0; width: 160px; max-width: 100%; }
.arisu-browser-bar button:hover { border-color: var(--p-primary-color, #6ea8fe); }
.arisu-browser-path { flex: 1; min-width: 0; padding: 6px 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--descrip-text, #999); font-variant-numeric: tabular-nums; }
.arisu-browser-body { display: flex; flex: 1; min-height: 0; transition: opacity 150ms ease; }
.arisu-browser-body[aria-busy="true"] { opacity: 0.45; pointer-events: none; transition-delay: 200ms; }
.arisu-browser-tree, .arisu-browser-grid { overflow: auto; scrollbar-width: thin; scrollbar-color: var(--border-color, #444) transparent; }
.arisu-browser-tree { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; padding: 8px;
  border-right: 1px solid var(--border-color, #444); }
.arisu-browser-tree-head { display: flex; justify-content: space-between; align-items: center; padding: 4px 6px;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--descrip-text, #999); }
.arisu-browser-tree-head button { padding: 2px 8px; font-size: 11px; text-transform: none; letter-spacing: 0; }
.arisu-browser-name-editor { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 0; }
.arisu-browser-name-editor input { width: 100%; box-sizing: border-box; }
.arisu-browser-saved { display: flex; align-items: center; flex-shrink: 0; }
.arisu-browser-saved-action { width: 22px; height: 26px; padding: 0; flex-shrink: 0; background: none; border-color: transparent;
  color: var(--descrip-text, #999); }
.arisu-browser-saved-action:hover { color: inherit; }
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

function savedPaths() {
  const value = app.extensionManager?.setting?.get?.(SAVED_PATHS_SETTING);
  return Array.isArray(value)
    ? value.filter((entry) => entry && typeof entry.root === 'string' && typeof entry.path === 'string' && relativePath(entry.path))
    : [];
}

function savedLabel(location) {
  return typeof location.name === 'string' && location.name.trim() ? location.name.trim() : locationLabel(location.root, location.path);
}

function storeSavedPaths(paths) {
  return app.extensionManager?.setting?.set?.(SAVED_PATHS_SETTING, paths);
}

function rootWidget(node) {
  return node.widgets?.find((widget) => widget.name === 'root');
}

function rootValue(node) {
  return rootWidget(node)?.value ?? 'input';
}

/** Client-side migration hint only; the server is the security boundary. */
export function relativePath(path) {
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
export function viewUrl(path, max, bust = false, crop = '', root = 'input') {
  const params = new URLSearchParams({ root, path });
  if (max != null) params.set('max', String(max));
  if (crop) params.set('crop', crop);
  if (bust) params.set('t', String(Date.now()));
  return api.apiURL(`${VIEW_ROUTE}?${params}`);
}

/** The image at `url` once loaded, or `null` when the browser cannot load it. */
export async function browseResources(node, options = {}) {
  browserDialogs.get(node)?.close();
  const isCurrent = () => (!options.isCurrent || options.isCurrent()) && !options.signal?.aborted && dialog.open;
  let listing = { root: rootValue(node), path: '', parent: null, dirs: [], files: [], ancestors: [] };
  let loaded = false;
  let navigation = 0;
  let editor = null;
  let saving = false;
  const roots = new Map();
  const tree = new Map();
  // Read-only: the tree, up, the roots, saved locations and thumbnails are the only ways to move.
  const pathField = el('output', { className: 'arisu-browser-path' });
  const upButton = el('button', { textContent: '↑ up', onclick: () => navigate(listing.root, listing.parent) });
  const filterField = el('input', {
    type: 'search',
    placeholder: options.mixed ? 'filter resources' : 'filter images',
    oninput: () => renderGrid(false),
  });
  const saveButton = el('button', { textContent: '+ save', onclick: () => editPath({ root: listing.root, path: listing.path }, false) });
  const savedList = el('div', { className: 'arisu-browser-saved-list' });
  const treeList = el('div', { className: 'arisu-browser-tree-list' });
  const treePane = el('div', { className: 'arisu-browser-tree' }, [
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
  const dialog = el(
    'dialog',
    {
      className: 'arisu-browser',
      onclose: () => {
        editor = null;
        dialog.remove();
      },
    },
    [
      el('style', { textContent: STYLE }),
      el('div', { className: 'arisu-browser-bar' }, [
        pathField,
        upButton,
        el('button', { textContent: 'input dir', onclick: () => navigate('input', '') }),
        el('button', { textContent: 'output dir', onclick: () => navigate('output', '') }),
        filterField,
        el('button', { textContent: '✕', onclick: () => dialog.close() }),
      ]),
      panes,
    ],
  );
  closeOnBackdropClick(dialog);
  browserDialogs.set(node, dialog);

  function treeNode(root, path) {
    const key = locationKey(root, path);
    if (!tree.has(key)) tree.set(key, { root, path, dirs: null, expanded: false });
    return tree.get(key);
  }

  async function fetchListing(root, path, withTree) {
    const params = new URLSearchParams({ root, path });
    if (!withTree) params.set('tree', '0');
    const response = await api.fetchApi(`${options.mixed ? '/arisu/resources/browse' : BROWSE_ROUTE}?${params}`);
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
      [el('span', { textContent: ICONS.saved }), el('span', { textContent: savedLabel(location) })],
    );
    const remove = el('button', {
      className: 'arisu-browser-saved-action',
      textContent: '✕',
      ariaLabel: `Remove ${locationLabel(root, path)}`,
      disabled: saving,
      onclick: async () => {
        if (saving || !isCurrent()) return;
        saving = true;
        renderSaved();
        try {
          await storeSavedPaths(savedPaths().filter((saved) => locationKey(saved.root, saved.path) !== locationKey(root, path)));
        } catch {
          if (isCurrent()) toast('error', 'Cannot remove saved path. Try again.');
        } finally {
          saving = false;
          if (isCurrent()) renderSaved();
        }
      },
    });
    const rename = el('button', {
      className: 'arisu-browser-saved-action',
      textContent: '✎',
      title: 'Rename',
      ariaLabel: `Rename ${locationLabel(root, path)}`,
      disabled: saving,
      onclick: () => editPath(location, true),
    });
    return el('div', { className: 'arisu-browser-saved' }, [row, rename, remove]);
  }

  function renderSaved() {
    const saved = savedPaths();
    saveButton.disabled = saving || !loaded || saved.some(({ root, path }) => current(root, path));
    savedList.replaceChildren(...saved.map(savedRow), ...(editor ? [editor.element] : []));
  }

  function editPath(location, rename) {
    if (saving || !loaded || !isCurrent() || (!rename && saveButton.disabled)) return;
    const { root, path } = location;
    const input = el('input', {
      type: 'text',
      ariaLabel: 'Saved path name',
      value: savedLabel(location),
    });
    const cancel = () => {
      editor = null;
      renderSaved();
      saveButton.focus();
    };
    const submit = el('button', {
      textContent: 'Save',
      onclick: async () => {
        if (saving || editor !== draft || !isCurrent()) return;
        const name = input.value.trim();
        const value = { root, path, ...(name ? { name } : {}) };
        const key = locationKey(root, path);
        const paths = savedPaths();
        const updated = rename
          ? paths.map((entry) => (locationKey(entry.root, entry.path) === key ? value : entry))
          : [...paths.filter((entry) => locationKey(entry.root, entry.path) !== key), value];
        saving = true;
        input.disabled = submit.disabled = true;
        renderSaved();
        try {
          await storeSavedPaths(updated);
          if (editor === draft) editor = null;
        } catch {
          if (isCurrent()) toast('error', 'Cannot save path. Try again.');
        } finally {
          saving = false;
          input.disabled = submit.disabled = false;
          if (isCurrent()) renderSaved();
        }
      },
    });
    const element = el(
      'div',
      {
        className: 'arisu-browser-name-editor',
        onkeydown: (event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            cancel();
          }
          if (event.key === 'Enter' && event.target === input) {
            event.preventDefault();
            return submit.onclick();
          }
        },
      },
      [input, submit, el('button', { textContent: 'Cancel', onclick: cancel })],
    );
    const draft = { element };
    editor = draft;
    renderSaved();
    input.focus();
  }

  function renderGrid(fresh) {
    const files = listing.files.filter((name) => name.toLowerCase().includes(filterField.value.trim().toLowerCase()));
    const cards = files.map((name, index) => {
      const path = joinPath(listing.path, name);
      const root = listing.root;
      const thumbnail =
        options.mixed && listing.kinds?.[name] !== 'image'
          ? el('span', { textContent: 'Open clip editor', ariaLabel: 'Video or audio resource' })
          : el('img', {
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
            if (!isCurrent()) return;
            dialog.close();
            return options.onPick(path, root);
          },
        },
        [thumbnail, el('span', { textContent: name })],
      );
    });
    grid.className = fresh ? 'arisu-browser-grid arisu-fresh' : 'arisu-browser-grid';
    grid.replaceChildren(
      ...(cards.length
        ? cards
        : [el('div', { className: 'arisu-browser-empty', textContent: options.mixed ? 'No resources here' : 'No images here' })]),
    );
  }

  async function navigate(root, path, withTree = true) {
    if (path == null || !isCurrent()) return;
    editor = null;
    renderSaved();
    const token = ++navigation;
    panes.ariaBusy = 'true';
    try {
      const data = await fetchListing(root, path, withTree);
      if (token !== navigation || !isCurrent()) return;
      listing = data;
      loaded = true;
      absorb(data);
      pathField.textContent = data.path || '/';
      pathField.title = `Relative to ${data.root}`;
      upButton.disabled = data.parent == null;
      renderGrid(true);
      renderSaved();
      renderTree();
    } catch (error) {
      if (token === navigation && isCurrent()) toast('error', `Cannot open directory: ${error.message}`);
    } finally {
      if (token === navigation) panes.ariaBusy = 'false';
    }
  }

  async function expand(root, path) {
    if (!isCurrent()) return;
    const state = treeNode(root, path);
    if (!state.expanded && state.dirs == null) {
      try {
        const data = await fetchListing(root, path, false);
        if (!isCurrent()) return;
        state.dirs = data.dirs;
      } catch (error) {
        if (isCurrent()) toast('error', `Cannot open directory: ${error.message}`);
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
  options.signal?.addEventListener('abort', () => dialog.close(), { once: true });
  renderSaved();
  const start = pathWidget(node)?.value?.trim() ?? '';
  if (!relativePath(start)) toast('warn', 'Reselect this image under a configured root; absolute paths are no longer accepted.');
  if (!rootsDiscovered) await discoverRoots();
  if (!isCurrent() || navigation !== 0) return;
  const preferred = app.extensionManager?.setting?.get?.(DEFAULT_ROOT_SETTING.id) ?? 'input';
  const allowed = DEFAULT_ROOT_SETTING.options.some((option) => (typeof option === 'string' ? option : option.value) === preferred);
  await navigate(start ? rootValue(node) : allowed ? preferred : 'input', relativePath(start) ? start : '');
  if (!loaded) await navigate('input', '');
}
