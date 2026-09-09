// Path Builder's field row, driven the way LiteGraph drives it: onNodeCreated and
// onConfigure on a node double, clicks through the button-row widget from widgets.js.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { extensionNamed, resetApp } from '../support/app.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/path_builder.js';

const FIELDS = 4;
const COUNT_PROPERTY = 'arisuSegments';
// the stock button widget's margin and the gap between the row's cells (widgets.js)
const MARGIN = 15;
const GAP = 4;

const PathBuilder = { prototype: {} };
extensionNamed('Arisu.Common.PathBuilder').beforeRegisterNodeDef(PathBuilder, { name: 'ArisuPathBuilder' });

/** A node as the backend declares it: every field's widget and socket, before any hook ran. */
function makePathNode({ values = {}, links = [] } = {}) {
  const names = Array.from({ length: FIELDS }, (_, index) => `segment_${index + 1}`);
  return makeNode({
    id: 1,
    type: 'ArisuPathBuilder',
    widgets: names.map((name) => ({ name, value: values[name] ?? '' })),
    inputs: names.map((name) => ({ name, shape: 7, link: links.includes(name) ? 9 : null })),
  });
}

function visibleFields(node) {
  return node.widgets.filter((widget) => widget.name.startsWith('segment_') && !widget.hidden).map((widget) => widget.name);
}

function socketNames(node) {
  return node.inputs.map((input) => input.widget?.name).filter((name) => name?.startsWith('segment_'));
}

function buttonRow(node) {
  return node.widgets.find((widget) => widget.type === 'arisu_button_row');
}

/** Press the labelled cell of the button row, at its centre. */
function click(node, label) {
  const row = buttonRow(node);
  const labels = row.name.split(' / ');
  const cell = (node.size[0] - 2 * MARGIN - GAP * (labels.length - 1)) / labels.length;
  return row.mouse({ type: 'pointerdown' }, [MARGIN + labels.indexOf(label) * (cell + GAP) + cell / 2, 0], node);
}

test('a fresh node shows one field; the row grows and shrinks it, clamped to the declared fields', () => {
  resetApp(makeGraph());
  const node = makePathNode();
  // creation: one visible field with its socket, the other fields hidden and socketless
  PathBuilder.prototype.onNodeCreated.call(node);
  assert.deepEqual(visibleFields(node), ['segment_1']);
  assert.deepEqual(socketNames(node), ['segment_1']);
  assert.equal(node.properties[COUNT_PROPERTY], 1);
  // the row is a canvas-only control: it never lands in the saved workflow
  assert.equal(buttonRow(node).serialize, false);
  // the canvas reports the press and the release; only the press acts
  assert.equal(buttonRow(node).mouse({ type: 'pointerup' }, [MARGIN, 0], node), false);
  assert.deepEqual(visibleFields(node), ['segment_1']);
  // two "+ field" presses show three fields, each with a socket
  assert.equal(click(node, '+ field'), true);
  click(node, '+ field');
  assert.deepEqual(visibleFields(node), ['segment_1', 'segment_2', 'segment_3']);
  assert.deepEqual(socketNames(node), ['segment_1', 'segment_2', 'segment_3']);
  // "- field" stops at one field
  for (let press = 0; press < 5; press++) click(node, '- field');
  assert.deepEqual(visibleFields(node), ['segment_1']);
  assert.equal(node.properties[COUNT_PROPERTY], 1);
  // "+ field" stops at the last declared field and stores the clamped count
  for (let press = 0; press < 10; press++) click(node, '+ field');
  assert.equal(visibleFields(node).length, FIELDS);
  assert.equal(node.properties[COUNT_PROPERTY], FIELDS);
});

test('a hidden field is cleared and loses its socket; shown again it gets the socket and its descriptor back', () => {
  resetApp(makeGraph());
  const node = makePathNode();
  PathBuilder.prototype.onNodeCreated.call(node);
  click(node, '+ field');
  click(node, '+ field');
  const third = node.widgets.find((widget) => widget.name === 'segment_3');
  third.value = 'clips';
  const descriptor = node.inputs.find((input) => input.widget.name === 'segment_3').widget;
  // shrinking past the third field clears its text, so it never reaches the join, and removes its socket
  click(node, '- field');
  assert.equal(third.hidden, true);
  assert.equal(third.value, '');
  assert.deepEqual(socketNames(node), ['segment_1', 'segment_2']);
  // growing back restores the socket with the descriptor it had, cloned from a surviving socket
  click(node, '+ field');
  const restored = node.inputs.find((input) => input.widget.name === 'segment_3');
  assert.equal(restored.widget, descriptor);
  assert.equal(restored.type, node.inputs[0].type);
  assert.equal(restored.shape, node.inputs[0].shape);
  assert.equal(third.hidden, false);
});

test('onConfigure raises the stored count to cover every field holding text or a link', () => {
  const cases = [
    { name: 'nothing beyond the count', stored: 1, values: {}, links: [], expected: 1 },
    { name: 'text beyond the count', stored: 2, values: { segment_3: ' x ' }, links: [], expected: 3 },
    { name: 'whitespace is not text', stored: 1, values: { segment_2: '   ' }, links: [], expected: 1 },
    { name: 'a link beyond the count', stored: 1, values: {}, links: ['segment_4'], expected: 4 },
    { name: 'a stored count above the text', stored: 3, values: { segment_2: 'a' }, links: [], expected: 3 },
    { name: 'an unreadable stored count', stored: 'junk', values: {}, links: [], expected: 1 },
  ];
  for (const { name, stored, values, links, expected } of cases) {
    resetApp(makeGraph());
    // configure() has restored properties, widget values, and sockets before it calls the hook
    const node = makePathNode({ values, links });
    node.properties[COUNT_PROPERTY] = stored;
    PathBuilder.prototype.onConfigure.call(node);
    assert.equal(node.properties[COUNT_PROPERTY], expected, `case=${name}`);
    assert.equal(visibleFields(node).length, expected, `case=${name}`);
    assert.equal(socketNames(node).length, expected, `case=${name}`);
  }
});
