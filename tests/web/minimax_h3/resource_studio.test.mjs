// Exercise the shipped Studio extension through node lifecycle and real DOM handlers.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, toastSeverities } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/minimax_h3/resource_studio.js';

const TYPE = 'ArisuMiniMaxH3ResourceStudio';
const definition = { prototype: {} };
const extension = extensionNamed('Arisu.MiniMaxH3.ResourceStudio');
extension.beforeRegisterNodeDef(definition, { name: TYPE });
const empty = () => ({ version: 1, keyframes: { first: null, last: null }, references: [] });
const widget = (node, name) => node.widgets.find((widget) => widget.name === name);
const state = (node) => JSON.parse(widget(node, 'resources_json').value);
const panel = (node) => widget(node, 'studio').element;
const button = (root, name) =>
  descendants(root).find((element) => element.tagName === 'BUTTON' && (element.textContent === name || element.ariaLabel === name));
const settle = () => new Promise((resolve) => setImmediate(resolve));
function create(data = empty()) {
  const node = makeNode({
    id: 1,
    type: TYPE,
    graph: app.graph,
    widgets: [
      { name: 'aspect_ratio', value: '16:9 (Widescreen)' },
      { name: 'advertise', value: false },
      { name: 'resources_json', value: JSON.stringify(data) },
    ],
    outputs: ['resources'],
  });
  definition.prototype.onNodeCreated.call(node);
  return node;
}
function card(id, kind = 'image', muted = false) {
  return {
    id,
    kind,
    root: 'input',
    path: `${id}.${kind === 'image' ? 'png' : kind === 'video' ? 'mkv' : 'wav'}`,
    muted,
    ...(kind === 'image' ? { crop: null } : { clip: { start: 0, end: 5 }, ...(kind === 'video' ? { include_audio: true } : {}) }),
  };
}

test('Studio edits and reorders independent cards, counts only active references, and discards imported locations', async () => {
  resetApp(makeGraph());
  resetApi();
  resetDom();
  const node = create();
  assert.equal(
    descendants(panel(node)).some((element) => element.textContent?.startsWith('Images ')),
    false,
  );
  const data = empty();
  data.references = [card('picture'), card('video', 'video'), card('sound', 'audio', true)];
  widget(node, 'resources_json').value = JSON.stringify(data);
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert(descendants(panel(node)).some((element) => element.textContent === 'Images 1 · Videos 1 · Audio 0'));
  assert.equal(
    descendants(panel(node)).some((element) => ['VIDEO', 'AUDIO'].includes(element.tagName)),
    false,
  );
  let rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[0], 'Mute').onclick();
  assert.equal(state(node).references[0].muted, true);
  assert(descendants(panel(node)).some((element) => element.textContent === 'Images 0 · Videos 1 · Audio 0'));
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[2], 'Move up').onclick();
  assert.deepEqual(
    state(node).references.map((card) => card.id),
    ['picture', 'sound', 'video'],
  );
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[1], 'Unmute').onclick();
  assert(descendants(panel(node)).some((element) => element.textContent === 'Images 0 · Videos 1 · Audio 1'));
  // Existing card edits are drafts; Cancel and node removal cannot write stale selections.
  api.responses.push(jsonResponse(200, { kind: 'audio', duration: 12, has_audio: true, revision: 'a' }));
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  const editing = button(rows[1], 'Edit audio sound.wav').onclick();
  await settle();
  const dialog = body.children.find((element) => element.tagName === 'DIALOG');
  assert(dialog);
  const end = descendants(dialog).find((element) => element.ariaLabel === 'End seconds');
  end.value = '8';
  end.onchange();
  button(dialog, 'Cancel').onclick();
  await editing;
  assert.equal(state(node).references[1].clip.end, 5);
  definition.prototype.onConfigure.call(node);
  assert.deepEqual(state(node), empty());
  assert.equal(api.calls.filter((call) => call.route.includes('metadata')).length, 1);
});

test('Studio keyframes auto-crop on effective ratio changes and preserve manual edits until the basis changes', async () => {
  resetApp(makeGraph());
  resetApi();
  resetDom();
  const data = empty();
  data.keyframes.first = { ...card('first'), crop_basis_ratio: '16:9 (Widescreen)', crop: { left: 2, top: 3, width: 20, height: 10 } };
  const node = create(data);
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.equal(state(node).keyframes.first.crop.width, 20);
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  widget(node, 'aspect_ratio').value = '1:1 (Square)';
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 100, top: 0, width: 600, height: 600 });
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  const editing = button(panel(node), 'first frame').onclick();
  await settle();
  const dialog = body.children.find((element) => element.tagName === 'DIALOG');
  assert(button(dialog, 'auto-crop'));
  button(dialog, 'reset').onclick();
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  button(dialog, 'apply').onclick();
  await editing;
  assert.equal(state(node).keyframes.first.crop, null);
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.equal(state(node).keyframes.first.crop, null);
  button(panel(node), 'Mute').onclick();
  widget(node, 'aspect_ratio').value = '16:9 (Widescreen)';
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 0, top: 75, width: 800, height: 450 });
  assert.equal(state(node).keyframes.first.muted, true);
  const before = widget(node, 'resources_json').value;
  definition.prototype.onExecuted.call(node, { arisu_resources: [{ state: 'obsolete', keyframes: {} }] });
  assert.equal(widget(node, 'resources_json').value, before);
  definition.prototype.onRemoved.call(node);
  assert(!body.children.some((element) => element.open));
  assert(!toastSeverities().includes('error'));
});
