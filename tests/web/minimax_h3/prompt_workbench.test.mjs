import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentStatus } from '../../../web/js/minimax_h3/agent_settings.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/minimax_h3/prompt_workbench.js';

const TYPE = 'ArisuMiniMaxH3PromptWorkbench';
const definition = { prototype: {} };
extensionNamed('Arisu.MiniMaxH3.PromptWorkbench').beforeRegisterNodeDef(definition, { name: TYPE });
const widget = (node, name) => node.widgets.find((item) => item.name === name);
const panel = (node) => widget(node, 'workbench').element;
const find = (root, label) =>
  descendants(root).find((item) => item.ariaLabel === label) ?? descendants(root).find((item) => item.textContent === label);
const settle = () => new Promise((resolve) => setImmediate(resolve));

test('Workbench keeps finalized text independent of setup, source notes and reviewed or late drafts', async () => {
  resetApp(makeGraph());
  resetApi();
  resetDom();
  const graph = app.graph;
  let changes = 0;
  graph.beforeChange = () => changes++;
  graph.afterChange = () => {};
  const node = makeNode({
    id: 1,
    type: TYPE,
    graph,
    widgets: Object.entries({
      agent: 'codex',
      skill: 'bundled:with-ref',
      context_length: '22',
      audio_context_length: 24,
      motion_notes: '',
      reference_notes: '{}',
      trigger_words: '',
      requirements: '',
      finalized_prompt: 'keep',
      prepare_job: 'stale',
    }).map(([name, value]) => ({ name, value })),
    inputs: ['video_settings', 'resources', 'context_latent', 'vae'].map((name) => ({ name })),
  });
  api.responses.push(jsonResponse(200, { docker: false }));
  definition.prototype.onNodeCreated.call(node);
  try {
    await settle();
    assert.equal(widget(node, 'prepare_job').value, '');
    assert.equal(descendants(panel(node)).find((item) => item.className === 'generation').disabled, true);
    const final = find(panel(node), 'Finalized prompt');
    assert.equal(final.tagName, 'TEXTAREA');
    final.value = 'manual';
    final.oninput();
    assert.equal(widget(node, 'finalized_prompt').value, 'manual');
    assert.equal(descendants(panel(node)).filter((item) => item.tagName === 'SELECT').length, 3);

    api.responses.push(jsonResponse(200, { docker: true, agents: { codex: { ready: false } } }));
    await agentStatus(true);
    await node.arisuRefreshSources();
    await settle();
    assert(find(panel(node), 'Setup') && find(panel(node), 'Generate prompt').disabled);
    assert(find(panel(node), 'Agent activity').disabled);

    const data = {
      version: 1,
      keyframes: { first: { id: 'key', path: 'key.png' }, last: null },
      references: [
        { id: 'a', root: 'input', path: 'a.png', kind: 'image' },
        { id: 'b', root: 'input', path: 'b.webm', kind: 'video' },
        { id: 'muted', root: 'input', path: 'muted.wav', kind: 'audio', muted: true },
      ],
    };
    const studio = makeNode({
      id: 2,
      type: 'ArisuMiniMaxH3ResourceStudio',
      graph,
      widgets: [
        { name: 'resources_json', value: JSON.stringify(data) },
        { name: 'advertise_resources', value: false },
      ],
    });
    graph.links = { 10: { origin_id: 2, origin_slot: 0 } };
    node.inputs.find((item) => item.name === 'resources').link = 10;
    definition.prototype.onConnectionsChange.call(node);
    await settle();
    const note = find(panel(node), 'Notes for a.png');
    assert(note && !find(panel(node), 'Notes for key.png') && !find(panel(node), 'Notes for muted.wav'));
    note.value = 'red coat';
    note.oninput();
    data.references.reverse();
    widget(studio, 'resources_json').value = JSON.stringify(data);
    node.arisuRefreshSources();
    await settle();
    assert.equal(find(panel(node), 'Notes for a.png').value, 'red coat');
    data.references.find((item) => item.id === 'a').path = 'replacement.png';
    widget(studio, 'resources_json').value = JSON.stringify(data);
    node.arisuRefreshSources();
    await settle();
    assert.equal(find(panel(node), 'Notes for replacement.png').value, '');
    // Notes still resolve when a root Studio feeds an explicit subgraph input.
    const inner = makeGraph('inner');
    inner.beforeChange = graph.beforeChange;
    inner.afterChange = graph.afterChange;
    graph.nodes.splice(graph.nodes.indexOf(node), 1);
    node.graph = inner;
    inner.nodes.push(node);
    const scope = makeNode({ id: 20, type: 'Subgraph', graph, inputs: [{ name: 'resources', link: 10 }] });
    scope.subgraph = inner;
    scope.getInnerNodes = () => [{ node, id: '20:1', subgraphNodePath: [20] }];
    inner.links = { 50: { originIsIoNode: true, origin_slot: 0 } };
    node.inputs.find((item) => item.name === 'resources').link = 50;
    definition.prototype.onConnectionsChange.call(node);
    await settle();
    assert(find(panel(node), 'Notes for replacement.png'));
    node.inputs.find((item) => item.name === 'context_latent').link = 11;
    definition.prototype.onConnectionsChange.call(node);
    assert.equal(descendants(panel(node)).find((item) => item.className === 'motion').disabled, true);
    node.inputs.find((item) => item.name === 'vae').link = 12;
    definition.prototype.onConnectionsChange.call(node);
    assert.equal(descendants(panel(node)).find((item) => item.className === 'motion').disabled, false);

    api.responses.push(jsonResponse(200, { docker: true, agents: { codex: { ready: true } } }));
    await agentStatus(true);
    node.arisuRefreshSources();
    await settle();
    app.graphToPrompt = async () => ({ output: { '20:1': { class_type: TYPE, inputs: { finalized_prompt: 'manual' } } } });
    api.responses.push(jsonResponse(202, { id: 'job1' }), jsonResponse(200, { state: 'complete', draft: 'first draft' }));
    find(panel(node), 'Generate prompt').onclick();
    await settle();
    await settle();
    assert.equal(widget(node, 'finalized_prompt').value, 'manual');
    assert(find(body, 'Generated prompt draft'));
    find(body, 'Discard').onclick();
    assert.equal(widget(node, 'finalized_prompt').value, 'manual');

    api.responses.push(jsonResponse(202, { id: 'job2' }), jsonResponse(200, { state: 'complete', draft: 'second draft' }));
    find(panel(node), 'Generate prompt').onclick();
    await settle();
    await settle();
    find(body, 'Generated prompt draft').value = 'edited draft';
    const before = changes;
    find(body, 'Apply').onclick();
    assert.equal(widget(node, 'finalized_prompt').value, 'edited draft');
    assert.equal(changes, before + 1);

    let finish;
    api.responses.push(
      jsonResponse(202, { id: 'job3' }),
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    find(panel(node), 'Generate prompt').onclick();
    await settle();
    await settle();
    assert.equal(find(panel(node), 'Agent activity').disabled, false);
    api.responses.push(
      jsonResponse(200, {
        session: 'job3',
        cursor: 1,
        lines: [
          JSON.stringify({ item: { type: 'reasoning', text: 'Inspecting selected reference' } }),
          'More reasoning. '.repeat(100),
          '[tool] workbench.get_context',
          '{',
          '  "references": []',
          '}',
          JSON.stringify({ message: { content: [{ type: 'thinking', thinking: 'Keep the warm lighting' }] } }),
          JSON.stringify({ event: { delta: { type: 'thinking_delta', thinking: 'Preserve the silhouette' } } }),
          '[agent] <img src=x onerror=alert(1)>',
          '{malformed json',
        ],
        state: 'running',
      }),
    );
    find(panel(node), 'Agent activity').onclick();
    await settle();
    const activity = find(body, 'Generation activity');
    assert(activity);
    assert(find(activity, '[analysis] Inspecting selected reference'));
    assert.equal(find(activity, 'More reasoning. '.repeat(100)).parent.parent, activity);
    assert(find(activity, '[analysis] Keep the warm lighting'));
    assert(find(activity, '[analysis] Preserve the silhouette'));
    assert(find(activity, '[agent] <img src=x onerror=alert(1)>'));
    assert(find(activity, '{malformed json'));
    const details = descendants(activity).find((item) => item.tagName === 'DETAILS');
    assert(details && !details.open);
    assert(find(details, '  "references": []'));

    api.responses.push(jsonResponse(200, { released: true }), jsonResponse(200, { released: true }));
    widget(node, 'finalized_prompt').value = 'restored';
    widget(node, 'prepare_job').value = 'imported';
    definition.prototype.onConfigure.call(node);
    finish(jsonResponse(200, { state: 'complete', draft: 'late draft' }));
    await settle();
    assert.equal(widget(node, 'prepare_job').value, '');
    assert.equal(widget(node, 'finalized_prompt').value, 'restored');
    assert(!find(body, 'Generated prompt draft'));
    assert(!find(body, 'Generation activity'));
    assert(find(panel(node), 'Agent activity').disabled);
  } finally {
    api.responses.push(jsonResponse(200, { released: true }));
    definition.prototype.onRemoved.call(node);
    await settle();
  }
});
