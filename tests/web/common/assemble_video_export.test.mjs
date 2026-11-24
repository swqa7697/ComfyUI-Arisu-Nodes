// Assemble Video's export and the provenance of its edit: the checked plan that gates an export, the
// one job it puts on ComfyUI's queue, how a reload finds that job again, and what an edit keeps when
// its workflow is imported, copied or reopened. The request bodies asserted here are the ones the
// video routes and ComfyUI's /prompt parse.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api, jsonResponse } from '../support/api.mjs';
import { app, extensionNamed, resetApp, toastSeverities } from '../support/app.mjs';
import { button, described, edit, makeAssembly, panel, rows, serve, settle, TYPE, widget } from '../support/assembly.mjs';
import { descendants, resetDom } from '../support/dom.mjs';
import { makeGraph } from '../support/litegraph.mjs';
import '../../../web/js/common/assemble_video.js';

const Assembly = { prototype: {} };
const extension = extensionNamed('Arisu.Common.AssembleVideo');
extension.beforeRegisterNodeDef(Assembly, { name: TYPE });

const NAMES = ['project_prefix', 'export_name', 'encoding', 'codec', 'crf', 'edit_json', 'export_request'];
const PROJECT = 'motion_context/fixed';
const ID = (n) => `00000000-0000-4000-8000-00000000000${n}`;
const A = described(`${PROJECT}/videos/h3_clip_00007_.mp4`, { take: ID(1), frames: 243 });
const B = described(`${PROJECT}/videos/h3_clip_00008_.mp4`, { take: ID(2), frames: 221 });
const OLD = described('legacy/old.mp4', { frames: 48 });
const SPEC = { width: 1280, height: 720, fps: [24, 1], sample_rate: 32000, channels: 2 };
const entry = (id, item, extra = {}) => ({
  id,
  source: item.take ? 'take' : 'file',
  take: item.take?.take ?? '',
  segment: '',
  root: 'output',
  path: item.path,
  revision: item.revision,
  included: true,
  range: null,
  audio: 'auto',
  join: { correction: null, fade: 0 },
  ...extra,
});
const DOCUMENT = {
  version: 1,
  output: null,
  entries: [entry(ID(7), A), entry(ID(8), B, { range: [0, 200] }), entry(ID(9), OLD, { range: [22, 48] })],
};

/** The node as the frontend saves it: positional widget values, with each widget's own serializer applied. */
function serialized(node) {
  return {
    type: TYPE,
    id: node.id,
    widgets_values: NAMES.map((name) => widget(node, name).serializeValue?.() ?? widget(node, name).value),
    properties: structuredClone(node.properties),
  };
}

/** The frontend loads a serialized graph: nodes are created, given their saved values, then configured. */
async function configureWorkflow(data, workflow) {
  app.graph = app.rootGraph = makeGraph();
  const created = data.nodes.map((saved) => {
    const values = Object.fromEntries(NAMES.map((name, index) => [name, saved.widgets_values[index]]));
    const node = makeAssembly(Assembly, { id: saved.id, values, properties: saved.properties ?? {} });
    app.configuringGraph = true;
    try {
      Assembly.prototype.onConfigure.call(node);
    } finally {
      app.configuringGraph = false;
    }
    return node;
  });
  app.extensionManager.workflow.activeWorkflow = typeof workflow === 'object' && workflow ? workflow : { isPersisted: false };
  return created;
}
app.loadGraphData = (data, _clean, _restoreView, workflow) => configureWorkflow(data, workflow);
extension.init();

const states = (node) => rows(node).map((item) => item.dataset.state);
const needs = (node) => descendants(panel(node)).filter((element) => element.className === 'need');

test('Assemble Video exports one checked job through the queue, recovers it after a reload, and unbinds an edit it did not open itself', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  resetApp(makeGraph());
  resetDom();
  const server = {
    files: new Map([A, B, OLD].map((item) => [item.path, item])),
    plans: [],
    prompts: [],
    actions: [],
    takes: [],
    history: {},
    running: [],
    waiting: [],
    accept: 'running',
    reject: false,
  };
  serve((route, init) => {
    const [path, query] = route.split('?');
    const sent = init?.body ? JSON.parse(init.body) : null;
    if (path === '/arisu/video/describe')
      return jsonResponse(200, { entries: sent.entries.map((item) => server.files.get(item.path) ?? { ...item, state: 'missing' }) });
    if (path === '/arisu/video/takes') {
      server.takes.push(Object.fromEntries(new URLSearchParams(query)));
      return jsonResponse(200, { project: PROJECT, takes: [server.files.get(A.path), server.files.get(B.path)] });
    }
    if (path === '/arisu/video/preflight') {
      server.plans.push(sent);
      const second = sent.document.entries[1];
      // The plan depends on the request alone, as the route's does: each unresolved decision is one need.
      const found = [
        ...(sent.encoding === 'inherit' ? [{ kind: 'choose_codec', entries: [], suggested: { codec: 'h265', crf: 20 } }] : []),
        ...(sent.document.output ? [] : [{ kind: 'confirm_output', entries: [], suggested: SPEC }]),
        ...(second.audio === 'auto' ? [{ kind: 'switch_audio', entries: [second.id], suggested: { audio: 'embedded' } }] : []),
      ];
      return jsonResponse(200, {
        entries: sent.document.entries.map((item) => ({
          id: item.id,
          state: 'ok',
          frames: [0, 1],
          samples: [0, 1],
          audio: 'pcm',
          message: null,
        })),
        frames: 464,
        duration: 464 / 24,
        samples: 618667,
        ...SPEC,
        video: { operation: 'encode', reason: 'explicit codec', codec: sent.codec, encoder: 'libx265', crf: sent.crf },
        audio: { operation: 'encode', reason: 'joins with sound' },
        destination: `${PROJECT}/exports/main_00001/main_00001.mp4`,
        backend: 'ffmpeg',
        needs: found,
        warnings: [],
        ready: !found.length,
      });
    }
    if (path === '/prompt') {
      if (server.reject) return jsonResponse(400, { error: { message: 'invalid prompt' } });
      server.prompts.push(sent);
      // ComfyUI queues an accepted prompt at once: running first, waiting behind another job afterwards.
      server[server.accept] = [[server.prompts.length, sent.prompt_id]];
      return jsonResponse(200, { prompt_id: sent.prompt_id });
    }
    if (path.startsWith('/history/')) return jsonResponse(200, server.history);
    if (path === '/queue' && !init?.method) return jsonResponse(200, { queue_running: server.running, queue_pending: server.waiting });
    if (path === '/queue' || path === '/interrupt') {
      server.actions.push([path, sent]);
      server.waiting = server.waiting.filter((item) => !sent.delete?.includes(item[1]));
      return jsonResponse(200, {});
    }
    return undefined;
  });
  const persisted = { isPersisted: true };
  // The project is wired: the panel reads it through Path Builder before any run, and the prompt keeps the wire.
  app.graphToPrompt = async () => {
    const node = app.graph.nodes.find((item) => item.type === TYPE);
    const inputs = Object.fromEntries(NAMES.map((name) => [name, widget(node, name).serializeValue?.() ?? widget(node, name).value]));
    return {
      output: {
        7: { class_type: TYPE, inputs: { ...inputs, project_prefix: ['8', 0] } },
        8: { class_type: 'ArisuPathBuilder', inputs: { segment_1: 'motion_context/', segment_2: 'fixed' } },
        9: { class_type: 'KSampler', inputs: {} },
        10: { class_type: 'SaveVideo', inputs: { video: ['9', 0] } },
      },
      workflow: {},
    };
  };
  const wire = (target) => {
    target.inputs.find((input) => input.name === 'project_prefix').link = 1;
    return target;
  };
  let node = wire(makeAssembly(Assembly, { values: { edit_json: JSON.stringify(DOCUMENT) } }));
  await settle();
  assert.deepEqual(states(node), ['ok', 'ok', 'ok']);

  // the check posts the whole request; every unresolved decision blocks the export and offers its own action
  await button(panel(node), 'Check Export').onclick();
  assert.deepEqual(server.plans[0], {
    project: PROJECT,
    export_name: 'main',
    encoding: 'inherit',
    codec: 'h264',
    crf: 18,
    document: DOCUMENT,
  });
  assert.equal(needs(node).length, 3);
  assert.equal(button(panel(node), 'Export').disabled, true);
  await needs(node)[0].children[1].onclick();
  assert.deepEqual([widget(node, 'encoding').value, widget(node, 'codec').value, widget(node, 'crf').value], ['encode', 'h265', 20]);
  await needs(node)[0].children[1].onclick();
  assert.deepEqual(edit(node).output, SPEC, 'a common output is stored only after the user confirms it');
  await needs(node)[0].children[1].onclick();
  assert.equal(edit(node).entries[1].audio, 'embedded');
  assert.deepEqual([server.plans.length, needs(node).length, button(panel(node), 'Export').disabled], [4, 0, false]);

  // export: one job holding the assembly node and what feeds it; the request ID exists only in the submitted copy
  const text = widget(node, 'edit_json').value;
  const first = button(panel(node), 'Export').onclick();
  await settle();
  const [submitted] = server.prompts;
  assert.deepEqual(Object.keys(submitted.prompt), ['7', '8'], 'samplers and other savers stay out of the job');
  assert.match(submitted.prompt_id, /^[0-9a-f-]{36}$/);
  assert.deepEqual(
    { ...submitted, prompt: null },
    { prompt: null, prompt_id: submitted.prompt_id, client_id: 'test-client', partial_execution_targets: ['7'] },
  );
  assert.deepEqual(submitted.prompt[7].inputs, {
    project_prefix: ['8', 0],
    export_name: 'main',
    encoding: 'encode',
    codec: 'h265',
    crf: 20,
    edit_json: text,
    export_request: submitted.prompt_id,
  });
  assert.equal(server.plans.length, 5, 'the plan is checked again at the moment of export');
  assert.equal(widget(node, 'export_request').value, '');
  assert.deepEqual(node.properties.arisuAssembly, { pending: { id: submitted.prompt_id, node: '7' }, last: null });
  assert.equal(button(panel(node), 'Export').disabled, true);
  api.emit('progress', { prompt_id: submitted.prompt_id, value: 1, max: 4 });
  assert.match(descendants(panel(node)).find((element) => element.className === 'receipt').textContent, /25%/);

  // a trusted reload while the job runs: the saved receipt finds the same job, and its film is recorded once
  const saved = serialized(node);
  assert.equal(saved.widgets_values[6], '', 'a saved workflow never carries a request');
  [node] = await app.loadGraphData({ nodes: [saved] }, true, true, persisted);
  wire(node);
  await settle();
  assert.equal(edit(node).entries[0].path, A.path, 'a workflow the frontend reopened keeps its files');
  const receipt = {
    request: submitted.prompt_id,
    path: `${PROJECT}/exports/main_00001/main_00001.mp4`,
    name: 'main',
    counter: 1,
    frames: 464,
    samples: 618667,
    duration: 464 / 24,
  };
  server.running = [];
  server.history = {
    [submitted.prompt_id]: {
      status: { status_str: 'success', completed: true },
      outputs: {
        7: {
          arisu_project: [PROJECT],
          images: [{ filename: 'main_00001.mp4', subfolder: `${PROJECT}/exports/main_00001`, type: 'output' }],
          animated: [true],
          arisu_export: [receipt],
        },
      },
    },
  };
  t.mock.timers.tick(1200);
  await first;
  await settle();
  assert.deepEqual(node.properties.arisuAssembly, { pending: null, last: receipt });
  assert.deepEqual(toastSeverities(), ['success'], 'the replaced node reports nothing');
  assert.equal(server.prompts.length, 1, 'recovery follows the job; it does not export again');

  // a deliberate second export is another job; Stop removes it from the queue and the receipt is cleared
  server.history = {};
  server.accept = 'waiting';
  const second = button(panel(node), 'Export').onclick();
  await settle();
  const again = server.prompts[1];
  assert.notEqual(again.prompt_id, submitted.prompt_id);
  await button(panel(node), 'Stop').onclick();
  assert.deepEqual(server.actions, [['/queue', { delete: [again.prompt_id] }]]);
  t.mock.timers.tick(1200);
  await second;
  assert.deepEqual(node.properties.arisuAssembly, { pending: null, last: receipt });
  assert.deepEqual(toastSeverities(), ['success', 'info']);

  // a prompt ComfyUI refuses leaves no pending receipt behind
  server.reject = true;
  await button(panel(node), 'Export').onclick();
  assert.equal(node.properties.arisuAssembly.pending, null);
  assert.deepEqual(toastSeverities(), ['success', 'info', 'error']);
  server.reject = false;

  // an imported workflow keeps the order, identity and take IDs of its edit, and no location, join, trim of a plain file or receipt
  const exported = serialized(node);
  [node] = await app.loadGraphData({ nodes: [exported] }, true, true, null);
  await settle();
  assert.deepEqual(
    edit(node).entries.map((item) => [item.id, item.take, item.path, item.revision, item.range]),
    [
      [ID(7), ID(1), '', '', null],
      [ID(8), ID(2), '', '', [0, 200]],
      [ID(9), '', '', '', null],
    ],
  );
  assert.deepEqual(edit(node).output, SPEC);
  assert.equal(node.properties.arisuAssembly, undefined);
  assert.deepEqual(states(node), ['unbound', 'unbound', 'unbound']);
  assert.equal(button(panel(node), 'Export').disabled, true);

  // rebinding is one explicit action: takes are found again by ID inside this node's project, a plain file is reselected by hand
  server.files.set(A.path, { ...A, revision: 'rev:replaced' });
  await button(panel(node), `Rebind from Project ${PROJECT}`).onclick();
  assert.deepEqual(server.takes, [{ project: PROJECT }]);
  assert.deepEqual(
    edit(node).entries.map((item) => [item.path, item.revision]),
    [
      [A.path, 'rev:replaced'],
      [B.path, B.revision],
      ['', ''],
    ],
  );
  assert.deepEqual(states(node), ['ok', 'ok', 'unbound']);
  assert(button(rows(node)[2], 'Reselect Unbound video'));

  // a paste or duplicate configures outside a load: the copy is unbound too
  const copy = makeAssembly(Assembly, {
    id: 11,
    values: { edit_json: widget(node, 'edit_json').value },
    properties: { arisuAssembly: { pending: null, last: receipt } },
  });
  Assembly.prototype.onConfigure.call(copy);
  assert.deepEqual([edit(copy).entries.map((item) => item.path), copy.properties.arisuAssembly], [['', '', ''], undefined]);

  // reopening a saved workflow revalidates every file; a different file at the same location is flagged, never accepted
  const kept = edit(node);
  server.files.set(A.path, { ...A, revision: 'rev:other' });
  [node] = await app.loadGraphData({ nodes: [serialized(node)] }, true, true, persisted);
  await settle();
  assert.deepEqual(edit(node), kept);
  assert.deepEqual(states(node), ['changed', 'ok', 'unbound']);
});
