// Resize Image's settings button: the five option widgets hidden on the node and after a
// workflow load, and the dialog that edits them: seeded from the widgets, apply writing the
// changed ones through their callbacks, reset, cancel and Escape.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { app, extensionNamed, resetApp } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/resize_image.js';

/** The node definition as the frontend hands it to beforeRegisterNodeDef: `[type or choices, options]` per input. */
const NODE_DATA = {
  name: 'ArisuResizeImage',
  input: {
    required: {
      image: ['IMAGE', {}],
      width: ['INT', { default: 512, min: 0, max: 16384 }],
      height: ['INT', { default: 512, min: 0, max: 16384 }],
      upscale_method: [['nearest-exact', 'bilinear', 'area', 'bicubic', 'lanczos'], { default: 'lanczos' }],
      keep_proportion: [['stretch', 'resize', 'pad', 'pad_edge', 'pad_edge_pixel', 'crop', 'pillarbox_blur', 'total_pixels'], {}],
      pad_color: ['STRING', { default: '0, 0, 0' }],
      crop_position: [['center', 'top', 'bottom', 'left', 'right'], { default: 'center' }],
      divisible_by: ['INT', { default: 2, min: 0, max: 512, step: 1 }],
    },
    optional: { mask: ['MASK', {}] },
  },
};
const CONFIG = ['upscale_method', 'keep_proportion', 'pad_color', 'crop_position', 'divisible_by'];
const SOCKETS = ['image', 'width', 'height', ...CONFIG, 'mask'];

const ResizeImage = { prototype: {} };
extensionNamed('Arisu.Common.ResizeImage').beforeRegisterNodeDef(ResizeImage, NODE_DATA);

/** A node as LiteGraph builds it from the definition: a widget per value input at its default, a socket per input. */
function makeResizeNode(values = {}) {
  const inputs = { ...NODE_DATA.input.required, ...NODE_DATA.input.optional };
  const widgets = Object.entries(inputs)
    .filter(([, [type]]) => type !== 'IMAGE' && type !== 'MASK')
    .map(([name, [type, options]]) => ({ name, value: values[name] ?? options.default ?? type[0], options: {} }));
  return makeNode({ id: 7, type: 'ArisuResizeImage', graph: app.graph, widgets, inputs: sockets(), outputs: ['image', 'mask'] });
}

function sockets() {
  return SOCKETS.map((name) => ({ name, widget: { name } }));
}

function widget(node, name) {
  return node.widgets.find((candidate) => candidate.name === name);
}

function hidden(node, name) {
  const candidate = widget(node, name);
  return candidate.hidden === true && candidate.options.hidden === true;
}

function openDialog() {
  return body.children.find((element) => element.tagName === 'DIALOG');
}

function control(dialog, name) {
  return descendants(dialog).find((element) => element.id === `arisu-settings-${name}`);
}

function button(dialog, label) {
  return descendants(dialog).find((element) => element.tagName === 'BUTTON' && element.textContent === label);
}

function reset() {
  resetApp(makeGraph());
  resetDom();
}

test('creation and a workflow load hide the five option widgets on both renderers and drop their sockets; width and height stay', () => {
  reset();
  const node = makeResizeNode();
  ResizeImage.prototype.onNodeCreated.call(node);
  assert.ok(CONFIG.every((name) => hidden(node, name)));
  assert.equal(widget(node, 'width').hidden, undefined);
  assert.equal(widget(node, 'height').hidden, undefined);
  assert.deepEqual(
    node.inputs.map((input) => input.name),
    ['image', 'width', 'height', 'mask'],
  );
  // the button is last, right under height, and never saved
  const settings = node.widgets.at(-1);
  assert.equal(settings.name, 'settings…');
  assert.equal(settings.serialize, false);
  // a loaded workflow restores every saved socket and knows nothing of hidden: configure hides again, twice is the same
  const loaded = makeResizeNode({ keep_proportion: 'pad' });
  ResizeImage.prototype.onNodeCreated.call(loaded);
  loaded.inputs = sockets();
  ResizeImage.prototype.onConfigure.call(loaded, {});
  ResizeImage.prototype.onConfigure.call(loaded, {});
  assert.ok(CONFIG.every((name) => hidden(loaded, name)));
  assert.deepEqual(
    loaded.inputs.map((input) => input.name),
    ['image', 'width', 'height', 'mask'],
  );
  assert.equal(widget(loaded, 'keep_proportion').value, 'pad');
});

test('the settings button opens a dialog seeded from the widgets; apply writes the changed ones, reset restores the defaults, cancel and Escape write nothing', async () => {
  reset();
  const node = makeResizeNode();
  ResizeImage.prototype.onNodeCreated.call(node);
  const written = [];
  for (const name of CONFIG) widget(node, name).callback = (value) => written.push([name, value]);
  // the controls come from the definition: the combo's choices, the number's bounds, the colour's picker
  let applied = widget(node, 'settings…').callback();
  let dialog = openDialog();
  assert.equal(dialog.open, true);
  const mode = control(dialog, 'keep_proportion');
  assert.equal(mode.tagName, 'SELECT');
  assert.equal(mode.value, 'stretch');
  assert.equal(mode.children.length, 8);
  const grid = control(dialog, 'divisible_by');
  assert.deepEqual([grid.type, grid.value, grid.min, grid.max], ['number', '2', '0', '512']);
  const color = control(dialog, 'pad_color');
  const swatch = descendants(dialog).find((element) => element.className === 'arisu-settings-swatch');
  assert.deepEqual([color.value, swatch.value], ['0, 0, 0', '#000000']);
  // typing a colour moves the picker; picking one writes the text in the backend's default form
  color.value = '#FF0000';
  color.oninput();
  assert.equal(swatch.value, '#ff0000');
  color.value = 'white';
  color.oninput();
  assert.equal(swatch.value, '#ff0000');
  swatch.value = '#00ff00';
  swatch.oninput();
  assert.equal(color.value, '0, 255, 0');
  // apply: the changed widgets get their values through the callback path, a number held to its bounds; the others are left alone
  mode.value = 'pad';
  grid.value = '600';
  button(dialog, 'apply').onclick();
  await applied;
  assert.equal(dialog.open, false);
  assert.equal(openDialog(), undefined);
  assert.deepEqual(written, [
    ['keep_proportion', 'pad'],
    ['pad_color', '0, 255, 0'],
    ['divisible_by', 512],
  ]);
  assert.deepEqual([widget(node, 'upscale_method').value, widget(node, 'crop_position').value], ['lanczos', 'center']);
  // reopening starts from the widgets; reset is the declared defaults, applied like any edit
  applied = widget(node, 'settings…').callback();
  dialog = openDialog();
  assert.deepEqual([control(dialog, 'keep_proportion').value, control(dialog, 'divisible_by').value], ['pad', '512']);
  button(dialog, 'reset').onclick();
  assert.deepEqual([control(dialog, 'keep_proportion').value, control(dialog, 'divisible_by').value], ['stretch', '2']);
  button(dialog, 'apply').onclick();
  await applied;
  assert.deepEqual(written.slice(3), [
    ['keep_proportion', 'stretch'],
    ['pad_color', '0, 0, 0'],
    ['divisible_by', 2],
  ]);
  // cancel, and the dialog closing on its own (Escape, a backdrop click), write nothing
  applied = widget(node, 'settings…').callback();
  dialog = openDialog();
  control(dialog, 'keep_proportion').value = 'crop';
  button(dialog, 'cancel').onclick();
  await applied;
  applied = widget(node, 'settings…').callback();
  dialog = openDialog();
  control(dialog, 'divisible_by').value = '64';
  dialog.close();
  await applied;
  assert.deepEqual([widget(node, 'keep_proportion').value, widget(node, 'divisible_by').value], ['stretch', 2]);
  assert.equal(written.length, 6);
  assert.equal(openDialog(), undefined);
});
