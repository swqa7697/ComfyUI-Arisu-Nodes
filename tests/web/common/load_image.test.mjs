// Load Image (Browse)'s browse button: the listings it fetches, the tree it builds from them, the
// saved directories it keeps in the user's settings, the path it writes into the widget (the value
// core.resolve_image_path accepts on the other side), the node preview, and how failures are
// reported. The crop button has its own file.
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

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
const receivedLoads = [];

/** The frontend loads a serialized graph, configures nodes synchronously, then activates its workflow. */
async function configureWorkflow(data, workflow) {
  receivedLoads.push(data);
  if (data.fail) throw new Error('load failed');
  app.graph = app.rootGraph = makeGraph();
  const nodes = [];
  const previews = [];
  function configure(graphData, graph) {
    for (const saved of graphData.nodes ?? []) {
      if (saved.type !== 'ArisuLoadImage') continue;
      const node = makeLoadNode(saved.widgets_values[0], saved.widgets_values[2]);
      node.graph = graph;
      node.widgets[1].value = saved.widgets_values[1];
      app.configuringGraph = true;
      try {
        previews.push(LoadImage.prototype.onConfigure.call(node));
      } finally {
        app.configuringGraph = false;
      }
      nodes.push(node);
    }
    for (const saved of graphData.definitions?.subgraphs ?? []) {
      const subgraph = makeGraph(saved.id);
      graph.subgraphs ??= new Map();
      graph.subgraphs.set(saved.id, subgraph);
      configure(saved, subgraph);
    }
  }
  configure(data, app.graph);
  await Promise.all(previews);
  app.extensionManager.workflow.activeWorkflow = typeof workflow === 'object' && workflow ? workflow : { isPersisted: false };
  return nodes;
}
app.loadGraphData = (data, _clean, _restoreView, workflow) => configureWorkflow(data, workflow);
app.loadApiJson = (data) =>
  configureWorkflow({
    nodes: Object.values(data).map(({ class_type, inputs }) => ({
      type: class_type,
      widgets_values: [inputs.path, inputs.crop, inputs.root],
    })),
  });
extensionNamed('Arisu.Common.LoadImage').init();

function serialized(path = 'private.png', crop = '1,1,2,2', root = 'photos') {
  return { type: 'ArisuLoadImage', id: 3, widgets_values: [path, crop, root] };
}

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

function filenameRow(node) {
  return node.widgets.find((widget) => widget.name === 'filename');
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

/** The saved rows by path, each `[row, rename button, remove button]`. */
function savedRows(dialog) {
  return byClass(dialog, 'arisu-browser-saved').map((node) => node.children);
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
  receivedLoads.length = 0;
}

// Each scenario gets the frontend setup lifecycle, including when selected by name.
beforeEach(async () => {
  resetApi();
  api.responses.push(jsonResponse(200, { roots: ROOTS }));
  await extensionNamed('Arisu.Common.LoadImage').setup();
});

test('browse navigates configured roots, saves relative bookmarks, and selects and previews an external image', async () => {
  reset();
  const extension = extensionNamed('Arisu.Common.LoadImage');
  const defaultSetting = extension.settings.find(({ id }) => id === 'Arisu.LoadImage.DefaultRoot');
  // Discovery failure does not prevent browsing built-in roots, and Browse retries it.
  api.responses.push(new Error('offline'));
  await extension.setup();
  api.responses.push(new Error('offline'), jsonResponse(200, listing('input', '', null, [], [])));
  await browseButton(makeLoadNode('')).callback();
  assert.equal(treeRow(openDialog(), 'input:/').ariaCurrent, 'true');
  openDialog().close();
  reset();
  // The settings choices are populated before any successful Browse, without saved bookmarks.
  settings[SAVED_SETTING] = [{ root: 'photos', path: 'refs', name: 'Bookmark only' }];
  api.responses.push(jsonResponse(200, { roots: ROOTS }));
  await extension.setup();
  assert.deepEqual(
    defaultSetting.options,
    ROOTS.map(({ id, label }) => ({ value: id, text: label })),
  );
  const empty = makeLoadNode('');
  for (const root of ['output', 'photos', 'input', 'removed', 'Bookmark only']) {
    settings[defaultSetting.id] = root;
    const expected = ROOTS.some(({ id }) => id === root) ? root : 'input';
    api.responses.push(jsonResponse(200, listing(expected, '', null, [], [])));
    await browseButton(empty).callback();
    assert.equal(treeRow(openDialog(), `${expected}:/`).ariaCurrent, 'true');
    assert.deepEqual(
      empty.widgets.slice(0, 3).map(({ value }) => value),
      ['', '', 'input'],
    );
    openDialog().close();
  }
  // An inaccessible configured default reports the error and falls back to input.
  settings[defaultSetting.id] = 'photos';
  api.responses.push(jsonResponse(403, { error: 'unavailable' }), jsonResponse(200, listing('input', '', null, [], [])));
  await browseButton(empty).callback();
  assert.equal(treeRow(openDialog(), 'input:/').ariaCurrent, 'true');
  assert.equal(toastSeverities().at(-1), 'error');
  openDialog().close();
  // A selected image wins over the default; opening Browse preserves its selection.
  settings[defaultSetting.id] = 'output';
  const selected = makeLoadNode('refs/a.png', 'photos');
  api.responses.push(jsonResponse(200, listing('photos', 'refs', '', [], ['a.png'])));
  await browseButton(selected).callback();
  assert.deepEqual(query(api.calls.at(-1).route), { root: 'photos', path: 'refs/a.png' });
  assert.equal(selected.widgets[0].value, 'refs/a.png');
  openDialog().close();
  reset();
  const node = makeLoadNode('');
  assert.equal(browseButton(node).serialize, false);
  assert.equal(filenameRow(node).serialize, false);
  assert.equal(filenameRow(node).options.socketless, true);
  assert.equal(filenameRow(node).element.textContent, 'No image selected');
  // ComfyUI subtracts the DOM widget's margin (10px by default) from both sides of its allocated height.
  const filename = filenameRow(node);
  const contentHeight = filename.options.getMinHeight() - 2 * (filename.options.margin ?? 10);
  const lineHeight = Number.parseFloat(filename.element.style.match(/line-height:\s*([\d.]+)px/)[1]);
  assert.ok(contentHeight >= lineHeight, 'the filename row must fit a full line without clipping');
  assert.ok(node.widgets.indexOf(filenameRow(node)) < node.widgets.indexOf(browseButton(node)));
  assert.equal(node.inputs.length, 0);
  assert.ok(node.widgets.slice(0, 3).every((widget) => widget.hidden && widget.options.hidden && widget.options.socketless));
  api.responses.push(jsonResponse(200, listing('input', '', null, ['clips'], ['a.png'])));
  await browseButton(node).callback();
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  const toolbar = byClass(dialog, 'arisu-browser-bar')[0];
  for (const label of ['input dir', 'output dir']) {
    const shortcut = toolbar.children.find((element) => element.textContent === label);
    const root = label.split(' ')[0];
    api.responses.push(jsonResponse(200, listing(root, '', null, root === 'input' ? ['clips'] : [], root === 'input' ? ['a.png'] : [])));
    await shortcut.onclick();
    assert.equal(treeRow(dialog, `${root}:/`).ariaCurrent, 'true');
  }
  api.responses.push(jsonResponse(200, listing('input', '', null, ['clips'], ['a.png'])));
  await toolbar.children.find((element) => element.textContent === 'input dir').onclick();
  descendants(dialog)
    .find((element) => element.textContent === 'collapse')
    .onclick();
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
  let editor = byClass(dialog, 'arisu-browser-name-editor')[0];
  editor.children[0].value = '  Reference images  ';
  await editor.onkeydown({ key: 'Enter', target: editor.children[0], preventDefault() {} });
  assert.deepEqual(settings[SAVED_SETTING], [{ root: 'photos', path: 'refs', name: 'Reference images' }]);
  assert.equal(savedRows(dialog)[0][0].children[1].textContent, 'Reference images');
  await savedRows(dialog)[0][1].onclick();
  editor = byClass(dialog, 'arisu-browser-name-editor')[0];
  editor.children[0].value = 'discard';
  // Enter on Cancel must keep the button's native activation, never submit the name.
  await editor.onkeydown({
    key: 'Enter',
    target: editor.children[2],
    preventDefault() {
      assert.fail('cancel activation intercepted');
    },
  });
  assert.equal(settings[SAVED_SETTING][0].name, 'Reference images');
  editor.onkeydown({ key: 'Escape', preventDefault() {}, stopPropagation() {} });
  assert.equal(dialog.open, true);
  assert.equal(byClass(dialog, 'arisu-browser-name-editor').length, 0);
  assert.equal(settings[SAVED_SETTING][0].name, 'Reference images');
  // Names are text, even when they look like markup; failed writes retain the draft for retry.
  await savedRows(dialog)[0][1].onclick();
  editor = byClass(dialog, 'arisu-browser-name-editor')[0];
  editor.children[0].value = '<b>References</b>';
  const store = app.extensionManager.setting.set;
  app.extensionManager.setting.set = async () => {
    throw new Error('offline');
  };
  try {
    await editor.children[1].onclick();
    assert.equal(byClass(dialog, 'arisu-browser-name-editor')[0], editor);
    assert.equal(editor.children[0].value, '<b>References</b>');
    assert.equal(toastSeverities().at(-1), 'error');
  } finally {
    app.extensionManager.setting.set = store;
  }
  await editor.children[1].onclick();
  assert.equal(savedRows(dialog)[0][0].children[1].textContent, '<b>References</b>');
  assert.deepEqual(savedRows(dialog)[0][0].children[1].children, []);
  await savedRows(dialog)[0][1].onclick();
  editor = byClass(dialog, 'arisu-browser-name-editor')[0];
  editor.children[0].value = '   ';
  await editor.children[1].onclick();
  assert.deepEqual(settings[SAVED_SETTING], [{ root: 'photos', path: 'refs' }]);
  assert.equal(savedRows(dialog)[0][0].children[1].textContent, 'photos:refs');
  assert.equal(savedRows(dialog)[0][0].title, 'photos:refs');
  assert.equal(saveButton(dialog).disabled, true);
  // A root itself is a valid bookmark, even though its relative path is empty.
  await savedRows(dialog)[0][1].onclick();
  const staleEditor = byClass(dialog, 'arisu-browser-name-editor')[0];
  staleEditor.children[0].value = 'discard on navigation';
  api.responses.push(jsonResponse(200, listing('input', '', null, ['clips'], ['a.png'])));
  await treeRow(dialog, 'input:/').onclick();
  assert.equal(byClass(dialog, 'arisu-browser-name-editor').length, 0);
  await staleEditor.children[1].onclick();
  assert.equal(settings[SAVED_SETTING][0].name, undefined);
  await saveButton(dialog).onclick();
  editor = byClass(dialog, 'arisu-browser-name-editor')[0];
  editor.children[0].value = '';
  let finishSave;
  app.extensionManager.setting.set = async (id, value) => {
    await new Promise((resolve) => {
      finishSave = resolve;
    });
    await store(id, value);
  };
  try {
    const pending = editor.children[1].onclick();
    assert.equal(editor.children[1].disabled, true);
    await editor.children[1].onclick();
    finishSave();
    await pending;
  } finally {
    app.extensionManager.setting.set = store;
  }
  assert.deepEqual(settings[SAVED_SETTING][1], { root: 'input', path: '' });
  api.responses.push(jsonResponse(200, listing('photos', 'refs', '', [], ['b.png', 'c.jpg'], [{ path: '', dirs: ['refs'] }])));
  await savedRows(dialog)[0][0].onclick();
  assert.deepEqual(query(api.calls.at(-1).route), { root: 'photos', path: 'refs' });
  assert.equal(byClass(dialog, 'arisu-browser-path')[0].textContent, 'refs');
  await savedRows(dialog)[1][2].onclick();
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
  assert.equal(filenameRow(node).element.textContent, 'c.jpg');
  assert.equal(filenameRow(node).element.title, 'c.jpg');
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
  const [restored] = await app.loadGraphData({ nodes: [serialized(values[0], '1,1,2,2', values[2])] }, true, true, { isPersisted: true });
  assert.deepEqual(restored.inputs, []);
  assert.equal(query(restored.imgs[0].src).crop, '1,1,2,2');
  // Reopening a saved workflow preserves root selection and previews the original file, never a resized one.
  const [saved] = await app.loadGraphData({ nodes: [serialized('scan.avif', '', 'photos')] }, true, true, { isPersisted: true });
  assert.equal(query(saved.imgs[0].src).root, 'photos');
  assert.equal(query(saved.imgs[0].src).max, undefined);
  // Renamed bookmarks survive dialog reopening; an abandoned draft cannot save after close.
  api.responses.push(jsonResponse(200, listing('photos', 'refs', '', [], [])));
  await browseButton(saved).callback();
  const reopened = openDialog();
  await savedRows(reopened)[0][1].onclick();
  editor = byClass(reopened, 'arisu-browser-name-editor')[0];
  editor.children[0].value = 'My references';
  await editor.children[1].onclick();
  reopened.close();
  api.responses.push(jsonResponse(200, listing('photos', 'refs', '', [], [])));
  await browseButton(saved).callback();
  assert.equal(savedRows(openDialog())[0][0].children[1].textContent, 'My references');
  await savedRows(openDialog())[0][1].onclick();
  editor = byClass(openDialog(), 'arisu-browser-name-editor')[0];
  editor.children[0].value = 'discard on close';
  openDialog().close();
  await editor.children[1].onclick();
  assert.equal(settings[SAVED_SETTING][0].name, 'My references');
  assert.deepEqual(toastSeverities(), ['error']);
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
    assert.deepEqual(toastSeverities(), []);
    assert.equal(filenameRow(linked).element.textContent, 'No image selected');
    await LoadImage.prototype.onConfigure.call(linked);
    assert.deepEqual(toastSeverities(), []);
    reset();
  }
  settings['Arisu.LoadImage.SavedPaths'] = ['/mnt/old'];
  settings[SAVED_SETTING] = ['/mnt/old', { root: 'photos', path: '../escape' }, { root: 'photos', path: 'refs' }];
  const node = makeLoadNode('/old/private/a.png');
  node.imgs = [{}];
  await LoadImage.prototype.onConfigure.call(node);
  assert.equal(node.imgs, undefined);
  assert.deepEqual(toastSeverities(), []);
  api.responses.push(jsonResponse(200, listing('input', '', null, [], [])));
  await browseButton(node).callback();
  let dialog = openDialog();
  assert.deepEqual(query(api.calls[0].route), { root: 'input', path: '' });
  assert.equal(savedRows(dialog).length, 1);
  assert.equal(savedRows(dialog)[0][0].title, 'photos:refs');
  // The path display is read-only; a refused or failed navigation from the tree leaves the dialog where it was.
  const field = byClass(dialog, 'arisu-browser-path')[0];
  assert.equal(field.tagName, 'OUTPUT');
  assert.equal(field.onkeydown, undefined);
  assert.equal(field.textContent, '/');
  const outputRow = descendants(dialog).find((element) => element.title === 'output:/');
  api.responses.push(jsonResponse(400, { error: 'path must be relative' }));
  await outputRow.onclick();
  assert.equal(dialog.open, true);
  assert.deepEqual(treeRows(dialog), [
    ['input:/', true],
    ['output:/', false],
    ['photos:/', false],
  ]);
  assert.equal(toastSeverities().at(-1), 'error');
  api.responses.push(new Error('offline'));
  await outputRow.onclick();
  assert.equal(toastSeverities().at(-1), 'error');
  assert.equal(field.textContent, '/');
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
  assert.equal(filenameRow(removed).element.textContent, 'broken.png');
  assert.equal(toastSeverities().at(-1), 'warn');
});

test('workflow provenance preserves reopening and undo, while imports, paste and stale async work require reselection', async () => {
  reset();
  const savedWorkflow = { isPersisted: true, path: 'mine.json' };
  const source = {
    id: 'same-workflow-id',
    nodes: [serialized()],
    definitions: { subgraphs: [{ id: 'nested', nodes: [serialized('nested.png')] }] },
  };
  // Saved reopening, tab switching, refresh and undo/redo all carry workflow objects.
  for (const clean of [true, false, true]) {
    const nodes = await app.loadGraphData(source, clean, true, savedWorkflow);
    assert.deepEqual(
      nodes.map((node) => node.widgets[0].value),
      ['private.png', 'nested.png'],
    );
    assert.ok(nodes.every((node) => node.imgs?.length === 1));
    assert.equal(nodes[0].widgets[1].value, '1,1,2,2');
  }
  // An unsaved tab is recognized by its frontend-owned object after it has been active.
  const existingTab = { isPersisted: false };
  app.extensionManager.workflow.activeWorkflow = existingTab;
  await app.loadGraphData(source, true, true, savedWorkflow);
  const [tab] = await app.loadGraphData(source, true, true, existingTab);
  assert.equal(tab.widgets[0].value, 'private.png');
  assert.deepEqual(toastSeverities(), []);

  // Imported filenames/IDs (even an existing name), unknown objects and new duplicates grant no restoration context.
  for (const identity of ['mine.json', 'image.png', null, { isPersisted: false, path: 'mine.json' }]) {
    const nodes = await app.loadGraphData(source, true, true, identity);
    assert.ok(nodes.every((node) => node.widgets[0].value === '' && node.widgets[1].value === '' && node.widgets[2].value === 'input'));
    assert.ok(nodes.every((node) => node.imgs === undefined));
    assert.equal(receivedLoads.at(-1).definitions.subgraphs[0].nodes[0].widgets_values[0], '');
  }
  assert.deepEqual(toastSeverities(), []);
  assert.equal(source.nodes[0].widgets_values[0], 'private.png');
  const longName = `${'image'.repeat(50)}<sample>.png`;
  const [longNode] = await app.loadGraphData({ nodes: [serialized(`refs/${longName}`)] }, true, true, savedWorkflow);
  assert.equal(filenameRow(longNode).element.textContent, longName);
  assert.equal(filenameRow(longNode).element.title, longName);
  longNode.addInput('path', 'STRING', { link: 9 });
  await LoadImage.prototype.onConfigure.call(longNode);
  assert.equal(longNode.inputs.length, 0);
  assert.equal(filenameRow(longNode).element.textContent, 'No image selected');
  assert.equal(filenameRow(longNode).element.title, '');
  assert.deepEqual(toastSeverities(), []);
  // Concurrent requests cannot borrow a saved workflow's restoration context.
  const [retained, imported] = await Promise.all([
    app.loadGraphData(source, true, true, savedWorkflow),
    app.loadGraphData(source, true, true, 'mine.json'),
  ]);
  assert.equal(retained[0].widgets[0].value, 'private.png');
  assert.equal(imported[0].widgets[0].value, '');
  assert.equal(imported[0].imgs, undefined);

  // API-format imports also clear literal or linked inputs before the frontend builds any nodes.
  const apiSource = { 3: { class_type: 'ArisuLoadImage', inputs: { path: ['4', 0], crop: '1,1,2,2', root: 'photos' } } };
  const [apiNode] = await app.loadApiJson(apiSource);
  assert.deepEqual(
    apiNode.widgets.slice(0, 3).map((widget) => widget.value),
    ['', '', 'input'],
  );
  assert.equal(apiNode.imgs, undefined);
  assert.deepEqual(apiSource[3].inputs.path, ['4', 0]);
  // A failed load must not leave restoration permission active for a later paste.
  await assert.rejects(app.loadGraphData({ fail: true }, true, true, savedWorkflow), /load failed/);
  const copied = makeLoadNode('private.png', 'photos');
  copied.widgets[1].value = '1,1,2,2';
  copied.imgs = [{}];
  await LoadImage.prototype.onConfigure.call(copied);
  assert.deepEqual(
    copied.widgets.slice(0, 3).map((widget) => widget.value),
    ['', '', 'input'],
  );
  assert.equal(copied.imgs, undefined);
  const [reopened] = await app.loadGraphData(source, true, true, savedWorkflow);
  assert.equal(reopened.widgets[0].value, 'private.png');

  // Reset invalidates an already-open Browse dialog, including a retained click handler.
  api.responses.push(jsonResponse(200, listing('photos', '', null, [], ['old.png'])));
  await browseButton(reopened).callback();
  const oldDialog = openDialog();
  const click = byClass(oldDialog, 'arisu-browser-file')[0].onclick;
  await LoadImage.prototype.onConfigure.call(reopened);
  await click();
  assert.equal(oldDialog.open, false);
  assert.equal(reopened.widgets[0].value, '');
  assert.equal(reopened.imgs, undefined);
  // A late listing response must not start thumbnail loads or restore the previous selection.
  let answer;
  api.responses.push(
    () =>
      new Promise((resolve) => {
        answer = resolve;
      }),
  );
  const browsing = browseButton(reopened).callback();
  await LoadImage.prototype.onConfigure.call(reopened);
  answer(jsonResponse(200, listing('photos', '', null, [], ['old.png'])));
  await browsing;
  assert.equal(openDialog(), undefined);
  assert.equal(reopened.widgets[0].value, '');

  // A preview already loading at reset cannot return pixels or start another request.
  const OriginalImage = globalThis.Image;
  const pending = [];
  globalThis.Image = class {
    set src(url) {
      this.url = url;
      pending.push(this);
    }
  };
  try {
    const loading = app.loadGraphData({ nodes: [serialized()] }, true, true, savedWorkflow);
    await new Promise((resolve) => setImmediate(resolve));
    const node = app.graph.nodes[0];
    await LoadImage.prototype.onConfigure.call(node);
    pending[0].onerror();
    await loading;
    assert.equal(pending.length, 1);
    assert.equal(node.imgs, undefined);
    assert.equal(node.widgets[0].value, '');
    const before = pending.length;
    await app.loadGraphData(source, true, true, 'mine.json');
    assert.equal(pending.length, before);
  } finally {
    globalThis.Image = OriginalImage;
  }
});
