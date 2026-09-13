// Exercise the shipped Studio extension through node lifecycle and real DOM handlers.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, settings, toastSeverities } from '../support/app.mjs';
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
// The per-type counters, absent while the reference list is empty.
const counts = (node) =>
  descendants(panel(node))
    .find((element) => element.className === 'counts')
    ?.children.map((element) => element.textContent);
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

async function pick(control, path) {
  api.responses.push(
    jsonResponse(200, {
      root: 'input',
      path: '',
      parent: null,
      dirs: [],
      files: [path],
      ancestors: [],
      roots: [{ id: 'input', label: 'Input' }],
      kinds: { [path]: 'image' },
    }),
  );
  await control.onclick();
  const dialog = body.children.find((element) => element.tagName === 'DIALOG' && element.open);
  const file = descendants(dialog).find((element) => element.className === 'arisu-browser-file');
  assert(file);
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  await file.onclick();
}

async function checkBrowse(control, node, expected) {
  const before = state(node);
  api.responses.push((route) => {
    const query = new URL(route, 'http://localhost').searchParams;
    const path = query.get('path').split('/').slice(0, -1).join('/');
    return jsonResponse(200, {
      root: query.get('root'),
      path,
      parent: null,
      dirs: [],
      files: [],
      ancestors: [],
      roots: [
        { id: 'input', label: 'Input' },
        { id: 'output', label: 'Output' },
      ],
    });
  });
  await control.onclick();
  const dialog = body.children.find((element) => element.open);
  const location = descendants(dialog).find((element) => element.className === 'arisu-browser-path');
  const [root, path] = expected.split(':');
  assert.equal(location.textContent, path);
  assert.equal(location.title, `Relative to ${root}`);
  dialog.close();
  assert.deepEqual(state(node), before);
}

test('Studio edits and reorders independent cards, counts only active references, and discards imported locations', async (t) => {
  resetApp(makeGraph());
  resetApi();
  resetDom();
  const node = create();
  assert.equal(counts(node), undefined);
  // HTTP origins lack randomUUID; new cards must still persist independent identities.
  const descriptor = Object.getOwnPropertyDescriptor(globalThis.crypto, 'randomUUID');
  const restoreUUID = () => {
    if (descriptor) Object.defineProperty(globalThis.crypto, 'randomUUID', descriptor);
    else delete globalThis.crypto.randomUUID;
  };
  t.after(restoreUUID);
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: undefined });
  api.responses.push(
    jsonResponse(200, {
      roots: [
        { id: 'input', label: 'Input' },
        { id: 'output', label: 'Output' },
      ],
    }),
  );
  for (const slot of ['first', 'last']) {
    await pick(button(panel(node), `${slot} frame`), `${slot}.png`);
    assert.equal(state(node).keyframes[slot]?.path, `${slot}.png`);
  }
  for (const path of ['one.png', 'two.png']) await pick(button(panel(node), 'Browse references…'), path);
  const selected = state(node);
  assert.deepEqual(
    selected.references.map((item) => item.path),
    ['one.png', 'two.png'],
  );
  const ids = [selected.keyframes.first, selected.keyframes.last, ...selected.references].map((item) => item.id);
  assert.equal(new Set(ids).size, 4);
  for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  button(panel(node), 'Mute').onclick();
  await pick(button(panel(node), 'first frame'), 'replacement.png');
  assert.equal(state(node).keyframes.first.muted, true);
  assert.equal(button(panel(node), 'Replace'), undefined);
  assert.equal(state(node).keyframes.first.id, ids[0]);
  assert.equal(state(node).keyframes.first.path, 'replacement.png');
  await checkBrowse(button(panel(node), 'first frame'), node, 'input:/');
  await checkBrowse(button(panel(node), 'Browse references…'), node, 'input:/');
  restoreUUID();
  await pick(button(panel(node), 'Browse references…'), 'native.png');
  assert.equal(state(node).references[2].path, 'native.png');
  assert(!ids.includes(state(node).references[2].id));
  assert(!toastSeverities().includes('error'));
  resetApi();
  const data = empty();
  data.references = [card('picture'), card('video', 'video'), card('sound', 'audio', true)];
  data.references[2].root = 'output';
  data.references[2].path = 'audio/sound.wav';
  widget(node, 'resources_json').value = JSON.stringify(data);
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(counts(node), ['image 1', 'video 1', 'audio 0']);
  assert.equal(
    descendants(panel(node)).some((element) => ['VIDEO', 'AUDIO'].includes(element.tagName)),
    false,
  );
  await checkBrowse(button(panel(node), 'Browse references…'), node, 'output:audio');
  let rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[0], 'Mute').onclick();
  assert.equal(state(node).references[0].muted, true);
  assert.deepEqual(counts(node), ['image 0', 'video 1', 'audio 0']);
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[2], 'Move up').onclick();
  assert.deepEqual(
    state(node).references.map((card) => card.id),
    ['picture', 'sound', 'video'],
  );
  await checkBrowse(button(panel(node), 'Browse references…'), node, 'input:/');
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[1], 'Unmute').onclick();
  assert.deepEqual(counts(node), ['image 0', 'video 1', 'audio 1']);
  // Existing card edits are drafts; Cancel and node removal cannot write stale selections.
  api.responses.push(jsonResponse(200, { kind: 'audio', duration: 12, has_audio: true, revision: 'a' }));
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  const editing = button(rows[1], 'Edit audio audio/sound.wav').onclick();
  await settle();
  const dialog = body.children.find((element) => element.tagName === 'DIALOG');
  assert(dialog);
  const end = descendants(dialog).find((element) => element.ariaLabel === 'End seconds');
  end.value = '8';
  end.onchange();
  button(dialog, 'Cancel').onclick();
  await editing;
  assert.equal(state(node).references[1].clip.end, 5);
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[2], 'Remove').onclick();
  await checkBrowse(button(panel(node), 'Browse references…'), node, 'output:audio');
  for (const row of descendants(panel(node)).filter((element) => element.dataset.cardId)) button(row, 'Remove').onclick();
  settings['Arisu.LoadImage.DefaultRoot'] = 'output';
  await checkBrowse(button(panel(node), 'Browse references…'), node, 'output:/');
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
  for (const slot of ['first', null]) {
    for (const [crop, expected, parts] of [
      [{ left: 2, top: 3, width: 320, height: 180 }, '16:9', []],
      [{ left: 2, top: 3, width: 210, height: 90 }, 'custom', ['7', '3']],
      [null, 'free', []],
    ]) {
      const next = state(node);
      const item = { ...card('ratio'), crop, crop_basis_ratio: '16:9 (Widescreen)' };
      if (slot) next.keyframes.first = item;
      else next.references = [item];
      widget(node, 'resources_json').value = JSON.stringify(next);
      widget(node, 'aspect_ratio').callback();
      await settle();
      for (const action of ['apply', 'cancel']) {
        api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
        const editing = button(panel(node), slot ? 'Crop' : 'Edit image ratio.png').onclick();
        await settle();
        const dialog = body.children.find((element) => element.open);
        assert.equal(descendants(dialog).find((element) => element.className === 'arisu-cropper-ratio').value, expected);
        const fields = descendants(dialog).filter((element) => element.className === 'arisu-cropper-ratio-part');
        assert.deepEqual(
          fields.filter((element) => !element.hidden).map((element) => element.value),
          parts,
        );
        assert.equal(
          descendants(dialog).find((element) => element.className === 'arisu-cropper-readout').textContent,
          crop ? `${crop.width} × ${crop.height} at ${crop.left}, ${crop.top}` : '800 × 600 at 0, 0',
        );
        if (action === 'apply') api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
        button(dialog, action).onclick();
        await editing;
        assert.deepEqual((slot ? state(node).keyframes.first : state(node).references[0]).crop, crop);
      }
    }
  }

  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  widget(node, 'aspect_ratio').value = '1:1 (Square)';
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 100, top: 0, width: 600, height: 600 });
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  const editing = button(panel(node), 'Crop').onclick();
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
