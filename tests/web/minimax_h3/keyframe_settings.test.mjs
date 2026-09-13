// The hybrid nodes' keyframes button: the eight keyframe fit widgets hidden on both node types,
// after a workflow load too, and the dialog that edits them seeded from the widgets, each keyframe
// on its own. The dialog's own mechanics (reset, cancel, the colour picker) are covered by
// resize_image.test.mjs through the shared settings_button.js.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { app, extensionNamed, resetApp } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/minimax_h3/keyframe_settings.js';

const KEYFRAMES = ['first_frame', 'last_frame'];
const CONFIG = KEYFRAMES.flatMap((frame) => [`${frame}_resize_method`, `${frame}_mode`, `${frame}_pad_color`, `${frame}_crop_position`]);
const SIZE = ['INT', { default: 1344, min: 32, max: 16384, step: 32 }];

/** The node definition as the frontend hands it to beforeRegisterNodeDef; the Advanced node adds the target size. */
function nodeData(name, targets = {}) {
  const required = {
    clip: ['CLIP', {}],
    vae: ['VAE', {}],
    prompt: ['STRING', { multiline: true }],
    width: SIZE,
    height: SIZE,
    ...targets,
    length: ['INT', { default: 124, min: 5, max: 3600, step: 17 }],
    ref_image_size: ['COMBO', { options: ['match', 'max'], default: 'match' }],
    frame_picture_tags: ['COMBO', { options: ['after_refs', 'before_refs', 'none'], default: 'after_refs' }],
  };
  for (const frame of KEYFRAMES) {
    required[`${frame}_resize_method`] = [
      'COMBO',
      { options: ['nearest-exact', 'bilinear', 'area', 'bicubic', 'lanczos'], default: 'lanczos' },
    ];
    required[`${frame}_mode`] = ['COMBO', { options: ['crop', 'pad', 'stretch'], default: 'crop' }];
    required[`${frame}_pad_color`] = ['STRING', { default: '0, 0, 0' }];
    required[`${frame}_crop_position`] = ['COMBO', { options: ['center', 'top', 'bottom', 'left', 'right'], default: 'center' }];
  }
  const optional = {
    audio_vae: ['VAE', {}],
    resources: ['ARISU_MINIMAX_H3_RESOURCES', {}],
    first_frame: ['IMAGE', {}],
    last_frame: ['IMAGE', {}],
  };
  return { name, input: { required, optional } };
}

const HYBRID = nodeData('ArisuMiniMaxH3HybridToVideo');
const ADVANCED = nodeData('ArisuMiniMaxH3HybridToVideoAdvanced', { target_width: SIZE, target_height: SIZE });
const NO_WIDGET = new Set(['CLIP', 'VAE', 'IMAGE', 'ARISU_MINIMAX_H3_RESOURCES']);

const Hybrid = { prototype: {} };
const Advanced = { prototype: {} };
const Other = { prototype: {} };
const extension = extensionNamed('Arisu.MiniMaxH3.KeyframeSettings');
extension.beforeRegisterNodeDef(Hybrid, HYBRID);
extension.beforeRegisterNodeDef(Advanced, ADVANCED);
extension.beforeRegisterNodeDef(Other, { name: 'ArisuMiniMaxH3VideoSettings', input: { required: {} } });

/** A node as LiteGraph builds it from `data`: a widget per value input at its default, a socket per input. */
function makeHybridNode(data, values = {}) {
  const inputs = { ...data.input.required, ...data.input.optional };
  const widgets = Object.entries(inputs)
    .filter(([, [type]]) => !NO_WIDGET.has(type))
    .map(([name, [, options]]) => ({ name, value: values[name] ?? options.default, options: {} }));
  return makeNode({ id: 3, type: data.name, graph: app.graph, widgets, inputs: sockets(data), outputs: ['positive', 'latent'] });
}

function sockets(data) {
  return Object.keys({ ...data.input.required, ...data.input.optional }).map((name) => ({ name, widget: { name } }));
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

test('both hybrid nodes hide the eight keyframe fit widgets behind a keyframes button whose dialog edits each keyframe on its own', async () => {
  resetApp(makeGraph());
  resetDom();
  assert.equal(Other.prototype.onNodeCreated, undefined);
  for (const [Type, data] of [
    [Hybrid, HYBRID],
    [Advanced, ADVANCED],
  ]) {
    const node = makeHybridNode(data);
    Type.prototype.onNodeCreated.call(node);
    assert.ok(
      CONFIG.every((name) => hidden(node, name)),
      `case=${data.name}`,
    );
    assert.equal(widget(node, 'width').hidden, undefined, `case=${data.name}`);
    const names = node.inputs.map((input) => input.name);
    assert.ok(
      CONFIG.every((name) => !names.includes(name)),
      `case=${data.name}`,
    );
    assert.ok(
      ['width', 'first_frame', 'last_frame', 'resources'].every((name) => names.includes(name)),
      `case=${data.name}`,
    );
    // the button is last and never saved
    const button = node.widgets.at(-1);
    assert.deepEqual([button.name, button.serialize], ['keyframes…', false], `case=${data.name}`);
    // a loaded workflow restores every saved socket and knows nothing of hidden: configure hides again
    const loaded = makeHybridNode(data, { last_frame_mode: 'pad' });
    Type.prototype.onNodeCreated.call(loaded);
    loaded.inputs = sockets(data);
    Type.prototype.onConfigure.call(loaded, {});
    assert.ok(
      CONFIG.every((name) => hidden(loaded, name)),
      `case=${data.name}`,
    );
    assert.equal(loaded.inputs.length, sockets(data).length - CONFIG.length, `case=${data.name}`);
    assert.equal(widget(loaded, 'last_frame_mode').value, 'pad', `case=${data.name}`);
  }
  // the dialog lists the first frame's settings, then the last frame's, each under its own heading with the
  // keyframe prefix dropped from the labels, seeded lanczos / crop / center from the widgets
  const node = makeHybridNode(HYBRID);
  Hybrid.prototype.onNodeCreated.call(node);
  const written = [];
  for (const name of CONFIG) widget(node, name).callback = (value) => written.push([name, value]);
  const applied = widget(node, 'keyframes…').callback();
  const dialog = openDialog();
  assert.equal(dialog.open, true);
  assert.deepEqual(
    descendants(dialog)
      .filter((element) => element.id?.startsWith('arisu-settings-'))
      .map((element) => element.id.slice('arisu-settings-'.length)),
    CONFIG,
  );
  assert.deepEqual(
    descendants(dialog)
      .filter((element) => element.className === 'arisu-settings-heading')
      .map((element) => element.textContent),
    ['first frame', 'last frame'],
  );
  assert.deepEqual(
    descendants(dialog)
      .filter((element) => element.className === 'arisu-settings-label')
      .map((element) => [element.htmlFor, element.textContent]),
    CONFIG.map((name) => [`arisu-settings-${name}`, name.replace(/^(first|last)_frame_/, '')]),
  );
  for (const frame of KEYFRAMES) {
    const mode = control(dialog, `${frame}_mode`);
    assert.deepEqual([mode.tagName, mode.value, mode.children.length], ['SELECT', 'crop', 3], `case=${frame}`);
    assert.equal(control(dialog, `${frame}_resize_method`).value, 'lanczos', `case=${frame}`);
    assert.equal(control(dialog, `${frame}_crop_position`).value, 'center', `case=${frame}`);
    assert.equal(control(dialog, `${frame}_pad_color`).type, 'text', `case=${frame}`);
  }
  assert.equal(descendants(dialog).filter((element) => element.className === 'arisu-settings-swatch').length, 2);
  // padding the last frame leaves the first frame's settings alone
  control(dialog, 'last_frame_mode').value = 'pad';
  control(dialog, 'last_frame_pad_color').value = 'white';
  descendants(dialog)
    .find((element) => element.tagName === 'BUTTON' && element.textContent === 'apply')
    .onclick();
  await applied;
  assert.equal(openDialog(), undefined);
  assert.deepEqual(written, [
    ['last_frame_mode', 'pad'],
    ['last_frame_pad_color', 'white'],
  ]);
  assert.deepEqual([widget(node, 'first_frame_mode').value, widget(node, 'first_frame_pad_color').value], ['crop', '0, 0, 0']);
});
