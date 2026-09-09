// Load Image (Browse)'s crop button: the dialog it opens on the picked file, how a drag, a ratio,
// apply and reset drive the hidden crop widget (the value core.parse_crop reads on the other side)
// and the node preview, and how it declines a file it cannot show.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { resetApi } from '../support/api.mjs';
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
  // a ratio fits the largest such box inside it, centred
  const ratioField = byClass(dialog, 'arisu-cropper-ratio')[0];
  ratioField.value = '1:1';
  ratioField.onchange();
  assert.equal(readout(dialog), '300 × 300 at 250, 150');
  // dragging the box moves it, and it stops at the image's edge
  const box = byClass(dialog, 'arisu-cropper-box')[0];
  press(box, 200, 200);
  drag(400, 200);
  release();
  assert.equal(readout(dialog), '300 × 300 at 500, 150');
  // a corner handle resizes from the opposite corner, which holds, and keeps the ratio
  press(
    descendants(dialog).find((element) => element.handle === 'nw'),
    250,
    75,
  );
  drag(300, 100);
  release();
  assert.equal(readout(dialog), '250 × 250 at 550, 200');
  // apply: the crop widget gets the box and its callback, the dialog goes, the node previews the cropped pixels
  button(dialog, 'apply').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '550,200,250,250');
  assert.deepEqual(written, ['550,200,250,250']);
  assert.equal(dialog.open, false);
  assert.equal(openDialog(), undefined);
  assert.deepEqual([query(node.imgs[0].src).path, query(node.imgs[0].src).crop], ['/in/a.png', '550,200,250,250']);
  assert.equal(query(node.imgs[0].src).max, undefined);
  // opening again starts from the saved box; reset is the whole image, which is stored as no crop at all
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  assert.equal(readout(dialog), '250 × 250 at 550, 200');
  button(dialog, 'reset').onclick();
  assert.equal(readout(dialog), '800 × 600 at 0, 0');
  assert.equal(ratioField.value, '1:1');
  button(dialog, 'apply').onclick();
  await applied;
  assert.deepEqual(written, ['550,200,250,250', '']);
  assert.equal(query(node.imgs[0].src).crop, undefined);
  // cancel leaves the widget alone
  applied = cropButton(node).callback();
  await settle();
  dialog = openDialog();
  press(img, 0, 0);
  drag(100, 100);
  release();
  button(dialog, 'cancel').onclick();
  await applied;
  assert.equal(cropWidget(node).value, '');
  assert.deepEqual(written, ['550,200,250,250', '']);
  assert.deepEqual(toastSeverities(), []);
  // nothing to crop without a file, and a format the browser cannot decode has no known size: a warning, no dialog
  await cropButton(makeLoadNode('')).callback();
  await cropButton(makeLoadNode('/in/scan.tif')).callback();
  assert.equal(openDialog(), undefined);
  assert.deepEqual(toastSeverities(), ['warn', 'warn']);
});
