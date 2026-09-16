// Load Image (Browse)'s crop button: the dialog it opens on the picked file, how a drag, a ratio,
// apply and reset drive the hidden crop widget (the value core.parse_crop reads on the other side)
// and the node preview, how the ratio is remembered for the picked file and starts free on another,
// how applied choices survive workflow saves without inferring from the box, and how it declines a file it
// cannot show.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, toastSeverities } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/load_image.js';

const LoadImage = { prototype: {} };
extensionNamed('Arisu.Common.LoadImage').beforeRegisterNodeDef(LoadImage, { name: 'ArisuLoadImage' });

/** A node with its path widget at `path` and a blank crop, after LiteGraph created it, so it carries the buttons. */
function makeLoadNode(path) {
  const node = makeNode({
    id: 3,
    type: 'ArisuLoadImage',
    graph: app.graph,
    widgets: [
      { name: 'path', value: path },
      { name: 'crop', value: '' },
      { name: 'root', value: 'photos' },
    ],
    inputs: [{ name: 'path' }, { name: 'crop' }],
  });
  LoadImage.prototype.onNodeCreated.call(node);
  return node;
}

function cropWidget(node) {
  return node.widgets.find((widget) => widget.name === 'crop');
}

function cropButton(node) {
  return node.widgets.find((widget) => widget.name === 'Crop…');
}

function openDialog() {
  return body.children.find((element) => element.tagName === 'DIALOG');
}

function byClass(root, className) {
  return descendants(root).filter((element) => element.className === className);
}

function readout(dialog) {
  return byClass(dialog, 'arisu-cropper-readout')[0].textContent;
}

function ratioMenu(dialog) {
  return byClass(dialog, 'arisu-cropper-ratio')[0];
}

function chooseRatio(dialog, value) {
  const menu = ratioMenu(dialog);
  menu.value = value;
  menu.onchange();
}

function button(dialog, label) {
  return descendants(dialog).find((element) => element.tagName === 'BUTTON' && element.textContent === label);
}

/** The query string of an image URL, as an object. */
function query(url) {
  return Object.fromEntries(new URLSearchParams(url.split('?')[1]));
}

/** Let the image load and the dialog open: the load completes on a microtask after the button's own awaits. */
function settle() {
  return new Promise((resolve) => setImmediate(resolve));
}

function reset() {
  resetApp(makeGraph());
  resetApi();
  resetDom();
}

test('the crop button opens a box over the picked file; drags, a ratio, apply and reset drive the hidden crop and the preview', async () => {
  reset();
  const node = makeLoadNode('a.png');
  const written = [];
  cropWidget(node).callback = (value) => written.push(value);
  // opening loads the file itself, whole, and starts with the whole image as the box
  let applied = cropButton(node).callback();
  await settle();
  let dialog = openDialog();
  assert.equal(dialog.open, true);
  const img = descendants(dialog).find((element) => element.tagName === 'IMG');
  assert.equal(query(img.src).path, 'a.png');
  assert.equal(query(img.src).root, 'photos');
  assert.equal(query(img.src).max, undefined);
  assert.equal(readout(dialog), '800 × 600 at 0, 0');
  // the image is shown at half size: pointer positions map to image pixels through its on-screen rectangle
  img.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 300 });
  // the pointer helpers address whichever crop dialog is open; a later dialog's image keeps the fake's 1:1 mapping
  const stage = () => byClass(openDialog(), 'arisu-cropper-stage')[0];
  const press = (target, x, y) => stage().onpointerdown({ clientX: x, clientY: y, target, pointerId: 1 });
  const drag = (x, y) => stage().onpointermove({ clientX: x, clientY: y, pointerId: 1 });
  const release = () => stage().onpointerup({ pointerId: 1 });
  // a drag on the image draws a box
  press(img, 100, 75);
  drag(300, 225);
  release();
  assert.equal(readout(dialog), '400 × 300 at 200, 150');
  // a preset ratio makes the box the largest one of that ratio in the whole image, centred; the menu offers only free and presets
  assert.equal(ratioMenu(dialog).value, 'free');
  assert.deepEqual(
    ratioMenu(dialog).children.map((option) => option.value),
    ['free', '1:1', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16', '21:9'],
  );
  chooseRatio(dialog, '1:1');
  assert.equal(readout(dialog), '600 × 600 at 100, 0');
  // a press inside the ratio menu that ends on the backdrop is not a backdrop click: the dialog stays
  dialog.onpointerdown({ target: ratioMenu(dialog) });
  dialog.onclick({ target: dialog });
  assert.equal(dialog.open, true);
  // dragging the box moves it, and it stops at the image's edge
  const box = byClass(dialog, 'arisu-cropper-box')[0];
  press(box, 200, 200);
  drag(400, 200);
  release();
  assert.equal(readout(dialog), '600 × 600 at 200, 0');
  // a corner handle resizes from the opposite corner, which holds, and keeps the ratio
  press(
    descendants(dialog).find((element) => element.handle === 'nw'),
    250,
    75,
  );
  drag(300, 100);
  release();
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  // apply: the crop widget gets the box and its callback, the dialog goes, the node previews the crop at its own size
  button(dialog, 'Apply').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '400,200,400,400');
  assert.deepEqual(written, ['400,200,400,400']);
  assert.equal(dialog.open, false);
  assert.equal(openDialog(), undefined);
  assert.deepEqual([query(node.imgs[0].src).path, query(node.imgs[0].src).crop], ['a.png', '400,200,400,400']);
  assert.equal(query(node.imgs[0].src).max, undefined);
  // opening again starts from the saved box and the remembered ratio; a free box drawn by hand keeps any shape, and
  // cancel leaves the widget alone
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  assert.equal(ratioMenu(dialog).value, '1:1');
  chooseRatio(dialog, 'free');
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  press(img, 0, 0);
  drag(750, 300);
  release();
  assert.equal(readout(dialog), '750 × 300 at 0, 0');
  button(dialog, 'Cancel').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '400,200,400,400');
  assert.deepEqual(written, ['400,200,400,400']);
  // Cancel discards the draft Free choice along with the box; switching presets fits the whole image.
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  assert.equal(ratioMenu(dialog).value, '1:1');
  chooseRatio(dialog, '16:9');
  assert.equal(readout(dialog), '800 × 450 at 0, 75');
  chooseRatio(dialog, '9:16');
  assert.equal(readout(dialog), '338 × 600 at 231, 0');
  chooseRatio(dialog, '16:9');
  assert.equal(readout(dialog), '800 × 450 at 0, 75');
  // reset is the whole image at a free ratio; applied, it is stored as no crop
  button(dialog, 'Reset').onclick();
  assert.equal(readout(dialog), '800 × 600 at 0, 0');
  assert.equal(ratioMenu(dialog).value, 'free');
  button(dialog, 'Apply').onclick();
  await applied;
  assert.deepEqual(written, ['400,200,400,400', '']);
  assert.equal(query(node.imgs[0].src).crop, undefined);
  // the applied reset ratio comes back; cancel leaves both the crop and the saved ratio alone
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(ratioMenu(dialog).value, 'free');
  press(img, 0, 0);
  drag(100, 100);
  release();
  chooseRatio(dialog, '16:9');
  button(dialog, 'Cancel').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '');
  assert.deepEqual(written, ['400,200,400,400', '']);
  assert.deepEqual(toastSeverities(), []);
  // Every applied choice survives serialization into a fresh node, including rounded portrait and 21:9 crops.
  // Free over a square is explicit, and a 4:3 full-image crop still remembers its mode despite the blank crop widget.
  for (const mode of ['1:1', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16', '21:9', 'free']) {
    const original = makeLoadNode('saved.png');
    cropWidget(original).value = '10,20,300,300';
    let editing = cropButton(original).callback();
    await settle();
    chooseRatio(openDialog(), mode);
    button(openDialog(), 'Apply').onclick();
    await editing;
    const saved = JSON.parse(JSON.stringify({ crop: cropWidget(original).value, properties: original.properties }));
    if (mode === '4:3') assert.equal(saved.crop, '');
    if (mode === '9:16') assert.equal(saved.crop, '231,0,338,600');
    const restored = makeLoadNode('saved.png');
    cropWidget(restored).value = saved.crop;
    restored.properties = saved.properties;
    for (const close of ['Cancel', 'escape', 'backdrop']) {
      editing = cropButton(restored).callback();
      await settle();
      const opened = openDialog();
      assert.equal(ratioMenu(opened).value, mode, `${mode}: ${close}`);
      const before = readout(opened);
      chooseRatio(opened, mode === '1:1' ? '16:9' : '1:1');
      button(opened, 'Reset').onclick();
      if (close === 'Cancel') button(opened, 'Cancel').onclick();
      else if (close === 'escape')
        opened.close(); // Native Escape closes the dialog without Apply.
      else {
        opened.onpointerdown({ target: opened });
        opened.onclick({ target: opened });
      }
      await editing;
      assert.equal(cropWidget(restored).value, saved.crop, before);
      assert.equal(restored.properties.arisu_crop_modes.image.ratio, mode);
    }
  }
  // Existing crops and malformed/mismatched metadata always open Free, without changing their shape.
  for (const entry of [
    undefined,
    null,
    { ratio: '9:16' },
    { root: 'photos', path: 'legacy.png', ratio: '7:3' },
    { root: 'other', path: 'legacy.png', ratio: '1:1' },
    { root: 'photos', path: 'other.png', ratio: '1:1' },
  ]) {
    const legacy = makeLoadNode('legacy.png');
    cropWidget(legacy).value = '10,20,300,300';
    legacy.properties.arisu_crop_modes = { image: entry };
    const editing = cropButton(legacy).callback();
    await settle();
    assert.equal(ratioMenu(openDialog()).value, 'free');
    assert.equal(readout(openDialog()), '300 × 300 at 10, 20');
    button(openDialog(), 'Cancel').onclick();
    await editing;
    assert.equal(cropWidget(legacy).value, '10,20,300,300');
  }
  // picking another file in the browser drops the remembered ratio along with the crop
  api.responses.push(jsonResponse(200, { roots: [{ id: 'photos', label: 'photos' }] }));
  await extensionNamed('Arisu.Common.LoadImage').setup();
  api.responses.push(
    jsonResponse(200, {
      root: 'photos',
      path: '',
      parent: null,
      dirs: [],
      files: ['b.png'],
      ancestors: [],
      roots: [{ id: 'photos', label: 'photos' }],
    }),
  );
  await node.widgets.find((widget) => widget.name === 'Browse').callback();
  await byClass(openDialog(), 'arisu-browser-file')[0].onclick();
  assert.equal(node.widgets[0].value, 'b.png');
  assert.equal(node.properties.arisu_crop_modes, undefined);
  applied = cropButton(node).callback();
  await settle();
  assert.equal(ratioMenu(openDialog()).value, 'free');
  chooseRatio(openDialog(), '3:2');
  button(openDialog(), 'Cancel').onclick();
  await applied;
  // the ratio belongs to the file it was chosen for: a path typed into the field, which the browser never sees, starts free
  node.widgets[0].value = 'c.png';
  applied = cropButton(node).callback();
  await settle();
  assert.equal(ratioMenu(openDialog()).value, 'free');
  button(openDialog(), 'Cancel').onclick();
  await applied;
  // nothing to crop without a file, and a format the browser cannot decode has no known size: a warning, no dialog
  await cropButton(makeLoadNode('')).callback();
  await cropButton(makeLoadNode('broken.png')).callback();
  assert.equal(openDialog(), undefined);
  assert.deepEqual(toastSeverities(), ['warn', 'warn']);
  // An outstanding crop dialog cannot restore a selection or its remembered ratio after a paste/reset.
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  chooseRatio(dialog, '1:1');
  await LoadImage.prototype.onConfigure.call(node);
  button(dialog, 'Apply').onclick();
  await applied;
  assert.equal(node.widgets[0].value, '');
  assert.equal(cropWidget(node).value, '');
  assert.equal(node.properties.arisu_crop_modes, undefined);
  assert.equal(node.imgs, undefined);
  // Reset while the original file is loading for the crop dialog must not open a dialog later.
  node.widgets[0].value = 'c.png';
  applied = cropButton(node).callback();
  await LoadImage.prototype.onConfigure.call(node);
  await applied;
  assert.equal(openDialog(), undefined);
  // A second crop request also cancels an earlier image load within the same selection generation.
  node.widgets[0].value = 'c.png';
  const superseded = cropButton(node).callback();
  const current = cropButton(node).callback();
  await superseded;
  await settle();
  assert.equal(body.children.filter((element) => element.tagName === 'DIALOG').length, 1);
  button(openDialog(), 'Cancel').onclick();
  await current;
  assert.equal(node.properties.arisu_crop_modes, undefined);
});
