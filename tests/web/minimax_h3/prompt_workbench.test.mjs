import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentStatus } from '../../../web/js/minimax_h3/agent_settings.js';
import { captureWorkbenchPrompt } from '../../../web/js/minimax_h3/settings_broadcast.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed, resetApp, toasts } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode, makeSetGet } from '../support/litegraph.mjs';
import '../../../web/js/minimax_h3/prompt_workbench.js';

const TYPE = 'ArisuMiniMaxH3PromptWorkbench';
const definition = { prototype: {} };
extensionNamed('Arisu.MiniMaxH3.PromptWorkbench').beforeRegisterNodeDef(definition, { name: TYPE });
const widget = (node, name) => node.widgets.find((item) => item.name === name);
const panel = (node) => widget(node, 'workbench').element;
const find = (root, label) =>
  descendants(root).find((item) => item.ariaLabel === label) ?? descendants(root).find((item) => item.textContent === label);
const settle = () => new Promise((resolve) => setImmediate(resolve));

test('Workbench keeps finalized text independent of setup, source notes and reviewed or late drafts', async (t) => {
  resetApp(makeGraph());
  resetApi();
  resetDom();
  const originalFetch = api.fetchApi;
  const graph = app.graph;
  const workflow = { isPersisted: true };
  app.extensionManager.workflow.activeWorkflow = workflow;
  app.extensionManager.workflow.openWorkflows = [workflow];
  let changes = 0;
  graph.beforeChange = () => changes++;
  graph.afterChange = () => {};
  let node = makeNode({
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
    assert.equal(descendants(panel(node)).find((item) => item.className === 'generation-fields').disabled, true);
    find(panel(node), 'Generation Results').onclick();
    assert(find(body, 'Generation Activity'));
    assert.equal(find(body, 'Output Prompt').value, '');
    find(body, 'Close').onclick();
    const final = find(panel(node), 'Finalized Prompt');
    assert.equal(final.tagName, 'TEXTAREA');
    final.value = 'manual';
    final.oninput();
    assert.equal(widget(node, 'finalized_prompt').value, 'manual');
    assert.equal(descendants(panel(node)).filter((item) => item.tagName === 'SELECT').length, 3);

    api.responses.push(jsonResponse(200, { docker: true, agents: { codex: { ready: false } } }));
    await agentStatus(true);
    await node.arisuRefreshSources();
    await settle();
    assert(find(panel(node), 'Setup') && find(panel(node), 'Generate Prompt').disabled);
    assert(!find(panel(node), 'Generation Results').disabled);

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
    // Set/Get labels are not literal input values: capture the resolved source.
    const get = makeNode({ id: 1985, type: 'GetNode', graph, widgets: [{ name: 'key', value: 'resources' }] });
    get.isVirtualNode = true;
    get.resolveVirtualOutput = () => ({ node: studio, slot: 0 });
    graph.links[14] = { origin_id: get.id, origin_slot: 0 };
    node.inputs.find((item) => item.name === 'resources').link = 14;
    const virtualPrompt = captureWorkbenchPrompt(node);
    assert.deepEqual(virtualPrompt.output['1'].inputs.resources, ['2', 0]);
    assert(virtualPrompt.output['2']);
    assert(!virtualPrompt.output['1985']);
    delete get.resolveVirtualOutput;
    get.getInputLink = () => ({ origin_id: studio.id, origin_slot: 0, resolve: () => ({ outputNode: studio, inputNode: get }) });
    assert.deepEqual(captureWorkbenchPrompt(node).output['1'].inputs.resources, ['2', 0]);
    get.resolveVirtualOutput = () => ({ node: get, slot: 0 });
    assert.throws(() => captureWorkbenchPrompt(node), /cycle/);
    delete get.resolveVirtualOutput;
    node.inputs.find((item) => item.name === 'resources').link = 10;
    // Actual same-graph setter lookup drives both reference notes and capture.
    const routed = makeSetGet(graph, 2000, studio, 0, 'resources');
    graph.links[15] = { origin_id: routed.getter.id, origin_slot: 0 };
    node.inputs.find((item) => item.name === 'resources').link = 15;
    node.arisuRefreshSources();
    await settle();
    assert(find(panel(node), 'Notes for replacement.png'));
    assert.deepEqual(captureWorkbenchPrompt(node).output['1'].inputs.resources, ['2', 0]);
    routed.getter.widgets[0].value = 'missing';
    node.arisuRefreshSources();
    await settle();
    assert(!find(panel(node), 'Notes for replacement.png'));
    assert.throws(() => captureWorkbenchPrompt(node), /could not be resolved/);
    routed.getter.widgets[0].value = 'resources';
    // Preserve a nonzero output slot through a second Set/Get hop and reroute.
    const relay = makeNode({ id: 2010, type: 'Reroute', graph, inputs: [{ name: 'value', link: 15 }] });
    relay.isVirtualNode = true;
    const chained = makeSetGet(graph, 2020, relay, 0, 'relay');
    graph.links[16] = { origin_id: chained.getter.id, origin_slot: 0 };
    graph.links[2000].origin_slot = 3;
    node.inputs.find((item) => item.name === 'resources').link = 16;
    assert.deepEqual(captureWorkbenchPrompt(node).output['1'].inputs.resources, ['2', 3]);
    graph.links[2000] = { origin_id: chained.getter.id, origin_slot: 0 };
    assert.throws(() => captureWorkbenchPrompt(node), /cycle/);
    graph.links[2000] = { origin_id: studio.id, origin_slot: 0 };
    node.inputs.find((item) => item.name === 'resources').link = 10;
    for (const name of ['video_settings', 'context_latent', 'vae']) {
      const socket = node.inputs.find((item) => item.name === name);
      socket.link = 15;
      assert.deepEqual(captureWorkbenchPrompt(node).output['1'].inputs[name], ['2', 0]);
      // SetNode's visible passthrough output is also a native virtual route.
      graph.links[17] = { origin_id: routed.setter.id, origin_slot: 0 };
      socket.link = 17;
      assert.deepEqual(captureWorkbenchPrompt(node).output['1'].inputs[name], ['2', 0]);
      socket.link = null;
    }
    // Notes still resolve when a root Studio feeds an explicit subgraph input.
    const inner = makeGraph('inner');
    inner.beforeChange = graph.beforeChange;
    inner.afterChange = graph.afterChange;
    graph.nodes.splice(graph.nodes.indexOf(node), 1);
    node.graph = inner;
    inner.nodes.push(node);
    const settings = makeNode({
      id: 3,
      type: 'ArisuMiniMaxH3VideoSettings',
      graph,
      widgets: [
        { name: 'length', value: 49 },
        { name: 'width', value: 832 },
        { name: 'height', value: 480 },
      ],
      outputs: ['video_settings'],
    });
    graph.links[13] = { origin_id: 3, origin_slot: 0 };
    const scope = makeNode({
      id: 20,
      type: 'Subgraph',
      graph,
      inputs: [
        { name: 'resources', link: 10 },
        { name: 'video_settings', link: 13 },
      ],
    });
    scope.subgraph = inner;
    // Subgraph input resolution needs the root DTOs in the same execution map.
    class ExecutionDTO {
      constructor(source, path, executionMap) {
        this.node = source;
        this.id = [...path, source.id].join(':');
        this.subgraphNodePath = path;
        this.executionMap = executionMap;
      }
      resolveOutput(slot) {
        return { origin_id: this.id, origin_slot: slot };
      }
      resolveInput(index) {
        const id = { resources: '2', video_settings: '3' }[this.node.inputs[index].name];
        if (!id) return null;
        const source = this.executionMap.get(id);
        if (!source) throw new Error(`No output node DTO found for id [${id}]`);
        return source.resolveOutput(0);
      }
    }
    scope.getInnerNodes = (executionMap) => [new ExecutionDTO(node, [20], executionMap)];
    inner.links = { 50: { originIsIoNode: true, origin_slot: 0 }, 51: { originIsIoNode: true, origin_slot: 1 } };
    node.inputs.find((item) => item.name === 'video_settings').link = 51;
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

    api.responses.push(
      jsonResponse(202, { id: 'job1' }),
      jsonResponse(200, { state: 'complete', draft: 'first draft', generation_elapsed_ms: 78000 }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    await settle();
    await settle();
    assert.equal(widget(node, 'finalized_prompt').value, 'manual');
    assert(
      !JSON.stringify(node.widgets.filter((item) => item.serialize !== false).map(({ name, value }) => ({ name, value }))).includes(
        'first draft',
      ),
    );
    assert(!find(body, 'Output Prompt'));
    assert.equal(toasts.at(-1).severity, 'success');
    assert(find(panel(node), ' · Agent time 1:18'));
    const beforeQuickApply = changes;
    find(panel(node), 'Apply Output').onclick();
    assert.equal(changes, beforeQuickApply + 1);
    assert.equal(widget(node, 'finalized_prompt').value, 'first draft');
    widget(node, 'finalized_prompt').value = 'manual';
    assert.equal(widget(node, 'finalized_prompt').value, 'manual');

    api.responses.push(
      jsonResponse(202, { id: 'job2' }),
      jsonResponse(200, { state: 'complete', draft: 'second draft', generation_elapsed_ms: 3661999 }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    await settle();
    await settle();
    api.responses.push(jsonResponse(200, { session: 'job2', lines: [], cursor: 0 }));
    find(panel(node), 'Generation Results').onclick();
    await settle();
    assert(find(body, 'Agent time 1:01:01'));
    const output = find(body, 'Output Prompt');
    output.value = '';
    output.oninput();
    assert.equal(output.disabled, false);
    assert(find(body, 'Apply to Workbench').disabled);
    output.value = 'edited draft';
    output.oninput();
    const before = changes;
    find(body, 'Apply to Workbench').onclick();
    find(body, 'Close').onclick();
    assert.equal(widget(node, 'finalized_prompt').value, 'edited draft');
    assert.equal(changes, before + 1);

    api.responses.push(
      jsonResponse(202, { id: 'failed' }),
      jsonResponse(200, { state: 'failed', error: 'Provider failed', generation_elapsed_ms: 12000 }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    await settle();
    await settle();
    assert.equal(toasts.at(-1).severity, 'error');
    assert(!find(panel(node), 'Apply Output'));
    assert(!find(body, 'Output Prompt'));
    assert(find(panel(node), ' · Agent time 0:12'));

    let finish;
    api.responses.push(
      jsonResponse(202, { id: 'job3' }),
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    assert(!find(panel(node), 'Apply Output'));
    await settle();
    await settle();
    assert(!find(panel(node), 'Generation Results').disabled);
    const captured = JSON.parse(api.calls.findLast((call) => call.route === '/arisu/workbench/generate').init.body);
    const releases = () => api.calls.filter((call) => call.route === '/arisu/workbench/release').length;
    const beforeEdits = releases();
    find(panel(node), 'Requirements').value = 'Changed for the next run';
    find(panel(node), 'Requirements').oninput();
    widget(studio, 'resources_json').value = JSON.stringify({ ...data, references: [] });
    widget(settings, 'length').value = 97;
    node.arisuRefreshSources();
    definition.prototype.onConnectionsChange.call(node);
    await settle();
    assert.equal(releases(), beforeEdits);
    assert(find(panel(node), 'Generate Prompt').disabled);
    assert.equal(captured.options.requirements, '');
    assert.equal(JSON.parse(captured.prompt['2'].inputs.resources_json).references.length, 3);
    assert.equal(captured.node_id, '20:1');
    assert.equal(captured.prompt['3'].inputs.length, 49);

    const framed = (...entries) => `ARISU_ACTIVITY ${JSON.stringify({ version: 1, entries })}`;
    const loaded = '# Skill\n[analysis] File content stays inside the tool\n{"metadata":true}';
    const toolRecord = { id: 'codex:tool1', kind: 'tool', text: 'workbench.read_skill', details: loaded };
    const responseRecord = { id: 'codex:response1', kind: 'agent', text: '```markdown\nA quiet sunrise\n```', details: '' };
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
          framed({ id: 'codex:thought1', kind: 'analysis', text: 'Original thought', details: '' }, toolRecord, responseRecord),
          'ARISU_AUDIT secret audit data',
          'ARISU_ACTIVITY {malformed',
        ],
        state: 'running',
      }),
    );
    find(panel(node), 'Generation Results').onclick();
    await settle();
    const activity = find(body, 'Generation Activity');
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
    const skillDetails = descendants(activity).find((item) => item.tagName === 'DETAILS' && find(item, 'workbench.read_skill'));
    assert(skillDetails && !skillDetails.open && find(skillDetails, loaded));
    const responses = descendants(activity).filter((item) => item.tagName === 'DETAILS' && find(item, 'Agent response'));
    assert.equal(responses.length, 2);
    assert(responses.every((item) => !item.open));
    assert(find(responses[0], '[agent] <img src=x onerror=alert(1)>'));
    assert(find(responses[1], responseRecord.text));
    responses[1].open = true;
    assert(!find(activity, '[analysis] File content stays inside the tool'));
    assert(!find(activity, 'ARISU_AUDIT secret audit data'));
    skillDetails.open = true;
    // A repeated provider item updates in place without closing the expanded details.
    api.responses.push(
      jsonResponse(200, {
        session: 'job3',
        cursor: 2,
        lines: [
          framed(
            { id: 'codex:thought1', kind: 'analysis', text: 'Updated thought', details: '' },
            { ...toolRecord, details: `${loaded}\nCompleted` },
            { ...responseRecord, text: '```markdown\nA quiet sunrise over a lake\n```' },
          ),
        ],
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 800));
    assert(!find(activity, '[analysis] Original thought'));
    assert(find(activity, '[analysis] Updated thought'));
    assert(skillDetails.open && find(skillDetails, `${loaded}\nCompleted`));
    assert(responses[1].open && find(responses[1], '```markdown\nA quiet sunrise over a lake\n```'));
    assert.equal(descendants(activity).filter((item) => item.tagName === 'SUMMARY' && item.textContent === 'Agent response').length, 2);
    assert.equal(
      descendants(activity).filter((item) => item.tagName === 'SUMMARY' && item.textContent === 'workbench.read_skill').length,
      1,
    );

    widget(node, 'finalized_prompt').value = 'restored';
    widget(node, 'prepare_job').value = 'imported';
    definition.prototype.onConfigure.call(node);
    finish(jsonResponse(200, { state: 'complete', draft: 'late draft', generation_elapsed_ms: 42000 }));
    await settle();
    assert.equal(widget(node, 'prepare_job').value, '');
    assert.equal(widget(node, 'finalized_prompt').value, 'restored');
    assert.equal(find(body, 'Output Prompt').value, 'late draft');
    assert(find(body, 'Agent time 0:42'));
    assert(find(body, 'Generation Activity'));
    find(body, 'Close').onclick();
    assert(!find(panel(node), 'Generation Results').disabled);
    find(panel(node), 'Apply Output').onclick();
    assert.equal(widget(node, 'finalized_prompt').value, 'late draft');
    const finalAgain = find(panel(node), 'Finalized Prompt');
    finalAgain.value = 'manual after Apply';
    finalAgain.oninput();
    assert(!find(panel(node), 'Apply Output').disabled);

    api.fetchApi = async function (route, init) {
      if (route === '/arisu/workbench/status') {
        api.calls.push({ route, init });
        return jsonResponse(200, { docker: true, agents: { codex: { ready: true } } });
      }
      return originalFetch.call(this, route, init);
    };
    // The actual frontend reloads nodes during Undo/Redo and when switching tabs.
    const saved = () => ({
      widgets: node.widgets.filter((item) => !item.element).map(({ name, value }) => ({ name, value })),
      inputs: node.inputs.map((item) => ({ ...item })),
    });
    const original = saved();
    app.loadGraphData = async (data, _clean, _view, owner) => {
      definition.prototype.onRemoved.call(node);
      inner.nodes.splice(inner.nodes.indexOf(node), 1);
      app.extensionManager.workflow.activeWorkflow = owner ?? { isPersisted: false };
      if (!data) return;
      node = makeNode({ id: 1, type: TYPE, graph: inner, ...data });
      definition.prototype.onNodeCreated.call(node);
      definition.prototype.onConfigure.call(node);
    };
    extensionNamed('Arisu.MiniMaxH3.PromptWorkbench').init();
    await app.loadGraphData(original, false, false, workflow);
    assert(find(panel(node), 'Apply Output'));
    assert(find(panel(node), ' · Agent time 0:42'));
    assert.equal(releases(), beforeEdits);

    let finishRequest;
    api.responses.push(
      () =>
        new Promise((resolve) => {
          finishRequest = resolve;
        }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    const background = { isPersisted: true };
    app.extensionManager.workflow.openWorkflows.push(background);
    await app.loadGraphData(original, false, false, background);
    await settle();
    assert(!find(panel(node), 'Apply Output'));
    assert(!find(panel(node), 'Generate Prompt').disabled);
    api.responses.push(jsonResponse(200, { state: 'complete', draft: 'Finished in the other tab', generation_elapsed_ms: 9000 }));
    finishRequest(jsonResponse(202, { id: 'background-job' }));
    await settle();
    await settle();
    await app.loadGraphData(original, false, false, workflow);
    assert(find(panel(node), 'Apply Output'));
    assert.equal(releases(), beforeEdits);
    find(panel(node), 'Apply Output').onclick();
    assert.equal(widget(node, 'finalized_prompt').value, 'Finished in the other tab');

    assert(find(panel(node), ' · Agent time 0:09'));
    // Cancellation before the POST returns releases the late ID and polls until confirmed.
    api.responses.push(
      () =>
        new Promise((resolve) => {
          finishRequest = resolve;
        }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    find(panel(node), 'Cancel').onclick();
    assert(find(panel(node), 'Cancelling…'));
    assert(!find(panel(node), ' · Agent time 0:09'));
    api.responses.push(jsonResponse(200, { released: true }), jsonResponse(200, { state: 'cancelled', generation_elapsed_ms: null }));
    finishRequest(jsonResponse(202, { id: 'cancelled-before-id' }));
    await settle();
    assert(api.calls.some((call) => call.route.endsWith('/jobs/cancelled-before-id')));
    assert(!find(panel(node), 'Generate Prompt').disabled);
    assert.equal(releases(), beforeEdits + 1);

    t.mock.timers.enable({ apis: ['setTimeout'] });
    api.responses.push(jsonResponse(202, { id: 'timed' }), jsonResponse(200, { state: 'preparing_media', generation_elapsed_ms: null }));
    find(panel(node), 'Generate Prompt').onclick();
    await settle();
    assert.equal(descendants(panel(node)).find((item) => item.className === 'generation-time').textContent, '');
    const direction = find(panel(node), 'Requirements');
    for (const elapsed of [0, 42000, 43000]) {
      api.responses.push(jsonResponse(200, { state: 'generating', generation_elapsed_ms: elapsed }));
      t.mock.timers.tick(750);
      await settle();
      assert.equal(find(panel(node), 'Requirements'), direction);
      assert(find(panel(node), ` · Agent time 0:${String(elapsed / 1000).padStart(2, '0')}`));
    }
    api.responses.push(jsonResponse(503, {}));
    t.mock.timers.tick(750);
    await settle();
    assert(find(panel(node), ' · Agent time 0:43 (updates unavailable)'));
    api.responses.push(jsonResponse(202, { id: 'cancel-timed' }), jsonResponse(200, { state: 'generating', generation_elapsed_ms: 1500 }));
    find(panel(node), 'Generate Prompt').onclick();
    await settle();
    api.responses.push(jsonResponse(200, { released: true }));
    find(panel(node), 'Cancel').onclick();
    await settle();
    assert(find(panel(node), 'Generate Prompt').disabled);
    api.responses.push(jsonResponse(200, { state: 'generating', generation_elapsed_ms: 2200 }));
    t.mock.timers.tick(750);
    await settle();
    assert(find(panel(node), 'Cancelling…'));
    assert(find(panel(node), ' · Agent time 0:02'));
    api.responses.push(jsonResponse(200, { state: 'cancelled', generation_elapsed_ms: 3300 }));
    t.mock.timers.tick(750);
    await settle();
    assert(find(panel(node), ' · Agent time 0:03'));
    assert(!find(panel(node), 'Generate Prompt').disabled);
    t.mock.timers.reset();

    // Same IDs in an imported workflow cannot inherit a previous session.
    await app.loadGraphData(original, true, true, null);
    assert(!find(panel(node), 'Apply Output'));
    app.extensionManager.workflow.openWorkflows = [app.extensionManager.workflow.activeWorkflow];
    api.responses.push(jsonResponse(200, { released: true }));
    await new Promise((resolve) => setTimeout(resolve, 1550));
    assert.equal(releases(), beforeEdits + 3);
    api.responses.push(
      jsonResponse(202, { id: 'removed-job' }),
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    find(panel(node), 'Generate Prompt').onclick();
    await settle();
    api.responses.push(jsonResponse(200, { released: true }));
    definition.prototype.onRemoved.call(node);
    finish(jsonResponse(200, { state: 'complete', draft: 'Must not appear after deletion' }));
    await settle();
    assert.equal(releases(), beforeEdits + 4);
    assert(!find(body, 'Must not appear after deletion'));
  } finally {
    api.responses.push(jsonResponse(200, { released: true }));
    definition.prototype.onRemoved.call(node);
    await settle();
    api.fetchApi = originalFetch;
  }
});
