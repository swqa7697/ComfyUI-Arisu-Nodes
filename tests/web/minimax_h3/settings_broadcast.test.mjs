// MiniMax H3 Video Settings advertising: the one-advertiser rule, the hybrid
// widgets it hands over, and the links injected into the queued prompt.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, toastSeverities } from '../support/app.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/minimax_h3/settings_broadcast.js';

const SETTINGS = 'ArisuMiniMaxH3VideoSettings';
const SETTINGS_UPSCALE = 'ArisuMiniMaxH3VideoSettingsUpscale';
const HYBRID = 'ArisuMiniMaxH3HybridToVideo';
const HYBRID_ADVANCED = 'ArisuMiniMaxH3HybridToVideoAdvanced';
// the widgets and outputs the backend declares: the plain nodes carry the size keys, the
// Upscale settings node and the Advanced hybrid add the target size
const SIZE_KEYS = ['width', 'height', 'length'];
const TARGET_KEYS = ['target_width', 'target_height'];

const extension = extensionNamed('Arisu.MiniMaxH3.SettingsBroadcast');
const prototypes = {};
for (const name of [SETTINGS, SETTINGS_UPSCALE, HYBRID, HYBRID_ADVANCED, 'ArisuMiniMaxH3ResourceStudio']) {
  const nodeType = { prototype: {} };
  extension.beforeRegisterNodeDef(nodeType, { name });
  prototypes[name] = nodeType.prototype;
}
app.graphToPrompt = async function () {
  return structuredClone(this.promptForTest);
};
extension.setup();

function keysOf(type) {
  return type === SETTINGS || type === HYBRID ? SIZE_KEYS : [...SIZE_KEYS, ...TARGET_KEYS];
}

/** A settings node LiteGraph just added to `graph`, its switch already at `advertise` (a duplicate restores widgets first). */
function addSettings(graph, id, type = SETTINGS, advertise = false) {
  const node = makeNode({ id, type, graph, widgets: [{ name: 'advertise', value: advertise }], outputs: keysOf(type) });
  prototypes[type].onAdded.call(node);
  return node;
}

/** A hybrid node LiteGraph just added to `graph`, with links into the named inputs. */
function addHybrid(graph, id, type = HYBRID, links = []) {
  const keys = keysOf(type);
  const node = makeNode({
    id,
    type,
    graph,
    widgets: keys.map((name) => ({ name, value: 1 })),
    inputs: keys.map((name) => ({ name, link: links.includes(name) ? 1 : null })),
  });
  prototypes[type].onAdded.call(node);
  return node;
}

function advertiseWidget(node) {
  return node.widgets.find((widget) => widget.name === 'advertise');
}

/** The user flips the switch: the widget takes the value, then its callback runs. */
function flip(node, on) {
  const widget = advertiseWidget(node);
  widget.value = on;
  widget.callback.call(widget, on);
}

function disabledWidgets(node) {
  return node.widgets.filter((widget) => widget.disabled).map((widget) => widget.name);
}

function linkedInputs(node) {
  return node.inputs.filter((input) => input.link != null).map((input) => input.name);
}

function inputIndex(node, name) {
  return node.inputs.findIndex((input) => input.name === name);
}

test('one settings node advertises at a time: a later switch wins, a pasted one is switched off, a load keeps the first', () => {
  const graph = makeGraph();
  resetApp(graph);
  const first = addSettings(graph, 1);
  const second = addSettings(graph, 2);
  const hybrid = addHybrid(graph, 3);
  // switching the first on hands over the hybrid's size widgets
  flip(first, true);
  assert.deepEqual(disabledWidgets(hybrid), SIZE_KEYS);
  // switching the second on takes the slot: the first is switched off, with a warning
  flip(second, true);
  assert.equal(advertiseWidget(first).value, false);
  assert.equal(advertiseWidget(second).value, true);
  assert.deepEqual(toastSeverities(), ['warn']);
  assert.deepEqual(disabledWidgets(hybrid), SIZE_KEYS);
  // switching it off releases the widgets
  flip(second, false);
  assert.deepEqual(disabledWidgets(hybrid), []);
  // a duplicate arrives with its switch already on: switched off on arrival
  const duplicate = addSettings(graph, 4, SETTINGS, true);
  assert.equal(advertiseWidget(duplicate).value, false);
  assert.deepEqual(toastSeverities(), ['warn', 'info']);
  // a paste restores the switch after the node was added: onConfigure catches it
  const pasted = addSettings(graph, 5);
  advertiseWidget(pasted).value = true;
  prototypes[SETTINGS].onConfigure.call(pasted);
  assert.equal(advertiseWidget(pasted).value, false);
  // a loading workflow keeps every switch until afterConfigureGraph, which keeps the first in node order
  const loaded = makeGraph();
  resetApp(loaded);
  app.configuringGraph = true;
  const kept = addSettings(loaded, 1, SETTINGS_UPSCALE, true);
  const demoted = addSettings(loaded, 2, SETTINGS, true);
  const advanced = addHybrid(loaded, 3, HYBRID_ADVANCED, ['width']);
  // Do not mutate partially configured workflow links before restoration finishes.
  assert.deepEqual(linkedInputs(advanced), ['width']);
  assert.deepEqual(disabledWidgets(advanced), []);
  assert.equal(advertiseWidget(demoted).value, true);
  app.configuringGraph = false;
  extension.afterConfigureGraph();
  assert.equal(advertiseWidget(kept).value, true);
  assert.equal(advertiseWidget(demoted).value, false);
  assert.deepEqual(disabledWidgets(advanced), [...SIZE_KEYS, ...TARGET_KEYS]);
  assert.deepEqual(linkedInputs(advanced), []);
});

test('the handed-over widgets are the keys both nodes carry: greyed, unlinked, and released when the advertiser leaves', async () => {
  const graph = makeGraph();
  resetApp(graph);
  const settings = addSettings(graph, 1);
  flip(settings, true);
  // an Advanced hybrid arrives wired on width and target_width: the plain settings node hands over the size keys only
  const hybrid = addHybrid(graph, 2, HYBRID_ADVANCED, ['width', 'target_width']);
  assert.deepEqual(disabledWidgets(hybrid), SIZE_KEYS);
  assert.deepEqual(linkedInputs(hybrid), ['target_width']);
  assert.deepEqual(toastSeverities(), ['info']);
  // a hybrid inside a subgraph is left alone
  const inner = addHybrid(makeGraph('sub'), 3, HYBRID, ['width']);
  assert.deepEqual(disabledWidgets(inner), []);
  assert.deepEqual(linkedInputs(inner), ['width']);
  // a muted advertiser keeps the slot but hands nothing over; the widgets update on the next refresh
  settings.mode = 2;
  flip(settings, true);
  assert.deepEqual(disabledWidgets(hybrid), []);
  settings.mode = 0;
  flip(settings, true);
  assert.deepEqual(disabledWidgets(hybrid), SIZE_KEYS);
  // removing the advertiser fires onRemoved while it is still listed; the release lands a tick later
  prototypes[SETTINGS].onRemoved.call(settings);
  graph.nodes.splice(graph.nodes.indexOf(settings), 1);
  assert.deepEqual(disabledWidgets(hybrid), SIZE_KEYS);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(disabledWidgets(hybrid), []);
});

test("a link into a handed-over widget is refused, and chained hooks keep either side's veto", () => {
  const graph = makeGraph();
  resetApp(graph);
  const settings = addSettings(graph, 1);
  flip(settings, true);
  const hybrid = addHybrid(graph, 2, HYBRID_ADVANCED);
  const onConnectInput = prototypes[HYBRID_ADVANCED].onConnectInput;
  // width comes from the advertiser: refused with a warning; target_width is free
  assert.equal(onConnectInput.call(hybrid, inputIndex(hybrid, 'width')), false);
  assert.deepEqual(toastSeverities(), ['warn']);
  assert.notEqual(onConnectInput.call(hybrid, inputIndex(hybrid, 'target_width')), false);
  // with advertising off nothing is refused
  flip(settings, false);
  assert.notEqual(onConnectInput.call(hybrid, inputIndex(hybrid, 'width')), false);
  // a hook installed before ours keeps its own veto (ours never runs: no warning), and its
  // result stands when neither side refuses
  const vetoing = { prototype: { onConnectInput: () => false } };
  const allowing = { prototype: { onConnectInput: () => true } };
  extension.beforeRegisterNodeDef(vetoing, { name: HYBRID });
  extension.beforeRegisterNodeDef(allowing, { name: HYBRID });
  const plain = addHybrid(graph, 3, HYBRID);
  flip(settings, true);
  assert.equal(vetoing.prototype.onConnectInput.call(plain, inputIndex(plain, 'width')), false);
  assert.deepEqual(toastSeverities(), ['warn']);
  assert.equal(allowing.prototype.onConnectInput.call(plain, inputIndex(plain, 'width')), false);
  assert.deepEqual(toastSeverities(), ['warn', 'warn']);
  flip(settings, false);
  assert.equal(allowing.prototype.onConnectInput.call(plain, inputIndex(plain, 'width')), true);
});

test("queueing a prompt points the handed-over widgets at the advertiser's outputs, and rejects a missing source", async () => {
  const graph = makeGraph();
  resetApp(graph);
  resetApi();
  const settings = addSettings(graph, 1, SETTINGS_UPSCALE);
  flip(settings, true);
  const hybrid = addHybrid(graph, 2);
  const advanced = addHybrid(graph, 3, HYBRID_ADVANCED);
  const muted = addHybrid(graph, 4);
  muted.mode = 2;
  addHybrid(graph, 5);
  const entry = (inputs) => ({ class_type: 'hybrid', inputs });
  // the advertiser is in the run: every active hybrid in the prompt gets one link per handed-over key,
  // to the advertiser's output of that name; the muted one and the one outside the prompt are untouched
  const output = {
    [settings.id]: entry({}),
    [hybrid.id]: entry({ width: 1, height: 1, length: 1, clip: ['9', 0] }),
    [advanced.id]: entry({ width: 1, target_width: 1 }),
    [muted.id]: entry({ width: 1 }),
  };
  const result = await api.queuePrompt(0, { output, workflow: {} });
  assert.deepEqual(output[hybrid.id].inputs, { width: ['1', 0], height: ['1', 1], length: ['1', 2], clip: ['9', 0] });
  assert.deepEqual(output[advanced.id].inputs, {
    width: ['1', 0],
    height: ['1', 1],
    length: ['1', 2],
    target_width: ['1', 3],
    target_height: ['1', 4],
  });
  assert.deepEqual(output[muted.id].inputs, { width: 1 });
  assert.deepEqual(toastSeverities(), []);
  // the call still reaches the frontend's queuePrompt with the same prompt, and its answer comes back
  assert.equal(result, 'queued');
  assert.equal(api.queued.length, 1);
  assert.equal(api.queued[0].prompt.output, output);
  // the advertiser is not in the run (muted or bypassed): nothing is injected, one warning
  const without = { [hybrid.id]: entry({ width: 1 }), [advanced.id]: entry({ width: 1 }) };
  await assert.rejects(api.queuePrompt(0, { output: without }), /absent/);
  assert.deepEqual(without[hybrid.id].inputs, { width: 1 });
  assert.deepEqual(without[advanced.id].inputs, { width: 1 });
  assert.deepEqual(toastSeverities(), []);
  // a call without a prompt passes straight through
  await api.queuePrompt(0, undefined);
  assert.equal(api.queued.length, 2);
  // Both ownership categories coexist, and API exports contain real dependencies.
  resetApp(makeGraph());
  resetApi();
  const root = app.graph;
  const studio = makeNode({
    id: 10,
    type: 'ArisuMiniMaxH3ResourceStudio',
    graph: root,
    widgets: [
      { name: 'advertise', value: false },
      { name: 'aspect_ratio', value: '16:9 (Widescreen)' },
    ],
    outputs: ['resources'],
  });
  const studioHooks = prototypes[studio.type];
  studioHooks.onAdded.call(studio);
  const consumer = makeNode({
    id: 11,
    type: HYBRID,
    graph: root,
    widgets: SIZE_KEYS.map((name) => ({ name, value: 64 })),
    inputs: [
      { name: 'clip', link: 90 },
      { name: 'first_frame', link: 91 },
      { name: 'ref_images.ref_image_0', link: 92 },
      { name: 'resources' },
    ],
  });
  prototypes[HYBRID].onAdded.call(consumer);
  flip(studio, true);
  assert.equal(consumer.inputs.find((input) => input.name === 'resources').disabled, true);
  assert.equal(prototypes[HYBRID].onConnectInput.call(consumer, inputIndex(consumer, 'resources')), false);
  app.promptForTest = {
    workflow: { links: [] },
    output: {
      10: { class_type: studio.type, inputs: {} },
      11: { class_type: HYBRID, inputs: { clip: ['90', 0], 'ref_images.ref_image_0': ['92', 0] } },
    },
  };
  const exported = await app.graphToPrompt();
  assert.deepEqual(exported.output[11].inputs, { clip: ['90', 0], resources: ['10', 0] });
  assert.deepEqual(exported.workflow.links, []);
  assert.deepEqual(
    consumer.inputs.map((input) => input.name),
    ['clip', 'resources'],
  );
  await api.queuePrompt(0, exported);
  assert.deepEqual(exported.output[11].inputs.resources, ['10', 0]);
  studio.mode = 2;
  assert.equal(consumer.inputs.find((input) => input.name === 'resources').disabled, false);
  assert(consumer.inputs.some((input) => input.name === 'first_frame' && input.link === null));
  assert.equal(consumer.inputs.find((input) => input.name === 'clip').link, 90);
  studio.mode = 0;
  await app.graphToPrompt();
  flip(studio, false);
  assert(consumer.inputs.some((input) => input.name === 'ref_images.ref_image_0'));
  // An explicit source pruned by the serializer is an error, never an empty bundle.
  root.links = { 100: { origin_id: 10 } };
  consumer.inputs.find((input) => input.name === 'resources').link = 100;
  app.promptForTest = { workflow: { links: [] }, output: { 11: { class_type: HYBRID, inputs: {} } } };
  await assert.rejects(app.graphToPrompt(), /explicitly connected/);
  consumer.inputs.find((input) => input.name === 'resources').link = null;
  flip(studio, true);
  app.promptForTest = { workflow: { links: [] }, output: { 10: { inputs: { upstream: ['11', 0] } }, 11: { inputs: {} } } };
  await assert.rejects(app.graphToPrompt(), /cycle/);
});
