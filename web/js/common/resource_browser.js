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
/** A saved path's choice in the default-location setting: its location key behind this prefix, so a rename keeps the choice. */
const SAVED_OPTION_PREFIX = 'saved:';
/** The roots the server reported, or the built-in pair until discovery succeeds. */
let discoveredRoots = [
  { id: 'input', label: 'Input' },
  { id: 'output', label: 'Output' },
];
export const DEFAULT_ROOT_SETTING = {
  id: 'Arisu.LoadImage.DefaultRoot',
  category: ['Arisu Nodes', 'LoadImage'],
  name: 'Load Image (Browse): Default Location',
  type: 'combo',
  defaultValue: 'input',
  // The settings panel calls this on every render, so saved paths and their names stay current without mirroring.
  options: () => defaultOptions(),
  tooltip: 'Starting location when Browse opens without a selected image: a root or a saved path.',
};
let rootsDiscovered = false;

/** Populate settings without scanning directories. Retry a failed discovery on Browse. */
export async function discoverRoots() {
  rootsDiscovered = false;
  try {
    const response = await api.fetchApi(ROOTS_ROUTE);
    if (!response.ok) return;
    const data = await response.json();
    discoveredRoots = data.roots.map(({ id, label }) => ({ id, label }));
    rootsDiscovered = true;
  } catch {
    // Built-in choices remain usable; a later Browse retries discovery.
  }
}

const ICONS = { root: '\u{1F4BE}', folder: '\u{1F4C1}', saved: '\u{1F4CC}' };
/** Inline kind glyphs, shared with Resource Studio's reference rows: a film strip and a waveform. */
export const VIDEO_ICON =
  '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">' +
  '<rect x="1.5" y="2.5" width="9" height="7"/><path d="M3.5 2.5v7M8.5 2.5v7M1.5 4.5h2M1.5 7.5h2M8.5 4.5h2M8.5 7.5h2"/></svg>';
export const AUDIO_ICON =
  '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" aria-hidden="true">' +
  '<path d="M1.5 5.5v1M3.5 4v4M5.5 2.5v7M7.5 3.5v5M9.5 5v2"/></svg>';
const KIND_ICONS = { video: VIDEO_ICON, audio: AUDIO_ICON };

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
.arisu-browser button:enabled:active { transform: scale(0.97); }
.arisu-browser-tree button:enabled:active { transform: none; }
.arisu-browser button:disabled { opacity: 0.4; cursor: default; pointer-events: none; }
.arisu-browser :focus-visible { outline: 2px solid var(--arisu-accent); outline-offset: 2px; }
.arisu-browser input:focus-visible { outline: none; border-color: var(--arisu-accent); }
.arisu-browser-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #444); }
.arisu-browser-bar button { flex-shrink: 0; white-space: nowrap; }
.arisu-browser-bar input { min-width: 0; width: 160px; max-width: 100%; }
.arisu-browser-bar button:enabled:hover { border-color: var(--arisu-accent); }
.arisu-browser-path { flex: 1; min-width: 0; padding: 6px 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--descrip-text, #999); font-variant-numeric: tabular-nums; }
.arisu-browser-body { display: flex; flex: 1; min-height: 0; transition: opacity 150ms ease; }
.arisu-browser-body[aria-busy="true"] { opacity: 0.45; pointer-events: none; transition-delay: 200ms; }
.arisu-browser-tree, .arisu-browser-grid { overflow: auto; scrollbar-width: thin; scrollbar-color: var(--border-color, #444) transparent; }
.arisu-browser-tree { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; padding: 8px;
  border-right: 1px solid var(--border-color, #444); }
.arisu-browser-tree-head { display: flex; justify-content: space-between; align-items: center; padding: 4px 6px;
  font-size: 11px; letter-spacing: 0.06em; color: var(--descrip-text, #999); }
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
.arisu-browser-tree-row[aria-current="true"] { background: var(--comfy-input-bg, #333); border-color: var(--arisu-accent); }
.arisu-browser-grid { flex: 1; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; padding: 12px;
  align-content: start; }
.arisu-browser-file { display: flex; flex-direction: column; gap: 6px; padding: 6px; border-color: transparent; }
.arisu-browser-file:hover { transform: translateY(-2px); border-color: var(--arisu-accent);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35); }
.arisu-browser-file[aria-current="true"] { border-color: var(--arisu-accent); }
.arisu-browser-file[aria-current="true"] span, .arisu-browser-file:hover span { color: inherit; }
.arisu-browser-tile { position: relative; width: 100%; aspect-ratio: 1; display: flex; align-items: center; justify-content: center;
  box-sizing: border-box; background: #111; border-radius: 6px; color: var(--descrip-text, #999); }
.arisu-browser-tile img { width: 100%; height: 100%; object-fit: contain; border-radius: 6px; transition: opacity 250ms ease; }
.arisu-browser-tile.arisu-loading img { opacity: 0; }
.arisu-browser-tile.arisu-loading::after { content: ''; position: absolute; width: 22px; height: 22px; border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.15); border-top-color: var(--arisu-accent);
  animation: arisu-spin 800ms linear infinite; }
.arisu-browser-tile svg { width: 40%; height: 40%; }
.arisu-browser-file[data-kind="video"] .arisu-browser-tile { outline: 2px solid var(--arisu-video); outline-offset: -2px; }
.arisu-browser-file[data-kind="audio"] .arisu-browser-tile { outline: 2px solid var(--arisu-audio); outline-offset: -2px; }
.arisu-browser-file span { font-size: 12px; color: var(--descrip-text, #999); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; transition: color 150ms ease; }
.arisu-fresh .arisu-browser-file { animation: arisu-rise 160ms ease-out backwards; animation-delay: min(calc(var(--i, 0) * 10ms), 120ms); }
.arisu-browser-empty { grid-column: 1 / -1; padding: 32px 12px; text-align: center; color: var(--descrip-text, #999);
  animation: arisu-fade 200ms ease-out; }
@keyframes arisu-pop { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
@keyframes arisu-fade { from { opacity: 0; } }
@keyframes arisu-rise { from { opacity: 0; transform: translateY(4px); } }
@keyframes arisu-spin { to { transform: rotate(360deg); } }
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

function savedOption(location) {
  return { value: SAVED_OPTION_PREFIX + locationKey(location.root, location.path), text: savedLabel(location) };
}

/** The default-location choices: every root, then every saved path by name. */
function defaultOptions() {
  return [...discoveredRoots.map(({ id, label }) => ({ value: id, text: label })), ...savedPaths().map(savedOption)];
}

function defaultLocation() {
  return app.extensionManager?.setting?.get?.(DEFAULT_ROOT_SETTING.id) ?? 'input';
}

/** The saved location the default-location choice names, if it is still saved. */
function savedDefault(preferred) {
  const key = preferred.slice(SAVED_OPTION_PREFIX.length);
  return savedPaths().find((location) => locationKey(location.root, location.path) === key);
}

/** A forgotten or unreachable saved path cannot stay the default location: the choice returns to the input directory. */
async function resetDefault() {
  try {
    await app.extensionManager?.setting?.set?.(DEFAULT_ROOT_SETTING.id, 'input');
  } catch {
    // The next Browse repeats this fallback.
  }
  toast('warn', 'The default location was a saved path that is no longer available; Browse starts at the input directory again.');
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

/** The poster route's URL: the upright frame of a video at `at` seconds, shrunk into `max`, as WebP. */
export function posterUrl(root, path, at, max) {
  const params = new URLSearchParams({ root, path, at: String(at), max: String(max) });
  return api.apiURL(`/arisu/resources/poster?${params}`);
}

/**
 * Open the Browse dialog for `node` and hand the picked `(path, root)` to `options.onPick`. `options.mixed` lists
 * video and audio beside images; `options.selected(root, path)` marks the cards already chosen, by default the one
 * the node's `root` and `path` widgets name.
 */
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
  const upButton = el('button', { textContent: '↑ Up', onclick: () => navigate(listing.root, listing.parent) });
  const filterField = el('input', {
    type: 'search',
    placeholder: options.mixed ? 'Filter Resources' : 'Filter Images',
    oninput: () => renderGrid(false),
  });
  const saveButton = el('button', { textContent: '+ Save', onclick: () => editPath({ root: listing.root, path: listing.path }, false) });
  const savedList = el('div', { className: 'arisu-browser-saved-list' });
  const treeList = el('div', { className: 'arisu-browser-tree-list' });
  const treePane = el('div', { className: 'arisu-browser-tree' }, [
    el('div', { className: 'arisu-browser-tree-head' }, [el('span', { textContent: 'Saved' }), saveButton]),
    savedList,
    el('div', { className: 'arisu-browser-tree-head' }, [
      el('span', { textContent: 'Folders' }),
      el('button', { textContent: 'Collapse', onclick: collapseAll }),
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
        el('button', { textContent: 'Input Dir', onclick: () => navigate('input', '') }),
        el('button', { textContent: 'Output Dir', onclick: () => navigate('output', '') }),
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
        const key = locationKey(root, path);
        try {
          await storeSavedPaths(savedPaths().filter((saved) => locationKey(saved.root, saved.path) !== key));
          if (defaultLocation() === SAVED_OPTION_PREFIX + key) await resetDefault();
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
      ariaLabel: 'Saved Path Name',
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

  const selected = options.selected ?? ((root, path) => root === rootValue(node) && path === pathWidget(node)?.value?.trim());

  /** The current listing's tiles by kind and location: a filter keystroke moves a tile instead of loading its picture again. */
  const tiles = new Map();

  /** Turn `tile` into a square carrying the kind's glyph, where no picture exists or a poster failed. */
  function glyph(kind, tile = el('span')) {
    tile.className = 'arisu-browser-tile';
    tile.ariaLabel = `${kind === 'video' ? 'Video' : 'Audio'} resource`;
    tile.innerHTML = KIND_ICONS[kind];
    return tile;
  }

  /** An image's thumbnail or a video's poster at its first frame, behind a spinner until it loads; audio and a failed poster get a glyph. */
  function thumbnail(kind, root, path, name) {
    if (kind === 'audio') return glyph(kind);
    const tile = el('span', { className: 'arisu-browser-tile arisu-loading' });
    const settle = () => {
      tile.className = 'arisu-browser-tile';
    };
    const image = el('img', {
      loading: 'lazy',
      alt: name,
      onload: settle,
      onerror: kind === 'video' ? () => glyph(kind, tile) : settle,
      src: kind === 'video' ? posterUrl(root, path, 0, THUMBNAIL_MAX) : viewUrl(path, THUMBNAIL_MAX, false, '', root),
    });
    tile.append(image);
    return tile;
  }

  function renderGrid(fresh) {
    const files = listing.files.filter((name) => name.toLowerCase().includes(filterField.value.trim().toLowerCase()));
    const cards = files.map((name, index) => {
      const path = joinPath(listing.path, name);
      const root = listing.root;
      const kind = (options.mixed && listing.kinds?.[name]) || 'image';
      const key = `${kind}|${locationKey(root, path)}`;
      if (!tiles.has(key)) tiles.set(key, thumbnail(kind, root, path, name));
      const card = el(
        'button',
        {
          className: 'arisu-browser-file',
          style: `--i: ${index}`,
          title: locationLabel(root, path),
          ariaCurrent: selected(root, path) ? 'true' : null,
          onclick: () => {
            if (!isCurrent()) return;
            dialog.close();
            return options.onPick(path, root);
          },
        },
        [tiles.get(key), el('span', { textContent: name })],
      );
      card.dataset.kind = kind;
      return card;
    });
    grid.className = fresh ? 'arisu-browser-grid arisu-fresh' : 'arisu-browser-grid';
    grid.replaceChildren(
      ...(cards.length
        ? cards
        : [el('div', { className: 'arisu-browser-empty', textContent: options.mixed ? 'No Resources Here' : 'No Images Here' })]),
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
      tiles.clear();
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
  const preferred = defaultLocation();
  if (start) await navigate(rootValue(node), relativePath(start) ? start : '');
  else if (typeof preferred === 'string' && preferred.startsWith(SAVED_OPTION_PREFIX)) {
    const location = savedDefault(preferred);
    if (location) await navigate(location.root, location.path);
    if (!loaded && isCurrent()) await resetDefault();
  } else await navigate(discoveredRoots.some(({ id }) => id === preferred) ? preferred : 'input', '');
  if (!loaded) await navigate('input', '');
}
