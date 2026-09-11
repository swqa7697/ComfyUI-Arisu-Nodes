// Load Image (Browse)'s browse button: the listings it fetches, the tree it builds from them, the
// saved directories it keeps in the user's settings, the path it writes into the widget (the value
// core.resolve_image_path accepts on the other side), the node preview, and how failures are
// reported. The crop button has its own file.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, settings, toastSeverities } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/load_image.js';

const LoadImage = { prototype: {} };
// the frontend's own menu hook, installed on every node class before extensions run: it fills `options`
// in place (null is a separator) and returns a second list LiteGraph prepends
LoadImage.prototype.getExtraMenuOptions = (_canvas, options) => {
  options.push({ content: 'Open Image' }, { content: 'Open in MaskEditor | Image Canvas' }, null, { content: 'Bypass' });
  return [];
};
extensionNamed('Arisu.Common.LoadImage').beforeRegisterNodeDef(LoadImage, { name: 'ArisuLoadImage' });

const ROOTS = ['input', 'output', 'photos'].map((id) => ({ id, label: id }));
const SAVED_SETTING = 'Arisu.LoadImage.SavedLocations';

function listing(root, path, parent, dirs, files, ancestors = []) {
  return { root, path, parent, dirs, files, ancestors, roots: ROOTS };
}

/** A node with its path widget at `value` and a blank crop, after LiteGraph created it, so it carries the buttons. */
function makeLoadNode(value, root = 'input') {
  const node = makeNode({
    id: 3,
    type: 'ArisuLoadImage',
    graph: app.graph,
    widgets: [
      { name: 'path', value },
      { name: 'crop', value: '' },
      { name: 'root', value: root },
    ],
    inputs: [{ name: 'path' }, { name: 'crop' }, { name: 'root' }],
  });
  LoadImage.prototype.onNodeCreated.call(node);
  return node;
}

function browseButton(node) {
  return node.widgets.find((widget) => widget.name === 'browse');
}

function openDialog() {
  return body.children.find((element) => element.tagName === 'DIALOG');
}

function byClass(root, className) {
  return descendants(root).filter((element) => element.className === className);
}

/** The tree rows by path, with whether each one's chevron shows it expanded. */
function treeRows(dialog) {
  return byClass(dialog, 'arisu-browser-tree-node').map((node) => [node.children[1].title, node.children[0].ariaExpanded === 'true']);
}

function treeRow(dialog, path) {
  return byClass(dialog, 'arisu-browser-tree-row').find((row) => row.title === path);
}

function treeToggle(dialog, path) {
  return byClass(dialog, 'arisu-browser-tree-node').find((node) => node.children[1].title === path).children[0];
}

/** The saved rows by path, each `[row, remove button]`. */
function savedRows(dialog) {
  return byClass(dialog, 'arisu-browser-saved-list')[0].children.map((node) => node.children);
}

function saveButton(dialog) {
  return descendants(dialog).find((element) => element.tagName === 'BUTTON' && element.textContent === '+ save');
}

/** The query string of a fetched route or an image URL, as an object. */
function query(url) {
  return Object.fromEntries(new URLSearchParams(url.split('?')[1]));
}

function reset() {
  resetApp(makeGraph());
  resetApi();
  resetDom();
}

test('browse navigates configured roots, saves relative bookmarks, and selects and previews an external image', async () => {
  reset();
  const node = makeLoadNode('');
  assert.equal(browseButton(node).serialize, false);
  assert.equal(node.inputs.length, 0);
  assert.ok(node.widgets.slice(0, 3).every((widget) => widget.hidden && widget.options.hidden && widget.options.socketless));
  api.responses.push(jsonResponse(200, listing('input', '', null, ['clips'], ['a.png'])));
  await browseButton(node).callback();
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  assert.deepEqual(query(api.calls[0].route), { root: 'input', path: '' });
  assert.deepEqual(treeRows(dialog), [
    ['input:/', true],
    ['input:clips', false],
    ['output:/', false],
    ['photos:/', false],
  ]);
  assert.equal(descendants(dialog).find((element) => element.textContent === '↑ up').disabled, true);
  const thumbnail = descendants(dialog).find((element) => element.tagName === 'IMG');
  assert.deepEqual(query(thumbnail.src), { root: 'input', path: 'a.png', max: '256' });
  // Expanding another root preserves the current directory; navigating then selects that root.
  api.responses.push(jsonResponse(200, listing('photos', '', null, ['refs'], [])));
  await treeToggle(dialog, 'photos:/').onclick();
  assert.deepEqual(query(api.calls.at(-1).route), { root: 'photos', path: '', tree: '0' });
  assert.ok(treeRow(dialog, 'photos:refs'));
  assert.equal(treeRow(dialog, 'input:/').ariaCurrent, 'true');
  api.responses.push(jsonResponse(200, listing('photos', 'refs', '', [], ['b.png', 'c.jpg'])));
  await treeRow(dialog, 'photos:refs').onclick();
  assert.equal(treeRow(dialog, 'photos:refs').ariaCurrent, 'true');
  // Navigating directories alone never changes the node's selected image.
  assert.deepEqual(
    node.widgets.slice(0, 3).map((widget) => widget.value),
    ['', '', 'input'],
  );
  assert.equal(byClass(dialog, 'arisu-browser-file').length, 2);
  const filter = descendants(dialog).find((element) => element.type === 'search');
  filter.value = 'C.J';
  filter.oninput();
  assert.deepEqual(
    byClass(dialog, 'arisu-browser-file').map((file) => file.title),
    ['photos:refs/c.jpg'],
  );
  await saveButton(dialog).onclick();
  assert.deepEqual(settings[SAVED_SETTING], [{ root: 'photos', path: 'refs' }]);
  assert.equal(savedRows(dialog)[0][0].title, 'photos:refs');
  assert.equal(saveButton(dialog).disabled, true);
  // A root itself is a valid bookmark, even though its relative path is empty.
  api.responses.push(jsonResponse(200, listing('input', '', null, ['clips'], ['a.png'])));
  await treeRow(dialog, 'input:/').onclick();
  await saveButton(dialog).onclick();
  assert.deepEqual(settings[SAVED_SETTING][1], { root: 'input', path: '' });
  api.responses.push(jsonResponse(200, listing('photos', 'refs', '', [], ['b.png', 'c.jpg'], [{ path: '', dirs: ['refs'] }])));
  await savedRows(dialog)[0][0].onclick();
  assert.deepEqual(query(api.calls.at(-1).route), { root: 'photos', path: 'refs' });
  await savedRows(dialog)[1][1].onclick();
  assert.deepEqual(settings[SAVED_SETTING], [{ root: 'photos', path: 'refs' }]);
  descendants(dialog)
    .find((element) => element.textContent === 'collapse')
    .onclick();
  assert.deepEqual(treeRows(dialog), [
    ['input:/', false],
    ['output:/', false],
    ['photos:/', true],
    ['photos:refs', true],
  ]);
  dialog.onpointerdown({ target: byClass(dialog, 'arisu-browser-path')[0] });
  dialog.onclick({ target: dialog });
  assert.equal(dialog.open, true);
  node.widgets[1].value = '1,1,2,2';
  await byClass(dialog, 'arisu-browser-file')[0].onclick();
  assert.equal(node.widgets[0].value, 'refs/c.jpg');
  assert.equal(node.widgets[2].value, 'photos');
  assert.equal(node.widgets[1].value, '');
  assert.equal(openDialog(), undefined);
  assert.equal(query(node.imgs[0].src).root, 'photos');
  assert.equal(query(node.imgs[0].src).path, 'refs/c.jpg');
  assert.equal(query(node.imgs[0].src).crop, undefined);
  const options = [];
  assert.deepEqual(LoadImage.prototype.getExtraMenuOptions.call(node, {}, options), []);
  assert.deepEqual(
    options.map((option) => option?.content ?? null),
    ['Open Image', null, 'Bypass'],
  );
  // Hidden values remain serialized in their original order and restore with no sockets.
  const values = node.widgets.filter((widget) => widget.serialize !== false).map((widget) => widget.value);
  assert.deepEqual(values, ['refs/c.jpg', '', 'photos']);
  const restored = makeLoadNode(values[0], values[2]);
  restored.widgets[1].value = '1,1,2,2';
  await LoadImage.prototype.onConfigure.call(restored);
  assert.deepEqual(restored.inputs, []);
  assert.equal(query(restored.imgs[0].src).crop, '1,1,2,2');
  // Reloading a workflow preserves root selection and all formats arrive as raster pixels.
  const saved = makeLoadNode('scan.tif', 'photos');
  await LoadImage.prototype.onConfigure.call(saved);
  assert.equal(query(saved.imgs[0].src).root, 'photos');
  assert.equal(query(saved.imgs[0].src).max, undefined);
  assert.deepEqual(toastSeverities(), []);
});

test('legacy paths require reselection, invalid bookmarks stay inert, and failed requests preserve the browser', async () => {
  reset();
  // Restored path/root wires must not silently fall back to stale stored selections.
  for (const names of [['path'], ['root'], ['path', 'root']]) {
    const linked = makeLoadNode('stale.png', 'photos');
    linked.widgets[1].value = '1,1,2,2';
    linked.imgs = [{}];
    names.forEach((name, index) => {
      linked.addInput(name, 'STRING', { link: index });
    });
    // Include the modern widget-associated socket and the legacy name-only shape.
    if (names.includes('path')) linked.inputs[0].widget = { name: names[0] };
    await LoadImage.prototype.onConfigure.call(linked);
    assert.deepEqual(linked.inputs, []);
    assert.deepEqual(
      linked.widgets.slice(0, 3).map((widget) => widget.value),
      ['', '', 'input'],
    );
    assert.equal(linked.imgs, undefined);
    assert.equal(toastSeverities().length, 1);
    assert.equal(toastSeverities()[0], 'warn');
    await LoadImage.prototype.onConfigure.call(linked);
    assert.equal(toastSeverities().length, 1);
    reset();
  }
  settings['Arisu.LoadImage.SavedPaths'] = ['/mnt/old'];
  settings[SAVED_SETTING] = ['/mnt/old', { root: 'photos', path: '../escape' }, { root: 'photos', path: 'refs' }];
  const node = makeLoadNode('/old/private/a.png');
  node.imgs = [{}];
  await LoadImage.prototype.onConfigure.call(node);
  assert.equal(node.imgs, undefined);
  assert.deepEqual(toastSeverities(), ['warn']);
  api.responses.push(jsonResponse(200, listing('input', '', null, [], [])));
  await browseButton(node).callback();
  let dialog = openDialog();
  assert.deepEqual(query(api.calls[0].route), { root: 'input', path: '' });
  assert.equal(savedRows(dialog).length, 1);
  assert.equal(savedRows(dialog)[0][0].title, 'photos:refs');
  // Typed absolute paths are refused by the server; no ad-hoc roots are created.
  const field = byClass(dialog, 'arisu-browser-path')[0];
  field.value = '/outside';
  api.responses.push(jsonResponse(400, { error: 'path must be relative' }));
  await field.onkeydown({ key: 'Enter' });
  assert.equal(dialog.open, true);
  assert.deepEqual(treeRows(dialog), [
    ['input:/', true],
    ['output:/', false],
    ['photos:/', false],
  ]);
  assert.equal(toastSeverities().at(-1), 'error');
  api.responses.push(new Error('offline'));
  await field.onkeydown({ key: 'Enter' });
  assert.equal(toastSeverities().at(-1), 'error');
  dialog.onpointerdown({ target: dialog });
  dialog.onclick({ target: dialog });
  assert.equal(dialog.open, false);
  // Removed roots fail closed and the browser recovers at input without changing the workflow.
  resetApi();
  const removed = makeLoadNode('broken.png', 'removed');
  api.responses.push(jsonResponse(400, { error: 'unknown root' }), jsonResponse(200, listing('input', '', null, [], ['broken.png'])));
  await browseButton(removed).callback();
  assert.deepEqual(
    api.calls.map((call) => query(call.route)),
    [
      { root: 'removed', path: 'broken.png' },
      { root: 'input', path: '' },
    ],
  );
  dialog = openDialog();
  await byClass(dialog, 'arisu-browser-file')[0].onclick();
  assert.equal(removed.widgets[2].value, 'input');
  assert.equal(removed.imgs, undefined);
  assert.equal(toastSeverities().at(-1), 'warn');
});
