// Load Image (Browse)'s browse button: the listings it fetches, the path it writes into
// the widget (the value core.resolve_image_path accepts on the other side), the node
// preview, and how failures are reported.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, toastSeverities } from '../support/app.mjs';
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

/** A node with its path widget at `value`, after LiteGraph created it, so it carries the browse button. */
function makeLoadNode(value) {
  const node = makeNode({
    id: 3,
    type: 'ArisuLoadImage',
    graph: app.graph,
    widgets: [{ name: 'path', value }],
    inputs: [{ name: 'path' }],
  });
  LoadImage.prototype.onNodeCreated.call(node);
  return node;
}

function browseButton(node) {
  return node.widgets.find((widget) => widget.type === 'button');
}

function openDialog() {
  return body.children.find((element) => element.tagName === 'DIALOG');
}

function byClass(root, className) {
  return descendants(root).filter((element) => element.className === className);
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

test('browse lists a directory, entering a folder refetches, and picking a file fills the widget and previews it', async () => {
  reset();
  const node = makeLoadNode('');
  const picked = [];
  node.widgets[0].callback = (value) => picked.push(value);
  // the button is a canvas control, never written into the saved workflow
  assert.equal(browseButton(node).serialize, false);
  // opening asks for the input directory (an empty path) and renders a folder row and a thumbnail per image
  api.responses.push(jsonResponse(200, { path: '/in', parent: '/', dirs: ['clips'], files: ['a.png'] }));
  await browseButton(node).callback();
  assert.equal(api.calls.length, 1);
  assert.ok(api.calls[0].route.startsWith('/arisu/browse?'));
  assert.deepEqual(query(api.calls[0].route), { path: '' });
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  assert.deepEqual(
    byClass(dialog, 'arisu-browser-dir').map((row) => row.textContent),
    ['clips'],
  );
  const [thumbnail] = descendants(dialog).filter((element) => element.tagName === 'IMG');
  assert.ok(thumbnail.src.startsWith('/api/arisu/view?'));
  assert.deepEqual(query(thumbnail.src), { path: '/in/a.png', max: '256' });
  // entering a folder refetches with its path; the filter box narrows the listing by substring
  api.responses.push(jsonResponse(200, { path: '/in/clips', parent: '/in', dirs: [], files: ['b.png', 'c.jpg'] }));
  await byClass(dialog, 'arisu-browser-dir')[0].onclick();
  assert.deepEqual(query(api.calls[1].route), { path: '/in/clips' });
  assert.equal(byClass(dialog, 'arisu-browser-file').length, 2);
  const filter = descendants(dialog).find((element) => element.type === 'search');
  filter.value = 'C.J';
  filter.oninput();
  assert.deepEqual(
    byClass(dialog, 'arisu-browser-file').map((file) => file.title),
    ['/in/clips/c.jpg'],
  );
  // picking: the widget gets the full path and its callback, the dialog goes away, the node previews the file
  await byClass(dialog, 'arisu-browser-file')[0].onclick();
  assert.equal(node.widgets[0].value, '/in/clips/c.jpg');
  assert.deepEqual(picked, ['/in/clips/c.jpg']);
  assert.equal(dialog.open, false);
  assert.equal(openDialog(), undefined);
  assert.equal(query(node.imgs[0].src).path, '/in/clips/c.jpg');
  assert.equal(query(node.imgs[0].src).max, '1024');
  assert.equal(node.imageIndex, 0);
  assert.equal(node.previewMediaType, 'image');
  assert.deepEqual(toastSeverities(), []);
  // the node previews now, so the frontend's menu hook would offer its mask editor, which cannot load a path: that entry goes
  const options = [];
  const extra = LoadImage.prototype.getExtraMenuOptions.call(node, {}, options);
  assert.deepEqual(
    options.map((option) => option?.content ?? null),
    ['Open Image', null, 'Bypass'],
  );
  assert.deepEqual(extra, []);
  // a loaded workflow shows its saved file again; an empty path shows nothing
  const saved = makeLoadNode('/in/a.png');
  await LoadImage.prototype.onConfigure.call(saved);
  assert.equal(query(saved.imgs[0].src).path, '/in/a.png');
  const blank = makeLoadNode('');
  await LoadImage.prototype.onConfigure.call(blank);
  assert.equal(blank.imgs, undefined);
});

test('a failed listing keeps the dialog open with an error, and a failed preview leaves no image on the node', async () => {
  reset();
  const node = makeLoadNode('');
  // the route refuses: an error, and an empty dialog that stays for another try
  api.responses.push(jsonResponse(500, { error: 'permission denied' }));
  await browseButton(node).callback();
  assert.deepEqual(toastSeverities(), ['error']);
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  assert.equal(byClass(dialog, 'arisu-browser-file').length, 0);
  // the request itself fails (server unreachable) for a path typed into the field: same outcome
  api.responses.push(new Error('offline'));
  const pathField = byClass(dialog, 'arisu-browser-path')[0];
  pathField.value = '/somewhere';
  await pathField.onkeydown({ key: 'Enter' });
  assert.deepEqual(query(api.calls[1].route), { path: '/somewhere' });
  assert.deepEqual(toastSeverities(), ['error', 'error']);
  dialog.close();
  // a saved path opens where the file lives; when that directory is gone the dialog falls back to the input directory
  resetApi();
  const saved = makeLoadNode('/gone/broken.png');
  api.responses.push(
    jsonResponse(404, { error: 'no such directory' }),
    jsonResponse(200, { path: '/in', parent: '/', dirs: [], files: ['broken.png'] }),
  );
  await browseButton(saved).callback();
  assert.deepEqual(
    api.calls.map((call) => query(call.route)),
    [{ path: '/gone/broken.png' }, { path: '' }],
  );
  // a preview that fails to load leaves no stale image on the node and warns
  await byClass(openDialog(), 'arisu-browser-file')[0].onclick();
  assert.equal(saved.widgets[0].value, '/in/broken.png');
  assert.equal(saved.imgs, undefined);
  assert.equal(toastSeverities().at(-1), 'warn');
});
