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
      { name: 'advertise_resources', value: false },
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

/** Open Browse from `control`, expect it at `expected` (`root:path`) listing `kinds`, and hand back the file cards. */
async function checkBrowse(control, node, expected, kinds = {}) {
  const before = state(node);
  api.responses.push((route) => {
    const query = new URL(route, 'http://localhost').searchParams;
    const path = query.get('path').split('/').slice(0, -1).join('/');
    return jsonResponse(200, {
      root: query.get('root'),
      path,
      parent: null,
      dirs: [],
      files: Object.keys(kinds),
      kinds,
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
  const cards = descendants(dialog).filter((element) => element.className === 'arisu-browser-file');
  dialog.close();
  assert.deepEqual(state(node), before);
  return cards;
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
    await pick(button(panel(node), `${slot === 'first' ? 'First' : 'Last'} Frame`), `${slot}.png`);
    assert.equal(state(node).keyframes[slot]?.path, `${slot}.png`);
    assert.equal(node.properties.arisu_crop_modes[`keyframe:${slot}`].ratio, '16:9');
  }
  for (const path of ['one.png', 'two.png']) await pick(button(panel(node), 'Browse References…'), path);
  const selected = state(node);
  assert.deepEqual(
    selected.references.map((item) => item.path),
    ['one.png', 'two.png'],
  );
  const ids = [selected.keyframes.first, selected.keyframes.last, ...selected.references].map((item) => item.id);
  assert.equal(new Set(ids).size, 4);
  for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  button(panel(node), 'Mute').onclick();
  await pick(button(panel(node), 'First Frame'), 'replacement.png');
  assert.equal(state(node).keyframes.first.muted, true);
  assert.equal(button(panel(node), 'Replace'), undefined);
  assert.equal(state(node).keyframes.first.id, ids[0]);
  assert.equal(state(node).keyframes.first.path, 'replacement.png');
  assert.deepEqual(node.properties.arisu_crop_modes['keyframe:first'], { root: 'input', path: 'replacement.png', ratio: '16:9' });
  await checkBrowse(button(panel(node), 'First Frame'), node, 'input:/');
  // Browse references marks every card already in the list, not only the last one, and never a keyframe.
  const marks = (cards) => cards.map((card) => [card.title, card.ariaCurrent, card.dataset.kind]);
  assert.deepEqual(
    marks(
      await checkBrowse(button(panel(node), 'Browse References…'), node, 'input:/', {
        'one.png': 'image',
        'two.png': 'image',
        'first.png': 'image',
      }),
    ),
    [
      ['input:one.png', 'true', 'image'],
      ['input:two.png', 'true', 'image'],
      ['input:first.png', null, 'image'],
    ],
  );
  // Two reference cards may share a source while retaining separate applied modes through reordering.
  const referenceIds = state(node).references.map((item) => item.id);
  const independent = state(node);
  independent.references[1].path = independent.references[0].path;
  widget(node, 'resources_json').value = JSON.stringify(independent);
  widget(node, 'aspect_ratio').callback();
  await settle();
  for (const [index, mode] of ['9:16', '21:9'].entries()) {
    const row = descendants(panel(node)).filter((element) => element.dataset.cardId)[index];
    api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
    const editing = button(row, 'Edit image one.png').onclick();
    await settle();
    const dialog = body.children.find((element) => element.open);
    const menu = descendants(dialog).find((element) => element.className === 'arisu-cropper-ratio');
    menu.value = mode;
    menu.onchange();
    api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
    button(dialog, 'Apply').onclick();
    await editing;
  }
  let referenceRows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(referenceRows[1], 'Move Up').onclick();
  assert.deepEqual(
    state(node).references.map((item) => item.id),
    referenceIds.toReversed(),
  );
  for (const [id, mode] of [
    [referenceIds[0], '9:16'],
    [referenceIds[1], '21:9'],
  ]) {
    assert.equal(node.properties.arisu_crop_modes[`reference:${id}`].ratio, mode);
  }
  referenceRows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(referenceRows[0], 'Remove').onclick();
  assert.equal(node.properties.arisu_crop_modes[`reference:${referenceIds[1]}`], undefined);
  assert.equal(node.properties.arisu_crop_modes[`reference:${referenceIds[0]}`].ratio, '9:16');
  // Restore the original two-card fixture for the remaining media-browser story.
  widget(node, 'resources_json').value = JSON.stringify(selected);
  widget(node, 'aspect_ratio').callback();
  await settle();
  restoreUUID();
  await pick(button(panel(node), 'Browse References…'), 'native.png');
  assert.equal(state(node).references[2].path, 'native.png');
  assert(!ids.includes(state(node).references[2].id));
  assert(!toastSeverities().includes('error'));
  resetApi();
  const data = empty();
  data.references = [card('picture'), card('video', 'video'), card('sound', 'audio', true)];
  data.references[2].root = 'output';
  data.references[2].path = 'audio/sound.wav';
  // Cards restored without in-memory metadata probe it once, in list order, and describe themselves like the design.
  api.responses.push(
    jsonResponse(200, { kind: 'image', width: 1200, height: 1200, size: 1468006, revision: 'i' }),
    jsonResponse(200, { kind: 'video', duration: 12, has_audio: true, width: 1280, height: 720, rate: 24, size: 8493465, revision: 'v' }),
    jsonResponse(200, { kind: 'audio', duration: 8.25, has_audio: true, width: 0, height: 0, rate: 48000, size: 2306867, revision: 'a' }),
  );
  widget(node, 'resources_json').value = JSON.stringify(data);
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(counts(node), ['Image 1', 'Video 1']);
  const details = () =>
    descendants(panel(node))
      .filter((element) => element.dataset.cardId)
      .map((row) => descendants(row).find((element) => element.className === 'detail'))
      .map((detail) => [detail.children[0].textContent, detail.children.map((part) => part.textContent).join('')]);
  assert.deepEqual(details(), [
    ['1200×1200', '1200×1200 · 1.4 MB'],
    ['00:05', '00:05 / 00:12 · 1280×720 · 8.1 MB'],
    ['00:05', '00:05 / 00:08.3 · 48 kHz · 2.2 MB'],
  ]);
  const probed = api.calls.length;
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.equal(api.calls.length, probed);
  // Canvas gestures pass through the panel; only an overflowing list keeps a plain vertical wheel for itself.
  const canvas = { calls: [] };
  for (const method of ['processMouseWheel', 'processMouseDown', 'processMouseMove', 'processMouseUp']) {
    canvas[method] = (event) => canvas.calls.push([method, event.type]);
  }
  app.canvas = canvas;
  // The fake DOM does not bubble: a target's own handler runs first and the panel's listeners follow unless it stopped.
  const fire = (target, type, init = {}) => {
    const event = { type, deltaX: 0, deltaY: 120, ctrlKey: false, button: 0, buttons: 1, stopped: false, prevented: false, ...init };
    event.currentTarget = target;
    event.stopPropagation = () => {
      event.stopped = true;
    };
    event.preventDefault = () => {
      event.prevented = true;
    };
    target[`on${type}`]?.(event);
    if (!event.stopped) for (const listener of panel(node).listeners.get(type) ?? []) listener(event);
    return event;
  };
  const list = descendants(panel(node)).find((element) => element.className === 'references');
  assert.equal(fire(panel(node), 'wheel').prevented, true);
  assert.equal(fire(list, 'wheel').stopped, false);
  list.scrollHeight = 500;
  list.clientHeight = 200;
  assert.equal(fire(list, 'wheel').stopped, true);
  assert.equal(fire(list, 'wheel', { ctrlKey: true }).stopped, false);
  assert.equal(fire(list, 'wheel', { deltaX: 200 }).stopped, false);
  assert.equal(fire(panel(node), 'pointerdown', { button: 0, buttons: 1 }).stopped, true);
  fire(panel(node), 'pointerdown', { button: 1, buttons: 4 });
  fire(panel(node), 'pointermove', { button: -1, buttons: 4 });
  fire(panel(node), 'pointermove', { button: -1, buttons: 1 });
  fire(panel(node), 'pointerup', { button: 1, buttons: 0 });
  assert.equal(fire(panel(node), 'keydown', { key: 'Delete' }).stopped, true);
  assert.deepEqual(canvas.calls, [
    ['processMouseWheel', 'wheel'],
    ['processMouseWheel', 'wheel'],
    ['processMouseWheel', 'wheel'],
    ['processMouseWheel', 'wheel'],
    ['processMouseDown', 'pointerdown'],
    ['processMouseMove', 'pointermove'],
    ['processMouseUp', 'pointerup'],
  ]);
  app.canvas = null;
  assert.equal(
    descendants(panel(node)).some((element) => ['VIDEO', 'AUDIO'].includes(element.tagName)),
    false,
  );
  // Video rows show a static still from the clip start, audio rows a marker; a failed still falls back to a marker.
  const thumbs = () =>
    descendants(panel(node))
      .filter((element) => element.dataset.cardId)
      .map((row) => row.children.find((child) => child.className === 'thumb'));
  assert.equal(thumbs()[1].tagName, 'IMG');
  assert.match(thumbs()[1].src, /\/arisu\/resources\/poster\?.*path=video\.mkv.*at=0/);
  assert.equal(thumbs()[2].tagName, 'SPAN');
  assert.match(thumbs()[2].innerHTML, /<svg/);
  thumbs()[1].onerror();
  assert.equal(thumbs()[1].tagName, 'SPAN');
  assert.match(thumbs()[1].innerHTML, /<svg/);
  // Mixed Browse draws videos as a poster still, falling back to the film glyph, and audio as a waveform glyph.
  const cards = await checkBrowse(button(panel(node), 'Browse References…'), node, 'output:audio', {
    'sound.wav': 'audio',
    'other.wav': 'audio',
    'clip.mkv': 'video',
  });
  assert.deepEqual(marks(cards), [
    ['output:audio/sound.wav', 'true', 'audio'],
    ['output:audio/other.wav', null, 'audio'],
    ['output:audio/clip.mkv', null, 'video'],
  ]);
  const tile = (card) => card.children[0];
  assert.equal(tile(cards[0]).className, 'arisu-browser-tile');
  assert.match(tile(cards[0]).innerHTML, /<svg/);
  assert.equal(tile(cards[2]).className, 'arisu-browser-tile arisu-loading');
  assert.equal(tile(cards[2]).children[0].tagName, 'IMG');
  assert.match(tile(cards[2]).children[0].src, /\/arisu\/resources\/poster\?.*path=audio%2Fclip\.mkv.*at=0.*max=256/);
  tile(cards[2]).children[0].onerror();
  assert.equal(tile(cards[2]).className, 'arisu-browser-tile');
  assert.match(tile(cards[2]).innerHTML, /<svg/);
  let rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[0], 'Mute').onclick();
  assert.equal(state(node).references[0].muted, true);
  assert.deepEqual(counts(node), ['Video 1']);
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[2], 'Move Up').onclick();
  assert.deepEqual(
    state(node).references.map((card) => card.id),
    ['picture', 'sound', 'video'],
  );
  // Dragging marks the source row, the hovered row shows which half the card lands in, and the drop follows it;
  // the video moves above the audio and back below it, so later steps keep the audio card in the middle.
  const cardRows = () => descendants(panel(node)).filter((element) => element.dataset.cardId);
  const grip = (row) => row.children.find((element) => element.className === 'handle');
  const drag = (row) => grip(row).ondragstart({ dataTransfer: { setData() {} } });
  const over = (row, clientY) => {
    row.getBoundingClientRect = () => ({ top: 0, height: 52 });
    row.ondragover({ preventDefault() {}, clientY });
  };
  const drop = (row) => row.ondrop({ preventDefault() {} });
  rows = cardRows();
  drag(rows[2]);
  assert.equal(rows[2].dataset.dragging, '');
  over(rows[0], 10);
  assert.equal(rows[0].dataset.drop, 'before');
  over(rows[1], 10);
  assert.equal(rows[0].dataset.drop, undefined);
  assert.equal(rows[1].dataset.drop, 'before');
  over(rows[2], 10);
  assert.equal(rows[1].dataset.drop, undefined);
  over(rows[0], 40);
  assert.equal(rows[0].dataset.drop, 'after');
  drop(rows[0]);
  assert.deepEqual(
    state(node).references.map((card) => card.id),
    ['picture', 'video', 'sound'],
  );
  assert.equal(rows[0].dataset.drop, undefined);
  assert.equal(rows[2].dataset.dragging, undefined);
  rows = cardRows();
  drag(rows[1]);
  over(rows[2], 40);
  drop(rows[2]);
  assert.deepEqual(
    state(node).references.map((card) => card.id),
    ['picture', 'sound', 'video'],
  );
  rows = cardRows();
  drag(rows[0]);
  grip(rows[0]).ondragend();
  over(rows[1], 10);
  assert.equal(rows[1].dataset.drop, undefined);
  await checkBrowse(button(panel(node), 'Browse References…'), node, 'input:/');
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[1], 'Unmute').onclick();
  assert.deepEqual(counts(node), ['Video 1', 'Audio 1']);
  // Existing card edits are drafts; Cancel and node removal cannot write stale selections.
  api.responses.push(jsonResponse(200, { kind: 'audio', duration: 12, has_audio: true, revision: 'a' }));
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  const editing = button(rows[1], 'Edit audio audio/sound.wav').onclick();
  await settle();
  const dialog = body.children.find((element) => element.tagName === 'DIALOG');
  assert(dialog);
  const end = descendants(dialog).find((element) => element.ariaLabel === 'End Seconds');
  end.value = '8';
  end.onchange();
  button(dialog, 'Cancel').onclick();
  await editing;
  assert.equal(state(node).references[1].clip.end, 5);
  rows = descendants(panel(node)).filter((element) => element.dataset.cardId);
  button(rows[2], 'Remove').onclick();
  await checkBrowse(button(panel(node), 'Browse References…'), node, 'output:audio');
  for (const row of descendants(panel(node)).filter((element) => element.dataset.cardId)) button(row, 'Remove').onclick();
  settings['Arisu.LoadImage.DefaultRoot'] = 'output';
  await checkBrowse(button(panel(node), 'Browse References…'), node, 'output:/');
  definition.prototype.onConfigure.call(node);
  assert.deepEqual(state(node), empty());
  assert.equal(node.properties.arisu_crop_modes, undefined);
  // Three row probes plus the audio edit; resetting to an empty state probes nothing.
  assert.equal(api.calls.filter((call) => call.route.includes('metadata')).length, 4);
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
  // Drive real configure hooks through the frontend-owned restoration context for reload and Undo.
  app.loadGraphData = (graphData) => {
    const saved = graphData.nodes[0];
    const restored = create(JSON.parse(saved.widgets_values[2]));
    widget(restored, 'advertise_resources').value = saved.widgets_values[1];
    restored.properties = structuredClone(saved.properties ?? {});
    app.configuringGraph = true;
    try {
      definition.prototype.onConfigure.call(restored);
    } finally {
      app.configuringGraph = false;
    }
    return restored;
  };
  extension.init();
  const workflow = { isPersisted: true };
  const restore = (saved, context = workflow, advertise = false) =>
    app.loadGraphData(
      {
        nodes: [
          {
            type: TYPE,
            widgets_values: ['16:9 (Widescreen)', advertise, JSON.stringify(saved.resources)],
            properties: saved.properties,
          },
        ],
      },
      true,
      true,
      context,
    );
  // Importing keeps the toggle while still clearing media selections and crop metadata.
  for (const advertise of [true, false]) {
    const imported = await restore({ resources: data, properties: { arisu_crop_modes: { first: 'Free' } } }, 'import.json', advertise);
    assert.equal(widget(imported, 'advertise_resources').value, advertise);
    assert.deepEqual(state(imported), empty());
    assert.equal(imported.properties.arisu_crop_modes, undefined);
    const reopened = await restore({ resources: empty() }, workflow, advertise);
    assert.equal(widget(reopened, 'advertise_resources').value, advertise);
  }
  const cropMenu = (dialog) => descendants(dialog).find((element) => element.className === 'arisu-cropper-ratio');
  const choose = (dialog, ratio) => {
    cropMenu(dialog).value = ratio;
    cropMenu(dialog).onchange();
  };
  const openCrop = async (owner, slot) => {
    api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
    const editing = button(panel(owner), slot ? 'Crop' : 'Edit image ratio.png').onclick();
    await settle();
    return { dialog: body.children.find((element) => element.open), editing };
  };
  const applyCrop = async ({ dialog, editing }) => {
    api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
    button(dialog, 'Apply').onclick();
    await editing;
  };
  for (const slot of ['first', null]) {
    const key = slot ? 'keyframe:first' : 'reference:ratio';
    // Legacy crops open Free even if the pixels or the separate auto-crop basis match a preset.
    for (const crop of [{ left: 2, top: 3, width: 320, height: 180 }, { left: 2, top: 3, width: 210, height: 90 }, null]) {
      const next = state(node);
      const item = { ...card('ratio'), crop, crop_basis_ratio: '16:9 (Widescreen)' };
      if (slot) next.keyframes.first = item;
      else next.references = [item];
      widget(node, 'resources_json').value = JSON.stringify(next);
      delete node.properties.arisu_crop_modes;
      widget(node, 'aspect_ratio').callback();
      await settle();
      const opened = await openCrop(node, slot);
      assert.equal(cropMenu(opened.dialog).value, 'free');
      assert.equal(
        descendants(opened.dialog).find((element) => element.className === 'arisu-cropper-readout').textContent,
        crop ? `${crop.width} × ${crop.height} at ${crop.left}, ${crop.top}` : '800 × 600 at 0, 0',
      );
      await applyCrop(opened);
      assert.deepEqual((slot ? state(node).keyframes.first : state(node).references[0]).crop, crop);
      assert.equal(node.properties.arisu_crop_modes[key].ratio, 'free');
    }
    // Applying stores the actual menu choice, including rounded ratios, full-image crops, and explicit Free over a square.
    for (const ratio of ['1:1', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16', '21:9', 'free']) {
      const opened = await openCrop(node, slot);
      if (ratio === 'free') choose(opened.dialog, '1:1');
      choose(opened.dialog, ratio);
      const undo = [];
      const snapshot = () => JSON.parse(JSON.stringify({ resources: state(node), properties: node.properties }));
      node.graph.beforeChange = () => undo.push(snapshot());
      node.graph.afterChange = () => undo.push(snapshot());
      await applyCrop(opened);
      delete node.graph.beforeChange;
      delete node.graph.afterChange;
      const saved = snapshot();
      assert.equal(saved.properties.arisu_crop_modes[key].ratio, ratio);
      assert.equal(undo.length, 2);
      assert.deepEqual(undo[1], saved);
      if (ratio === '4:3') assert.equal((slot ? state(node).keyframes.first : state(node).references[0]).crop, null);
      if (ratio === '9:16') assert.equal((slot ? state(node).keyframes.first : state(node).references[0]).crop.width, 338);
      // New node instances exercise the serialized state, independent of transient editor caches.
      const restored = await restore(saved);
      for (const close of ['Cancel', 'escape', 'backdrop']) {
        const draft = await openCrop(restored, slot);
        assert.equal(cropMenu(draft.dialog).value, ratio, `${key}: ${ratio}: ${close}`);
        choose(draft.dialog, ratio === '1:1' ? '21:9' : '1:1');
        button(draft.dialog, 'Reset').onclick();
        if (close === 'Cancel') button(draft.dialog, 'Cancel').onclick();
        else if (close === 'escape') draft.dialog.close();
        else {
          draft.dialog.onpointerdown({ target: draft.dialog });
          draft.dialog.onclick({ target: draft.dialog });
        }
        await draft.editing;
        assert.deepEqual(state(restored), saved.resources);
        assert.deepEqual(restored.properties, saved.properties);
      }
      // Undo restores the previous mode and rectangle together.
      const previous = await restore(undo[0]);
      const prior = await openCrop(previous, slot);
      assert.equal(cropMenu(prior.dialog).value, undo[0].properties.arisu_crop_modes[key].ratio);
      button(prior.dialog, 'Cancel').onclick();
      await prior.editing;
    }
    // A changed source revision after Apply discards both draft changes.
    const unchanged = JSON.stringify({ resources: state(node), properties: node.properties });
    const rejected = await openCrop(node, slot);
    choose(rejected.dialog, '21:9');
    api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'changed' }));
    button(rejected.dialog, 'Apply').onclick();
    await rejected.editing;
    assert.equal(JSON.stringify({ resources: state(node), properties: node.properties }), unchanged);
    assert.equal(toastSeverities().at(-1), 'error');
    resetApi();
  }
  // Expected source-change errors above are isolated from the remaining automatic-crop scenario.
  const expectedErrors = toastSeverities().filter((severity) => severity === 'error').length;
  assert.equal(expectedErrors, 2);

  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  widget(node, 'aspect_ratio').value = '1:1 (Square)';
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 100, top: 0, width: 600, height: 600 });
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, '1:1');
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  const editing = button(panel(node), 'Crop').onclick();
  await settle();
  const dialog = body.children.find((element) => element.tagName === 'DIALOG');
  assert(button(dialog, 'Auto-Crop'));
  button(dialog, 'Reset').onclick();
  api.responses.push(jsonResponse(200, { kind: 'image', width: 800, height: 600, revision: 'r' }));
  button(dialog, 'Apply').onclick();
  await editing;
  assert.equal(state(node).keyframes.first.crop, null);
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, 'free');
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.equal(state(node).keyframes.first.crop, null);
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, 'free');
  // The dialog's automatic crop remains a draft until Apply, just like a manual preset or Reset.
  const autoDraft = await openCrop(node, 'first');
  button(autoDraft.dialog, 'Auto-Crop').onclick();
  assert.equal(cropMenu(autoDraft.dialog).value, '1:1');
  button(autoDraft.dialog, 'Cancel').onclick();
  await autoDraft.editing;
  assert.equal(state(node).keyframes.first.crop, null);
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, 'free');
  const autoApplied = await openCrop(node, 'first');
  button(autoApplied.dialog, 'Auto-Crop').onclick();
  await applyCrop(autoApplied);
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, '1:1');
  assert.deepEqual(state(node).keyframes.first.crop, { left: 100, top: 0, width: 600, height: 600 });
  button(panel(node), 'Mute').onclick();
  widget(node, 'aspect_ratio').value = '16:9 (Widescreen)';
  widget(node, 'aspect_ratio').callback();
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 0, top: 75, width: 800, height: 450 });
  assert.equal(state(node).keyframes.first.muted, true);
  const before = widget(node, 'resources_json').value;
  definition.prototype.onExecuted.call(node, { arisu_resources: [{ state: 'obsolete', keyframes: {} }] });
  assert.equal(widget(node, 'resources_json').value, before);
  // A wired ratio reads the upstream settings selector and follows its changes; a selector that is itself wired defers to execution.
  const status = () => descendants(panel(node)).find((element) => element.tagName === 'OUTPUT').textContent;
  const settings = makeNode({
    id: 2,
    type: 'ArisuMiniMaxH3VideoSettings',
    graph: app.graph,
    widgets: [{ name: 'aspect_ratio', value: '1:1 (Square)' }],
    outputs: ['video_settings', 'width', 'height', 'length', 'aspect_ratio'],
  });
  app.graph.links = { 7: { origin_id: 2, origin_slot: 4 } };
  node.inputs.push({ name: 'aspect_ratio', link: 7, widget: { name: 'aspect_ratio' } });
  definition.prototype.onConnectionsChange.call(node);
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 100, top: 0, width: 600, height: 600 });
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, '1:1');
  assert.equal(status(), '');
  widget(settings, 'aspect_ratio').value = '16:9 (Widescreen)';
  node.arisuRefreshAspect();
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 0, top: 75, width: 800, height: 450 });
  settings.inputs.push({ name: 'aspect_ratio', link: 8 });
  definition.prototype.onConnectionsChange.call(node);
  await settle();
  assert.deepEqual(state(node).keyframes.first.crop, { left: 0, top: 75, width: 800, height: 450 });
  assert.equal(status(), 'Aspect ratio will resolve during execution');
  // Unchanged execution feedback preserves a manual Free choice; a changed basis records the ratio actually applied.
  const manual = await openCrop(node, 'first');
  choose(manual.dialog, 'free');
  await applyCrop(manual);
  const feedback = (basis, crop) => ({
    arisu_resources: [
      {
        state: widget(node, 'resources_json').value,
        aspect_ratio: basis,
        keyframes: { first: { id: state(node).keyframes.first.id, crop, crop_basis_ratio: basis }, last: null },
      },
    ],
  });
  definition.prototype.onExecuted.call(node, feedback('16:9 (Widescreen)', [0, 75, 800, 450]));
  await settle();
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, 'free');
  definition.prototype.onExecuted.call(node, feedback('9:16 (Portrait Widescreen)', [231, 0, 337, 600]));
  await settle();
  assert.equal(node.properties.arisu_crop_modes['keyframe:first'].ratio, '9:16');
  const automatic = await openCrop(node, 'first');
  assert.equal(cropMenu(automatic.dialog).value, '9:16');
  assert.match(descendants(automatic.dialog).find((element) => element.className === 'arisu-cropper-readout').textContent, /^337 × 600/);
  button(automatic.dialog, 'Cancel').onclick();
  await automatic.editing;
  // Imported selections drop metadata before configuration; an old dialog cannot put it back after reset.
  const imported = await restore({ resources: state(node), properties: node.properties }, null);
  assert.deepEqual(state(imported), empty());
  assert.equal(imported.properties.arisu_crop_modes, undefined);
  const stale = await openCrop(node, 'first');
  choose(stale.dialog, '21:9');
  definition.prototype.onConfigure.call(node);
  button(stale.dialog, 'Apply').onclick();
  await stale.editing;
  assert.deepEqual(state(node), empty());
  assert.equal(node.properties.arisu_crop_modes, undefined);
  definition.prototype.onRemoved.call(node);
  assert(!body.children.some((element) => element.open));
  assert.equal(toastSeverities().filter((severity) => severity === 'error').length, expectedErrors);
  assert(!toastSeverities().includes('info'));
});
