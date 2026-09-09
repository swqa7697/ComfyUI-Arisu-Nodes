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

const ROOTS = [
  { label: 'Home', path: '/home/ray' },
  { label: 'nas', path: '/mnt/nas' },
];
const PLACES = { input: '/home/ray/comfy/input', output: '/home/ray/comfy/output' };
const SAVED_SETTING = 'Arisu.LoadImage.SavedPaths';

/** A route body the way `_browse` answers: the listing plus the tree roots, the places and the chain. */
function listing(path, parent, dirs, files, ancestors = []) {
  return { path, parent, dirs, files, ancestors, roots: ROOTS, places: PLACES };
}

/** A node with its path widget at `value` and a blank crop, after LiteGraph created it, so it carries the buttons. */
function makeLoadNode(value) {
  const node = makeNode({
    id: 3,
    type: 'ArisuLoadImage',
    graph: app.graph,
    widgets: [
      { name: 'path', value },
      { name: 'crop', value: '' },
    ],
    inputs: [{ name: 'path' }, { name: 'crop' }],
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

test('browse lists a directory in a tree, entering a folder refetches, and picking a file fills the widget and previews it', async () => {
  reset();
  const node = makeLoadNode('');
  const picked = [];
  node.widgets[0].callback = (value) => picked.push(value);
  // the buttons are canvas controls, never written into the saved workflow; the crop widget is there for the run,
  // but out of sight and without a socket: the crop dialog is its editor
  assert.equal(browseButton(node).serialize, false);
  assert.equal(node.widgets.find((widget) => widget.name === 'crop…').serialize, false);
  assert.equal(node.widgets[1].hidden, true);
  assert.deepEqual(
    node.inputs.map((input) => input.name),
    ['path'],
  );
  // opening asks for the input directory (an empty path) with its chain; the tree shows the roots and the chain
  // expanded down to the current directory, the grid a thumbnail per image
  api.responses.push(
    jsonResponse(
      200,
      listing(
        PLACES.input,
        '/home/ray/comfy',
        ['clips'],
        ['a.png'],
        [
          { path: '/home/ray', dirs: ['comfy', 'Pictures'] },
          { path: '/home/ray/comfy', dirs: ['input', 'output'] },
        ],
      ),
    ),
  );
  await browseButton(node).callback();
  assert.equal(api.calls.length, 1);
  assert.ok(api.calls[0].route.startsWith('/arisu/browse?'));
  assert.deepEqual(query(api.calls[0].route), { path: '' });
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  assert.deepEqual(treeRows(dialog), [
    ['/home/ray', true],
    ['/home/ray/comfy', true],
    ['/home/ray/comfy/input', true],
    ['/home/ray/comfy/input/clips', false],
    ['/home/ray/comfy/output', false],
    ['/home/ray/Pictures', false],
    ['/mnt/nas', false],
  ]);
  assert.equal(treeRow(dialog, PLACES.input).ariaCurrent, 'true');
  assert.equal(treeRow(dialog, '/mnt/nas').ariaCurrent, null);
  const [thumbnail] = descendants(dialog).filter((element) => element.tagName === 'IMG');
  assert.ok(thumbnail.src.startsWith('/api/arisu/view?'));
  assert.deepEqual(query(thumbnail.src), { path: `${PLACES.input}/a.png`, max: '256' });
  // a chevron lists a folder the tree has not seen, without the chain, and opens it in place
  api.responses.push(jsonResponse(200, listing('/mnt/nas', '/mnt', ['refs'], ['n.png'])));
  await treeToggle(dialog, '/mnt/nas').onclick();
  assert.deepEqual(query(api.calls[1].route), { path: '/mnt/nas', tree: '0' });
  assert.ok(treeRows(dialog).some(([path, expanded]) => path === '/mnt/nas' && expanded));
  assert.ok(treeRow(dialog, '/mnt/nas/refs'));
  assert.equal(treeRow(dialog, PLACES.input).ariaCurrent, 'true');
  // clicking a tree row navigates there, also without the chain; the filter box narrows the images by substring, never the folders
  api.responses.push(jsonResponse(200, listing(`${PLACES.input}/clips`, PLACES.input, [], ['b.png', 'c.jpg'])));
  await treeRow(dialog, `${PLACES.input}/clips`).onclick();
  assert.deepEqual(query(api.calls[2].route), { path: `${PLACES.input}/clips`, tree: '0' });
  assert.equal(treeRow(dialog, `${PLACES.input}/clips`).ariaCurrent, 'true');
  assert.equal(byClass(dialog, 'arisu-browser-file').length, 2);
  const filter = descendants(dialog).find((element) => element.type === 'search');
  filter.value = 'C.J';
  filter.oninput();
  assert.deepEqual(
    byClass(dialog, 'arisu-browser-file').map((file) => file.title),
    [`${PLACES.input}/clips/c.jpg`],
  );
  assert.equal(treeRows(dialog).length, 8);
  // + save pins the current directory into the user's settings and lists it above the tree, outlined while it is the
  // current one; a second save is disabled; the row navigates there; ✕ forgets it
  assert.equal(savedRows(dialog).length, 0);
  assert.equal(saveButton(dialog).disabled, false);
  await saveButton(dialog).onclick();
  assert.deepEqual(settings[SAVED_SETTING], [`${PLACES.input}/clips`]);
  assert.deepEqual(
    savedRows(dialog).map(([row]) => [row.title, row.ariaCurrent]),
    [[`${PLACES.input}/clips`, 'true']],
  );
  assert.equal(saveButton(dialog).disabled, true);
  api.responses.push(jsonResponse(200, listing(PLACES.input, '/home/ray/comfy', ['clips'], ['a.png'])));
  await treeRow(dialog, PLACES.input).onclick();
  assert.equal(savedRows(dialog)[0][0].ariaCurrent, null);
  assert.equal(saveButton(dialog).disabled, false);
  api.responses.push(jsonResponse(200, listing(`${PLACES.input}/clips`, PLACES.input, [], ['b.png', 'c.jpg'])));
  await savedRows(dialog)[0][0].onclick();
  assert.deepEqual(query(api.calls.at(-1).route), { path: `${PLACES.input}/clips` });
  await savedRows(dialog)[0][1].onclick();
  assert.deepEqual(settings[SAVED_SETTING], []);
  assert.equal(savedRows(dialog).length, 0);
  // a press in the path field that ends on the backdrop is not a backdrop click; a press there is
  dialog.onpointerdown({ target: byClass(dialog, 'arisu-browser-path')[0] });
  dialog.onclick({ target: dialog });
  assert.equal(dialog.open, true);
  // collapse folds everything but the chain to the current directory
  descendants(dialog)
    .find((element) => element.textContent === 'collapse')
    .onclick();
  assert.deepEqual(treeRows(dialog), [
    ['/home/ray', true],
    ['/home/ray/comfy', true],
    ['/home/ray/comfy/input', true],
    ['/home/ray/comfy/input/clips', true],
    ['/home/ray/comfy/output', false],
    ['/home/ray/Pictures', false],
    ['/mnt/nas', false],
  ]);
  // picking: the widget gets the full path and its callback, the dialog goes away, the node previews the file itself;
  // a crop belonged to the previous file and goes
  node.widgets[1].value = '1,1,2,2';
  await byClass(dialog, 'arisu-browser-file')[0].onclick();
  assert.equal(node.widgets[0].value, `${PLACES.input}/clips/c.jpg`);
  assert.deepEqual(picked, [`${PLACES.input}/clips/c.jpg`]);
  assert.equal(node.widgets[1].value, '');
  assert.equal(dialog.open, false);
  assert.equal(openDialog(), undefined);
  assert.equal(query(node.imgs[0].src).path, `${PLACES.input}/clips/c.jpg`);
  assert.equal(query(node.imgs[0].src).max, undefined);
  assert.equal(query(node.imgs[0].src).crop, undefined);
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
  // a loaded workflow shows its saved file again; a format the browser cannot decode falls back to a thumbnail; an empty path shows nothing
  const saved = makeLoadNode('/in/a.png');
  await LoadImage.prototype.onConfigure.call(saved);
  assert.equal(query(saved.imgs[0].src).path, '/in/a.png');
  const tiff = makeLoadNode('/in/scan.tif');
  await LoadImage.prototype.onConfigure.call(tiff);
  assert.deepEqual([query(tiff.imgs[0].src).path, query(tiff.imgs[0].src).max], ['/in/scan.tif', '1024']);
  assert.deepEqual(toastSeverities(), []);
  const blank = makeLoadNode('');
  await LoadImage.prototype.onConfigure.call(blank);
  assert.equal(blank.imgs, undefined);
});

test('a failed listing keeps the dialog open with an error, and a failed preview leaves no image on the node', async () => {
  reset();
  settings[SAVED_SETTING] = ['/mnt/nas/refs'];
  const node = makeLoadNode('');
  // the route refuses: an error, and an empty dialog that stays for another try
  api.responses.push(jsonResponse(500, { error: 'permission denied' }));
  await browseButton(node).callback();
  assert.deepEqual(toastSeverities(), ['error']);
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  assert.equal(byClass(dialog, 'arisu-browser-file').length, 0);
  // the saved directories come from the settings, so they are there even when nothing listed
  assert.deepEqual(
    savedRows(dialog).map(([row]) => row.title),
    ['/mnt/nas/refs'],
  );
  // the request itself fails (server unreachable) for a path typed into the field: same outcome
  api.responses.push(new Error('offline'));
  const pathField = byClass(dialog, 'arisu-browser-path')[0];
  pathField.value = '/somewhere';
  await pathField.onkeydown({ key: 'Enter' });
  assert.deepEqual(query(api.calls[1].route), { path: '/somewhere' });
  assert.deepEqual(toastSeverities(), ['error', 'error']);
  // a typed directory outside every root still lists, and the tree grows a root for its chain, showing only that chain at the top
  api.responses.push(
    jsonResponse(
      200,
      listing(
        '/opt/refs',
        '/opt',
        [],
        ['r.png'],
        [
          { path: '/', dirs: ['opt'] },
          { path: '/opt', dirs: ['comfy', 'refs'] },
        ],
      ),
    ),
  );
  await pathField.onkeydown({ key: 'Enter' });
  assert.deepEqual(treeRows(dialog), [
    ['/home/ray', false],
    ['/mnt/nas', false],
    ['/', true],
    ['/opt', true],
    ['/opt/comfy', false],
    ['/opt/refs', true],
  ]);
  assert.equal(treeRow(dialog, '/opt/refs').ariaCurrent, 'true');
  // a press and a click both on the backdrop close the dialog
  dialog.onpointerdown({ target: dialog });
  dialog.onclick({ target: dialog });
  assert.equal(dialog.open, false);
  // a saved path opens where the file lives; when that directory is gone the dialog falls back to the input directory
  resetApi();
  const saved = makeLoadNode('/gone/broken.png');
  api.responses.push(jsonResponse(404, { error: 'no such directory' }), jsonResponse(200, listing('/in', '/', [], ['broken.png'])));
  await browseButton(saved).callback();
  assert.deepEqual(
    api.calls.map((call) => query(call.route)),
    [{ path: '/gone/broken.png' }, { path: '' }],
  );
  // a preview that fails to load, whole and as a thumbnail, leaves no stale image on the node and warns once
  await byClass(openDialog(), 'arisu-browser-file')[0].onclick();
  assert.equal(saved.widgets[0].value, '/in/broken.png');
  assert.equal(saved.imgs, undefined);
  assert.deepEqual(toastSeverities().slice(-2), ['error', 'warn']);
});
