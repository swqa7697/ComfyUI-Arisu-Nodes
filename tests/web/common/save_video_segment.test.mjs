// Arisu Save Video Segment's widgets: the CRF range and preset that follow the codec without
// rewriting a saved value, and the take context that never leaves the node through the workflow.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { app, extensionNamed, resetApp } from '../support/app.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/save_video_segment.js';

const WIDGETS = { project_prefix: '', clip_name: 'clip', filename_prefix: '', codec: 'h264', crf: 18, take_context: '' };

const Saver = { prototype: {} };
extensionNamed('Arisu.Common.SaveVideoSegment').beforeRegisterNodeDef(Saver, { name: 'ArisuSaveVideoSegment' });

/** A node as LiteGraph builds it from the definition: a widget and a socket per value input, plus the video socket. */
function makeSaver() {
  const node = makeNode({
    id: 4,
    type: 'ArisuSaveVideoSegment',
    graph: app.graph,
    widgets: Object.entries(WIDGETS).map(([name, value]) => ({ name, value, options: {} })),
    inputs: [{ name: 'video', type: 'VIDEO' }, ...Object.keys(WIDGETS).map((name) => ({ name }))],
    outputs: ['video'],
  });
  Saver.prototype.onNodeCreated.call(node);
  return node;
}

function widget(node, name) {
  return node.widgets.find((candidate) => candidate.name === name);
}

/** A user edit: LiteGraph writes the value, then calls the widget's callback. */
function choose(node, name, value) {
  const target = widget(node, name);
  target.value = value;
  target.callback?.(value);
}

function sockets(node) {
  return node.inputs.map((input) => input.name);
}

test('the saver follows the codec with its CRF range and keeps the take context out of the workflow', () => {
  resetApp(makeGraph());
  const node = makeSaver();
  const crf = widget(node, 'crf');
  const context = widget(node, 'take_context');

  // created: H.264's range on the CRF widget, the context hidden on both renderers and without a socket
  assert.equal(crf.options.max, 51);
  assert.match(crf.label, /51/);
  assert.equal(context.hidden && context.options.hidden, true);
  assert.deepEqual(sockets(node), ['video', 'project_prefix', 'clip_name', 'filename_prefix', 'codec', 'crf']);

  // an untouched preset follows the codec to that codec's own preset
  choose(node, 'codec', 'av1');
  assert.deepEqual([crf.value, crf.options.max], [24, 63]);
  assert.match(crf.label, /63/);
  choose(node, 'codec', 'h265');
  assert.deepEqual([crf.value, crf.options.max], [20, 51]);

  // a value the user chose is kept, lowered only when the new codec's range ends below it
  choose(node, 'codec', 'av1');
  choose(node, 'crf', 60);
  choose(node, 'codec', 'h264');
  assert.deepEqual([crf.value, crf.options.max], [51, 51]);
  choose(node, 'codec', 'h265');
  assert.equal(crf.value, 51, 'a custom value does not become a preset');
  choose(node, 'crf', 30);
  choose(node, 'codec', 'av1');
  assert.equal(crf.value, 30);

  // loading a workflow: the saved codec sets the range, the saved CRF is not rewritten,
  // and a context that arrived with the file or over a wire is dropped
  widget(node, 'codec').value = 'av1';
  crf.value = 60;
  context.value = '{"segment":"forged"}';
  context.hidden = false;
  node.inputs.push({ name: 'take_context', type: 'STRING', link: 9, widget: { name: 'take_context' } });
  Saver.prototype.onConfigure.call(node);
  assert.deepEqual([crf.value, crf.options.max], [60, 63]);
  assert.equal(context.value, '');
  assert.equal(context.hidden && context.options.hidden, true);
  assert.equal(sockets(node).includes('take_context'), false);

  // a value written after the load still serializes empty: only a submitted prompt carries a context
  context.value = '{"segment":"typed"}';
  assert.equal(context.serializeValue(node, 5), '');

  // the next codec change starts from the loaded codec: 60 is not AV1's preset, so it is only lowered
  choose(node, 'codec', 'h264');
  assert.deepEqual([crf.value, crf.options.max], [51, 51]);

  // a codec this script does not know leaves the CRF widget as it was
  choose(node, 'codec', 'prores');
  assert.deepEqual([crf.value, crf.options.max], [51, 51]);
});
