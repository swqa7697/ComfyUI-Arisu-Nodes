// Assemble Video's edit list, driven through the shipped extension: the three ways footage enters the
// edit, replacing and reordering it, what a join keeps and loses, and the difference between removing
// a row and deleting its files. The request bodies asserted here are the ones the video routes parse.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { registerTakeSource } from '../../../web/js/common/take_sources.js';
import { api, jsonResponse } from '../support/api.mjs';
import { commands, extensionNamed, resetApp, toastSeverities } from '../support/app.mjs';
import { button, described, dialog, edit, makeAssembly, panel, row, rows, serve, settle, TYPE } from '../support/assembly.mjs';
import { descendants, FakeElement, resetDom } from '../support/dom.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';
import '../../../web/js/common/assemble_video.js';

const Assembly = { prototype: {} };
extensionNamed('Arisu.Common.AssembleVideo').beforeRegisterNodeDef(Assembly, { name: TYPE });

const VIDEOS = 'motion_context/fixed/videos';
const ID = (n) => `00000000-0000-4000-8000-00000000000${n}`;
const A = described(`${VIDEOS}/h3_clip_00007_.mp4`, { take: ID(1), frames: 243, deletable: true });
const B = described(`${VIDEOS}/h3_clip_00008_.mp4`, { take: ID(2), frames: 221, predecessor: ID(1), deletable: true });
const C = described(`${VIDEOS}/h3_clip_00009_.mp4`, { take: ID(3), frames: 204 });
const D1 = described(`arisu_director/${ID(4)}/clip_00002_.mp4`, { frames: 120 });
const D2_PATH = `arisu_director/${ID(5)}/clip_00002_.mp4`;
const OLD = described('legacy/old.mp4', { frames: 48 });
const SUGGESTED = { luma_gain: 1.02, luma_offset: 0.01, cb_offset: 0, cr_offset: -0.005, taper: 12 };
const FILES = new Map([A, B, C, D1, OLD].map((item) => [item.path, item]));
const checkboxes = (root) => descendants(root).filter((element) => element.tagName === 'INPUT' && element.type === 'checkbox');
const paths = (node) => edit(node).entries.map((entry) => entry.path.split('/').at(-1));
const event = (extra = {}) => ({ preventDefault() {}, stopPropagation() {}, ...extra });

test('Assemble Video builds an edit from takes, Director and files, keeps joins only while they hold, and deletes only on confirmation', async () => {
  const graph = makeGraph();
  const changes = { before: 0, after: 0 };
  graph.beforeChange = () => changes.before++;
  graph.afterChange = () => changes.after++;
  resetApp(graph);
  resetDom();
  let focused = null;
  FakeElement.prototype.focus = function () {
    focused = this;
  };
  const server = { takes: [], describe: [], joins: [], released: [], deletes: [], browsed: 0 };
  serve((route, init) => {
    const [path, query] = route.split('?');
    const sent = init?.body ? JSON.parse(init.body) : null;
    if (path === '/arisu/video/takes') {
      server.takes.push(Object.fromEntries(new URLSearchParams(query)));
      return jsonResponse(200, { project: 'motion_context/fixed', takes: [A, B, C] });
    }
    if (path === '/arisu/video/describe') {
      server.describe.push(sent);
      return jsonResponse(200, { entries: sent.entries.map((item) => FILES.get(item.path) ?? { ...item, state: 'missing' }) });
    }
    if (path === '/arisu/video/join-preview') {
      server.joins.push(sent);
      return jsonResponse(202, { id: `j${server.joins.length}` });
    }
    if (path.startsWith('/arisu/video/join-preview/')) {
      if (init?.method === 'DELETE') {
        server.released.push(path.split('/').at(-1));
        return jsonResponse(200, { released: true });
      }
      const { join } = server.joins.at(-1);
      const tags = { range: 'tv', matrix: 'bt709', primaries: 'bt709', transfer: 'iec61966-2-1' };
      return jsonResponse(200, {
        state: 'ready',
        progress: 100,
        error: null,
        variants: join.correction || join.fade ? ['a', 'b'] : ['a'],
        cut: 3,
        signalling: { match: true, outgoing: tags, incoming: tags },
        suggestion: { stable: true, correction: SUGGESTED },
      });
    }
    if (path === '/arisu/roots') return jsonResponse(200, { roots: [{ id: 'output', label: 'Output' }] });
    if (path === '/arisu/resources/browse') {
      server.browsed++;
      return jsonResponse(200, {
        root: 'output',
        path: 'legacy',
        parent: '',
        dirs: [],
        files: ['old.mp4', 'still.png', 'voice.wav'],
        kinds: { 'old.mp4': 'video', 'still.png': 'image', 'voice.wav': 'audio' },
        ancestors: [],
        roots: [{ id: 'output', label: 'Output' }],
      });
    }
    if (path === '/arisu/video/delete') {
      server.deletes.push(sent);
      const files = (item) => [
        { path: item.path, bytes: 4000 },
        { path: item.path.replace('.mp4', '.arisu/take.json'), bytes: 96 },
      ];
      return jsonResponse(200, {
        entries: sent.entries.map((item) => ({
          root: item.root,
          path: item.path,
          state: sent.confirm ? (item.path === A.path ? 'deferred' : 'deleted') : 'deletable',
          files: files(item),
          bytes: 4096,
        })),
        bytes: 4096 * sent.entries.length,
      });
    }
    return undefined;
  });
  // A Director panel publishes its film: one take that needs a rerender, one whose file is gone, one segment not rendered.
  registerTakeSource('TestDirector', () => ({
    label: 'Director #2',
    segments: [
      {
        segment: 's1',
        label: '01',
        transition: 'cut',
        status: 'Needs rerender',
        take: { take: ID(4), root: 'output', path: D1.path, revision: D1.revision, predecessor: null },
      },
      {
        segment: 's2',
        label: '02',
        transition: 'continuation',
        status: 'Rendered',
        take: { take: ID(5), root: 'output', path: D2_PATH, revision: 'rev:d2', predecessor: ID(4) },
      },
      { segment: 's3', label: '03', transition: 'cut', status: 'Pending', take: null },
    ],
  }));
  makeNode({ id: 2, type: 'TestDirector', graph });
  const node = makeAssembly(Assembly);
  assert.deepEqual(
    node.inputs.map((input) => input.name),
    ['project_prefix', 'export_name', 'encoding', 'codec', 'crf'],
    'the edit and the one-shot request are not connectable',
  );

  // project takes: several are chosen at once and enter the edit as one undoable step
  let pending = button(panel(node), 'Add Project Takes').onclick();
  await settle();
  const pick = (take) => checkboxes(dialog()).find((box) => box.ariaLabel?.endsWith(take.path.split('/').at(-1)));
  pick(A).onchange({ target: { checked: true } });
  pick(B).onchange({ target: { checked: true } });
  button(dialog(), 'Add 2 Takes').onclick();
  await pending;
  assert.deepEqual(server.takes, [{ project: 'motion_context/fixed' }]);
  assert.deepEqual(changes, { before: 1, after: 1 });
  const [first, second] = edit(node).entries;
  assert.deepEqual(
    { ...first, id: '' },
    {
      id: '',
      source: 'take',
      take: ID(1),
      segment: '',
      root: 'output',
      path: A.path,
      revision: A.revision,
      included: true,
      range: null,
      audio: 'auto',
      join: { correction: null, fade: 0 },
    },
  );
  assert.deepEqual(
    rows(node).map((item) => item.dataset.state),
    ['ok', 'ok'],
  );

  // the join between a take and its recorded continuation: a direct cut first, then the experimental match and a click fade
  pending = button(panel(node), 'Preview Join').onclick();
  await settle();
  const match = () => checkboxes(dialog())[0];
  const player = () => descendants(dialog()).find((element) => element.tagName === 'VIDEO');
  const place = (item) => ({ root: 'output', path: item.path, revision: item.revision, range: null });
  assert.equal(match().disabled, false, 'a verified predecessor with matching signalling and a stable step may be matched');
  assert.equal(player().src, '/api/arisu/video/join-preview/j1/view?variant=a');
  match().checked = true;
  match().onchange();
  await settle();
  assert.equal(player().src, '/api/arisu/video/join-preview/j2/view?variant=b');
  const fade = descendants(dialog()).find((element) => element.tagName === 'SELECT');
  fade.value = '10';
  fade.onchange();
  await settle();
  button(dialog(), 'Apply to This Join').onclick();
  await pending;
  await settle();
  assert.deepEqual(server.joins, [
    { outgoing: place(A), incoming: place(B), join: { correction: null, fade: 0 } },
    { outgoing: place(A), incoming: place(B), join: { correction: SUGGESTED, fade: 0 } },
    { outgoing: place(A), incoming: place(B), join: { correction: SUGGESTED, fade: 10 } },
  ]);
  assert.deepEqual(server.released, ['j1', 'j2', 'j3'], 'every preview job is released, the last one when the dialog closes');
  const applied = {
    correction: { ...SUGGESTED, basis: { prev_revision: A.revision, prev_end: 243, revision: B.revision, start: 0 } },
    fade: 10,
  };
  assert.deepEqual(edit(node).entries[1].join, applied);

  // Director footage arrives in film order as an independent block; the unrendered segment is skipped
  await button(panel(node), 'Import from Director').onclick();
  assert.deepEqual(server.describe.at(-1), {
    entries: [
      { root: 'output', path: D1.path },
      { root: 'output', path: D2_PATH },
    ],
  });
  const [, , stale, gone] = edit(node).entries;
  assert.deepEqual([stale.source, stale.take, stale.segment, gone.take, gone.revision], ['director', ID(4), 's1', ID(5), 'rev:d2']);
  assert.deepEqual(
    rows(node).map((item) => item.dataset.state),
    ['ok', 'ok', 'stale', 'missing'],
  );
  assert.deepEqual(edit(node).entries[1].join, applied, 'adding footage elsewhere leaves an existing join alone');

  // an existing file: Browse lists videos only, and the server describes the pick before it enters the edit
  await button(panel(node), 'Add Existing Video').onclick();
  const cards = descendants(dialog()).filter((element) => element.className === 'arisu-browser-file');
  assert.deepEqual(
    cards.map((card) => card.lastChild.textContent),
    ['old.mp4'],
  );
  await cards[0].onclick();
  assert.deepEqual(server.describe.at(-1), { entries: [{ root: 'output', path: OLD.path }] });
  assert.deepEqual([edit(node).entries[4].source, edit(node).entries[4].take], ['file', '']);

  // replacing the missing Director take keeps the row's place and identity
  pending = button(row(node, gone.id), `Reselect s2 · clip_00002_.mp4`).onclick();
  await settle();
  button(dialog(), `Use h3_clip_00009_.mp4`).onclick();
  await pending;
  const replaced = edit(node).entries[3];
  assert.deepEqual(
    [replaced.id, replaced.source, replaced.take, replaced.path, replaced.revision],
    [gone.id, 'take', ID(3), C.path, C.revision],
  );
  assert.equal(row(node, gone.id).dataset.state, 'ok');

  // reordering by keyboard, by the hidden move buttons and by drag; a join does not survive losing its neighbour
  const file = edit(node).entries[4];
  descendants(row(node, file.id))
    .find((element) => element.className === 'handle')
    .onkeydown(event({ key: 'ArrowUp' }));
  assert.deepEqual(paths(node), ['h3_clip_00007_.mp4', 'h3_clip_00008_.mp4', 'clip_00002_.mp4', 'old.mp4', 'h3_clip_00009_.mp4']);
  assert.equal(focused.parent.dataset.entryId, file.id, 'focus follows the moved row');
  button(row(node, first.id), 'Move Down').onclick();
  assert.deepEqual(paths(node).slice(0, 2), ['h3_clip_00008_.mp4', 'h3_clip_00007_.mp4']);
  assert.deepEqual(edit(node).entries[0].join, { correction: null, fade: 0 }, 'the correction described a join that no longer exists');
  descendants(row(node, replaced.id))
    .find((element) => element.className === 'handle')
    .ondragstart(event());
  row(node, stale.id).ondragover(event({ clientY: -1 }));
  row(node, stale.id).ondrop(event());
  assert.deepEqual(paths(node), ['h3_clip_00008_.mp4', 'h3_clip_00007_.mp4', 'h3_clip_00009_.mp4', 'clip_00002_.mp4', 'old.mp4']);

  // excluding keeps the row and takes it out of the film's running length
  button(row(node, stale.id), 'Exclude s1 · clip_00002_.mp4').onclick();
  assert.equal(edit(node).entries[3].included, false);
  const sum = () => descendants(panel(node)).find((element) => element.className === 'sum').textContent;
  assert.equal(sum(), `4 of 5 · ${221 + 243 + 204 + 48} frames · 29.83 s`);

  // removing rows is an edit: no request, no file touched
  const select = (id, checked = true) => checkboxes(row(node, id))[0].onchange({ target: { checked } });
  const requests = api.calls.length;
  select(stale.id);
  select(file.id);
  button(panel(node), 'Remove Selected').onclick();
  assert.deepEqual(paths(node), ['h3_clip_00008_.mp4', 'h3_clip_00007_.mp4', 'h3_clip_00009_.mp4']);
  assert.equal(api.calls.length, requests);
  assert.deepEqual(server.deletes, []);

  // ComfyUI hears its history keys before the panel, except on an INPUT: only a row checkbox forwards them,
  // so a key on a row handle is not answered twice
  button(panel(node), 'Undo').onclick();
  for (const key of panel(node).listeners.get('keydown')) {
    key(event({ ctrlKey: true, key: 'z', target: { tagName: 'INPUT', type: 'checkbox' } }));
    key(event({ ctrlKey: true, shiftKey: true, key: 'Z', target: { tagName: 'INPUT', type: 'checkbox' } }));
    key(event({ ctrlKey: true, key: 'z', target: { tagName: 'SPAN' } }));
    key(event({ ctrlKey: true, key: 'z', target: { tagName: 'INPUT', type: 'search' } }));
  }
  assert.deepEqual(commands, ['Comfy.Undo', 'Comfy.Undo', 'Comfy.Redo']);

  // deleting from disk is offered only for takes the server calls deletable, lists the files first, and needs a second click
  select(replaced.id);
  select(first.id);
  assert.equal(button(panel(node), 'Delete Files…').disabled, true, 'a row that is not a deletable take blocks the action');
  select(replaced.id, false);
  select(second.id);
  assert.equal(button(panel(node), 'Delete Files…').disabled, false);
  const before = edit(node);
  pending = button(panel(node), 'Delete Files…').onclick();
  await settle();
  const sent = [B, A].map((item) => ({ root: 'output', path: item.path, revision: item.revision }));
  assert.deepEqual(server.deletes, [{ entries: sent, confirm: false }]);
  assert.deepEqual(edit(node), before, 'the dry run changes nothing');
  button(dialog(), 'Delete 4 Files').onclick();
  await pending;
  assert.deepEqual(server.deletes[1], { entries: sent, confirm: true });
  assert.deepEqual(paths(node), ['h3_clip_00007_.mp4', 'h3_clip_00009_.mp4'], 'the deleted take leaves the edit; the deferred one stays');
  assert(toastSeverities().includes('warn'));
});
