// Browse and crop images beneath server-configured roots. Paths and bookmarks are relative; previews
// stream the original file, as Load Image's do, and only the browser's thumbnails are resized.
import { app } from '../../../../scripts/app.js';
import { cropImage } from './cropper.js';
import { el } from './dom.js';
import {
  browseResources,
  closeBrowser,
  DEFAULT_ROOT_SETTING,
  discoverRoots,
  relativePath,
  SAVED_PATHS_SETTING,
  viewUrl,
} from './resource_browser.js';
import { installSelectionGuards, preservingSelections, registerSelectionOwner } from './selection_context.js';
import { addButton, hideWidget, setWidget } from './widgets.js';

const NODE_TYPE = 'ArisuLoadImage';
const PATH_WIDGET = 'path';
const CROP_WIDGET = 'crop';
/** The context-menu entry the frontend adds to every previewing node; see beforeRegisterNodeDef for why it goes. */
const MASK_EDITOR_ENTRY = /mask ?editor/i;
/** A pending preview per node, so a load that finishes after a newer pick cannot overwrite it. */
const previewTokens = new WeakMap();
/** The aspect ratio the crop dialog last showed, per node, as `{ path, ratio }` with the file it was chosen for; dropped when the node's file changes. */
const cropRatios = new WeakMap();
const cropControllers = new WeakMap();
/** Dialog work belongs to one selection generation, never to a restored node. */
const selectionTokens = new WeakMap();
const filenameLabels = new WeakMap();

/** Keep the informational row derived from the hidden selection, never serialized. */
function updateFilename(node) {
  const label = filenameLabels.get(node);
  if (!label) return;
  const path = pathWidget(node)?.value;
  const filename = typeof path === 'string' ? path.trim().replaceAll('\\', '/').split('/').pop() : '';
  label.textContent = filename || 'No image selected';
  label.title = filename || '';
}

function addFilename(node) {
  const label = el('div', {
    style:
      'width: 100%; min-width: 0; box-sizing: border-box; padding: 0 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; color: var(--fg-color, #ddd); font-size: 13px; line-height: 24px;',
  });
  const widget = node.addDOMWidget('filename', 'arisu_filename', label, {
    serialize: false,
    socketless: true,
    margin: 0,
    getMinHeight: () => 24,
    getMaxHeight: () => 24,
  });
  widget.serialize = false;
  filenameLabels.set(node, label);
  updateFilename(node);
}

function invalidateSelection(node) {
  cropControllers.get(node)?.abort();
  cropControllers.delete(node);
  selectionTokens.set(node, {});
  previewTokens.set(node, {});
  closeBrowser(node);
}

function clearSelection(node) {
  invalidateSelection(node);
  if (pathWidget(node)) pathWidget(node).value = '';
  if (cropWidget(node)) cropWidget(node).value = '';
  if (rootWidget(node)) rootWidget(node).value = 'input';
  cropRatios.delete(node);
  node.imgs = undefined;
  node.images = undefined;
  node.imageIndex = null;
  node.previewMediaType = undefined;
  node.setDirtyCanvas(true, true);
  updateFilename(node);
}

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

/** Keep dialog-owned values socketless; linked legacy locations always require reselection. */
function hideSelection(node) {
  const linked = node.inputs?.some((input) => [PATH_WIDGET, 'root'].includes(input.widget?.name ?? input.name) && input.link != null);
  for (const widget of [pathWidget(node), cropWidget(node), rootWidget(node)]) {
    if (!widget) continue;
    widget.options ??= {};
    widget.options.socketless = true;
    hideWidget(node, widget);
  }
  if (linked) {
    clearSelection(node);
  }
}

/** The saved directories, from the user's ComfyUI settings. */
function rootWidget(node) {
  return node.widgets?.find((widget) => widget.name === 'root');
}
function rootValue(node) {
  return rootWidget(node)?.value ?? 'input';
}
function notMaskEditor(option) {
  return !MASK_EDITOR_ENTRY.test(option?.content ?? '');
}

/**
 * The view route's URL for `path`: the original file, or a WebP rendering shrunk into `max` and/or cut to
 * `crop` (the widget text) when given; `bust` defeats the browser cache for a file that may have changed.
 */
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
  updateFilename(node);
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
  // The original file, or the crop rendered at its own size: the caption shows what a run produces.
  const img = await loadImage(viewUrl(path, undefined, true, crop, root));
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
  invalidateSelection(node);
  const crop = cropWidget(node);
  if (widget.value !== path || rootValue(node) !== root) {
    if (crop) crop.value = '';
    cropRatios.delete(node);
  }
  const rootField = rootWidget(node);
  if (rootField && rootField.value !== root) setWidget(node, rootField, root);
  setWidget(node, widget, path);
  return showPreview(node);
}

/** Open the crop dialog on the picked file and keep its result in the hidden crop widget, and its ratio for next time. */
async function openCropper(node) {
  cropControllers.get(node)?.abort();
  const controller = new AbortController();
  cropControllers.set(node, controller);
  const selection = selectionTokens.get(node);
  const path = pathWidget(node)?.value?.trim();
  const crop = cropWidget(node);
  if (!path || !relativePath(path) || !crop) {
    toast('warn', 'Pick an image first.');
    return;
  }
  // The original file keeps crop coordinates aligned with node execution.
  const root = rootValue(node);
  const img = await loadImage(viewUrl(path, undefined, true, '', root));
  if (selectionTokens.get(node) !== selection) return;
  if (!img) {
    toast('warn', `Cannot crop ${path}: the browser cannot decode this file.`);
    return;
  }
  // Restored selections may differ from the remembered file; start their ratio over as free.
  const remembered = cropRatios.get(node);
  if (remembered && (remembered.path !== path || remembered.root !== root)) cropRatios.delete(node);
  const { rect, ratio } = await cropImage(
    img,
    { rect: parseCrop(crop.value), ratio: cropRatios.get(node)?.ratio ?? '' },
    { signal: controller.signal },
  );
  if (selectionTokens.get(node) !== selection) return;
  cropRatios.set(node, { root, path, ratio });
  if (!rect || pathWidget(node)?.value?.trim() !== path || rootValue(node) !== root) return;
  setWidget(node, crop, formatCrop(rect, img));
  await showPreview(node);
}

async function openBrowser(node) {
  const selection = selectionTokens.get(node);
  return browseResources(node, {
    isCurrent: () => selectionTokens.get(node) === selection,
    onPick: (path, root) => pick(node, path, root),
  });
}

registerSelectionOwner(NODE_TYPE, {
  fields: [
    ['path', 0, ''],
    ['crop', 1, ''],
    ['root', 2, 'input'],
  ],
  invalidate: invalidateSelection,
});

app.registerExtension({
  name: 'Arisu.Common.LoadImage',
  init: installSelectionGuards,
  setup: discoverRoots,
  // hidden: edited from the browse dialog, persisted per ComfyUI user by the frontend's settings store
  settings: [
    DEFAULT_ROOT_SETTING,
    { id: SAVED_PATHS_SETTING, name: 'Load Image (Browse): saved browse paths', type: 'hidden', defaultValue: [] },
  ],
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      selectionTokens.set(this, {});
      addFilename(this);
      addButton(this, 'browse', () => openBrowser(this));
      addButton(this, 'crop…', () => openCropper(this));
      hideSelection(this);
    };

    // Only a full restoration of a known workflow may reuse serialized selections.
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      invalidateSelection(this);
      hideSelection(this);
      if (!preservingSelections() || !app.configuringGraph) {
        clearSelection(this);
        return;
      }
      return showPreview(this);
    };

    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      invalidateSelection(this);
      return onRemoved?.apply(this, arguments);
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
