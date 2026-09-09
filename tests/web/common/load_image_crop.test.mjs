// Load Image (Browse)'s crop button: the dialog it opens on the picked file, how a drag, a ratio,
// apply and reset drive the hidden crop widget (the value core.parse_crop reads on the other side)
// and the node preview, how the ratio is remembered for the picked file and starts free on another,
// and how it declines a file it cannot show.
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
  return node.widgets.find((widget) => widget.name === 'crop…');
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

/** The ratio menu and its two custom fields. */
function ratioControls(dialog) {
  return { menu: byClass(dialog, 'arisu-cropper-ratio')[0], parts: byClass(dialog, 'arisu-cropper-ratio-part') };
}

function chooseRatio(dialog, value) {
  const { menu } = ratioControls(dialog);
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
  const node = makeLoadNode('/in/a.png');
  const written = [];
  cropWidget(node).callback = (value) => written.push(value);
  // opening loads the file itself, whole, and starts with the whole image as the box
  let applied = cropButton(node).callback();
  await settle();
  let dialog = openDialog();
  assert.equal(dialog.open, true);
  const img = descendants(dialog).find((element) => element.tagName === 'IMG');
  assert.equal(query(img.src).path, '/in/a.png');
  assert.equal(query(img.src).max, undefined);
  assert.equal(readout(dialog), '800 × 600 at 0, 0');
  // the image is shown at half size: pointer positions map to image pixels through its on-screen rectangle
  img.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 300 });
  const stage = byClass(dialog, 'arisu-cropper-stage')[0];
  const press = (target, x, y) => stage.onpointerdown({ clientX: x, clientY: y, target, pointerId: 1 });
  const drag = (x, y) => stage.onpointermove({ clientX: x, clientY: y, pointerId: 1 });
  const release = () => stage.onpointerup({ pointerId: 1 });
  // a drag on the image draws a box
  press(img, 100, 75);
  drag(300, 225);
  release();
  assert.equal(readout(dialog), '400 × 300 at 200, 150');
  // a preset ratio makes the box the largest one of that ratio in the whole image, centred; the custom fields stay out of sight
  assert.equal(ratioControls(dialog).menu.value, 'free');
  assert.ok(ratioControls(dialog).parts.every((part) => part.hidden));
  chooseRatio(dialog, '1:1');
  assert.equal(readout(dialog), '600 × 600 at 100, 0');
  assert.ok(ratioControls(dialog).parts.every((part) => part.hidden));
  // a press inside the ratio menu that ends on the backdrop is not a backdrop click: the dialog stays
  dialog.onpointerdown({ target: ratioControls(dialog).menu });
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
  // apply: the crop widget gets the box and its callback, the dialog goes, the node previews the cropped pixels
  button(dialog, 'apply').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '400,200,400,400');
  assert.deepEqual(written, ['400,200,400,400']);
  assert.equal(dialog.open, false);
  assert.equal(openDialog(), undefined);
  assert.deepEqual([query(node.imgs[0].src).path, query(node.imgs[0].src).crop], ['/in/a.png', '400,200,400,400']);
  assert.equal(query(node.imgs[0].src).max, undefined);
  // opening again starts from the saved box and the remembered ratio; custom shows two fields, which read as free
  // until both are filled and then make the box the largest one of their ratio; cancel leaves the widget alone
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  assert.equal(ratioControls(dialog).menu.value, '1:1');
  chooseRatio(dialog, 'custom');
  const { parts } = ratioControls(dialog);
  assert.ok(parts.every((part) => !part.hidden));
  parts[0].value = '5';
  parts[0].oninput();
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  parts[1].value = '4';
  parts[1].oninput();
  assert.equal(readout(dialog), '750 × 600 at 25, 0');
  button(dialog, 'cancel').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '400,200,400,400');
  assert.deepEqual(written, ['400,200,400,400']);
  // the custom ratio comes back seeded into its fields, over the saved box; switching presets never shrinks the box,
  // since each one is fitted to the image, not to the box before it
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(readout(dialog), '400 × 400 at 400, 200');
  assert.equal(ratioControls(dialog).menu.value, 'custom');
  assert.deepEqual(
    ratioControls(dialog).parts.map((part) => part.value),
    ['5', '4'],
  );
  chooseRatio(dialog, '16:9');
  assert.equal(readout(dialog), '800 × 450 at 0, 75');
  chooseRatio(dialog, '9:16');
  assert.equal(readout(dialog), '338 × 600 at 231, 0');
  chooseRatio(dialog, '16:9');
  assert.equal(readout(dialog), '800 × 450 at 0, 75');
  // reset is the whole image at a free ratio, with the custom fields hidden and blank; applied, it is stored as no crop
  button(dialog, 'reset').onclick();
  assert.equal(readout(dialog), '800 × 600 at 0, 0');
  assert.equal(ratioControls(dialog).menu.value, 'free');
  assert.ok(ratioControls(dialog).parts.every((part) => part.hidden && part.value === ''));
  button(dialog, 'apply').onclick();
  await applied;
  assert.deepEqual(written, ['400,200,400,400', '']);
  assert.equal(query(node.imgs[0].src).crop, undefined);
  // the reset ratio is what comes back; cancel leaves the widget alone but still remembers the ratio chosen meanwhile
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(ratioControls(dialog).menu.value, 'free');
  press(img, 0, 0);
  drag(100, 100);
  release();
  chooseRatio(dialog, '16:9');
  button(dialog, 'cancel').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '');
  assert.deepEqual(written, ['400,200,400,400', '']);
  assert.deepEqual(toastSeverities(), []);
  // picking another file in the browser drops the remembered ratio along with the crop
  api.responses.push(jsonResponse(200, { path: '/in', parent: '/', dirs: [], files: ['b.png'], ancestors: [], roots: [], places: {} }));
  await node.widgets.find((widget) => widget.name === 'browse').callback();
  await byClass(openDialog(), 'arisu-browser-file')[0].onclick();
  assert.equal(node.widgets[0].value, '/in/b.png');
  applied = cropButton(node).callback();
  await settle();
  assert.equal(ratioControls(openDialog()).menu.value, 'free');
  chooseRatio(openDialog(), '3:2');
  button(openDialog(), 'cancel').onclick();
  await applied;
  // the ratio belongs to the file it was chosen for: a path typed into the field, which the browser never sees, starts free
  node.widgets[0].value = '/in/c.png';
  applied = cropButton(node).callback();
  await settle();
  assert.equal(ratioControls(openDialog()).menu.value, 'free');
  button(openDialog(), 'cancel').onclick();
  await applied;
  // nothing to crop without a file, and a format the browser cannot decode has no known size: a warning, no dialog
  await cropButton(makeLoadNode('')).callback();
  await cropButton(makeLoadNode('/in/scan.tif')).callback();
  assert.equal(openDialog(), undefined);
  assert.deepEqual(toastSeverities(), ['warn', 'warn']);
});
