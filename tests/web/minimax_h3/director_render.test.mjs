// Director rendering with either video saver: the legacy and the project take directory, the
// project read from the prompt before the run, the saver choice, and what a removed latent leaves usable.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readDocument } from '../../../web/js/minimax_h3/director_document.js';
import {
  refreshRenderTakes,
  renderSegments,
  renderStatus,
  renderTake,
  revisionFootage,
  saverCandidates,
  takeLocation,
} from '../../../web/js/minimax_h3/director_render.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, resetApp } from '../support/app.mjs';
import { makeGraph, makeNode } from '../support/litegraph.mjs';

const DIRECTOR = 'ArisuMiniMaxH3DirectorWorkbench';
const LATENT = 'clip_00001.safetensors';
const SEGMENT = { seconds: 5, overlap_frames: 22, bindings: [] };
const FILM = readDocument(
  JSON.stringify({
    version: 1,
    segments: [
      { ...SEGMENT, id: 'a', prompt: 'A', transition: 'cut' },
      { ...SEGMENT, id: 'b', prompt: 'B', transition: 'continuation' },
    ],
    selected: 'a',
  }),
);

/** The Director template's render chain in API format, ending in the given saver (node 11). */
function chain(saver) {
  const node = (class_type, inputs = {}) => ({ class_type, inputs });
  return {
    1: node(DIRECTOR, { film_json: '' }),
    2: node('ArisuMiniMaxH3HybridToVideo', { prompt: ['1', 0], video_settings: ['1', 1], resources: ['1', 2] }),
    3: node('MiniMaxH3MotionContextLoadLatent'),
    4: node('MiniMaxH3MotionContext', { context_latent: ['3', 0], conditioning: ['2', 0], latent: ['2', 1] }),
    5: node('KSampler', { positive: ['4', 0], latent_image: ['2', 1] }),
    6: node('MiniMaxH3MotionContextSaveLatent', { latent: ['5', 0] }),
    7: node('VAEDecode', { samples: ['5', 0] }),
    8: node('VAEDecodeAudio', { samples: ['5', 0] }),
    9: node('MiniMaxH3MotionContextTrim', { trim_frames: ['4', 1], images: ['7', 0], audio: ['8', 0] }),
    10: node('CreateVideo', { images: ['9', 0], audio: ['9', 1] }),
    11: saver,
  };
}

function arisuSaver(project_prefix) {
  return {
    class_type: 'ArisuSaveVideoSegment',
    inputs: { video: ['10', 0], project_prefix, clip_name: 'clip', codec: 'h264', crf: 18, take_context: '' },
  };
}

/**
 * A stand-in for ComfyUI and the pack's take route: every prompt succeeds and saves into the
 * directory its prefix names, and the route reports the artifacts that have not been removed.
 */
function serve(server) {
  const answer = (route, init) => {
    if (route === '/prompt') {
      const body = JSON.parse(init.body);
      server.prompts.push(body);
      return jsonResponse(200, { prompt_id: body.prompt_id });
    }
    if (route.startsWith('/history/')) {
      const id = route.slice('/history/'.length);
      const { prompt, partial_execution_targets: targets } = server.prompts.find((body) => body.prompt_id === id);
      const subfolder = prompt[targets[1]].inputs.filename_prefix.replace(/\/clip$/, '');
      return jsonResponse(200, {
        [id]: {
          status: { status_str: 'success', completed: true },
          outputs: {
            // The latent already took counter 1 in this directory, so a stock saver's video is number 2.
            [targets[0]]: { images: [{ filename: 'clip_00002_.mp4', subfolder, type: 'output' }], animated: [true] },
            [targets[1]]: { latents: [{ filename: LATENT, subfolder, type: 'output' }] },
          },
        },
      });
    }
    if (route.startsWith('/arisu/resources/director-take?')) {
      const query = new URLSearchParams(route.slice(route.indexOf('?') + 1));
      server.inspected.push(Object.fromEntries(query));
      const take = query.get('take');
      if (server.removed.video.has(take)) return jsonResponse(200, {});
      return jsonResponse(200, { video: `video-${take}`, ...(server.removed.latent.has(take) ? {} : { latent: `latent-${take}` }) });
    }
    throw new Error(`unexpected request ${route}`);
  };
  resetApi();
  for (let i = 0; i < 64; i++) api.responses.push(answer);
}

test('Director renders through either saver into the legacy or project layout and keeps footage after its latent is removed', async () => {
  const graph = makeGraph();
  resetApp(graph);
  const director = makeNode({ id: 1, type: DIRECTOR, graph });
  const server = { prompts: [], inspected: [], removed: { video: new Set(), latent: new Set() } };
  let output;
  app.graphToPrompt = async () => ({ output: structuredClone(output), workflow: {} });
  const render = (selected) => renderSegments(director, { ...FILM, selected }, false);
  const refresh = () => refreshRenderTakes(director, FILM);
  const last = () => server.prompts.at(-1);
  serve(server);

  // the stock saver keeps the legacy directory: one prefix for both savers, slot 1 for the latent, no project anywhere
  output = chain({ class_type: 'SaveVideo', inputs: { video: ['10', 0], filename_prefix: 'video/ComfyUI' } });
  await render('a');
  const legacy = renderTake(director, 'a');
  assert.equal(last().prompt_id, legacy.id);
  assert.equal(last().client_id, 'test-client');
  assert.deepEqual(last().partial_execution_targets, ['11', '6']);
  assert.deepEqual(last().prompt[11].inputs, { video: ['10', 0], filename_prefix: `arisu_director/${legacy.id}/clip` });
  assert.deepEqual(last().prompt[6].inputs, { latent: ['5', 0], filename_prefix: `arisu_director/${legacy.id}/clip`, clip_index: 1 });
  assert.deepEqual([last().prompt[3].inputs.latent_path, last().prompt[3].inputs.clip_index], ['arisu_director', 0]);
  assert.deepEqual([legacy.saver, legacy.project], ['SaveVideo', '']);
  assert.deepEqual(legacy.files, { video: `video-${legacy.id}`, latent: `latent-${legacy.id}` });
  // the receipt is located by its saved directory, whatever counter the video received
  assert.deepEqual(takeLocation(legacy), { project: '', dir: `arisu_director/${legacy.id}` });
  assert.deepEqual(server.inspected.at(-1), { take: legacy.id, video: 'clip_00002_.mp4' });
  await refresh();
  assert.equal(renderStatus(director, 'a', FILM), 'Rendered');

  // the pack's saver with a project: Director reads it through Path Builder, String Concatenate and a
  // primitive before the run, and both savers write below <project>/director/<take>
  output = chain(arisuSaver(['12', 0]));
  output[12] = { class_type: 'ArisuPathBuilder', inputs: { segment_2: ['14', 0], segment_1: ' motion_context/', segment_3: '' } };
  output[14] = { class_type: 'StringConcatenate', inputs: { string_a: 'fix', string_b: ['13', 0], delimiter: '' } };
  output[13] = { class_type: 'PrimitiveString', inputs: { value: 'ed/' } };
  await render('a');
  const first = renderTake(director, 'a');
  const dir = `motion_context/fixed/director/${first.id}`;
  assert.notEqual(first.id, legacy.id);
  assert.equal('filename_prefix' in last().prompt[11].inputs, false);
  assert.deepEqual(last().prompt[11].inputs.project_prefix, ['12', 0], 'the project wire stays; the server resolves it again');
  assert.deepEqual([last().prompt[6].inputs.filename_prefix, last().prompt[6].inputs.clip_index], [`${dir}/clip`, 1]);
  assert.equal(last().prompt[3].inputs.latent_path, 'motion_context/fixed/director');
  assert.deepEqual(JSON.parse(last().prompt[11].inputs.take_context), {
    take: first.id,
    segment: 'a',
    predecessor: null,
    transition: 'cut',
  });
  assert.equal(output[11].inputs.take_context, '', 'only the submitted copy carries a context');
  assert.deepEqual([first.saver, first.project], ['ArisuSaveVideoSegment', 'motion_context/fixed']);
  assert.deepEqual(takeLocation(first), { project: 'motion_context/fixed', dir });
  assert.deepEqual(server.inspected.at(-1), { take: first.id, video: 'clip_00002_.mp4', project: 'motion_context/fixed' });

  // a continuation loads its predecessor's latent from that take's own directory and names it in the context
  await render('b');
  const second = renderTake(director, 'b');
  assert.deepEqual([last().prompt[3].inputs.latent_path, last().prompt[3].inputs.clip_index], [`${dir}/${LATENT}`, 1]);
  assert.deepEqual(JSON.parse(last().prompt[11].inputs.take_context), {
    take: second.id,
    segment: 'b',
    predecessor: first.id,
    transition: 'continuation',
  });
  assert.equal(second.predecessor, first.id);
  await refresh();
  assert.deepEqual([renderStatus(director, 'a', FILM), renderStatus(director, 'b', FILM)], ['Rendered', 'Rendered']);

  // a removed latent leaves the footage in place but no longer feeds a continuation; a removed video is unavailable
  server.removed.latent.add(first.id);
  server.removed.video.add(second.id);
  await refresh();
  assert.deepEqual([renderStatus(director, 'a', FILM), renderStatus(director, 'b', FILM)], ['Latent removed', 'Output unavailable']);
  await assert.rejects(render('b'));
  assert.deepEqual(await revisionFootage(director, FILM, 1), {
    project: 'motion_context/fixed',
    take: first.id,
    video: first.video.filename,
    revision: first.files.video,
    segment: 'a',
  });
  const edited = structuredClone(FILM);
  edited.segments[0].prompt = 'A different opening shot.';
  assert.equal(await revisionFootage(director, edited, 1), null, 'an edited predecessor no longer matches its take');
  assert.equal(await revisionFootage(director, FILM, 0), null, 'a cut starts from the film plan');
  server.removed.latent.clear();
  server.removed.video.clear();

  // receipts whose files sit outside their take's directory locate nowhere
  for (const [name, take] of Object.entries({
    'another take': { ...first, video: { ...first.video, subfolder: `motion_context/fixed/director/${legacy.id}` } },
    'no project': { ...first, video: { ...first.video, subfolder: `/director/${first.id}` }, latent: null },
    'stray latent': { ...first, latent: { ...first.latent, subfolder: `arisu_director/${first.id}` } },
    'other latent slot': { ...first, latent: { ...first.latent, filename: 'clip_00002.safetensors' } },
    'temp video': { ...first, video: { ...first.video, type: 'temp' } },
    'unnumbered video': { ...first, video: { ...first.video, filename: 'clip.mp4' } },
  }))
    assert.equal(takeLocation(take), null, `case=${name}`);

  // a project computed by another node cannot be read before the run: nothing is queued and no receipt is left pending
  const queued = server.prompts.length;
  output = chain(arisuSaver(['15', 0]));
  output[15] = { class_type: 'SomeTextNode', inputs: {} };
  await assert.rejects(render('a'));
  assert.equal(server.prompts.length, queued);
  assert.equal(director.properties.directorRenders.pending, null);

  // a blank project keeps the legacy directory, still with the pack's saver and its context
  output = chain(arisuSaver(''));
  await render('a');
  const blank = renderTake(director, 'a');
  assert.equal('filename_prefix' in last().prompt[11].inputs, false);
  assert.deepEqual(JSON.parse(last().prompt[11].inputs.take_context), {
    take: blank.id,
    segment: 'a',
    predecessor: null,
    transition: 'cut',
  });
  assert.equal(last().prompt[6].inputs.filename_prefix, `arisu_director/${blank.id}/clip`);
  assert.deepEqual([blank.saver, blank.project], ['ArisuSaveVideoSegment', '']);

  // two savers behind Create Video: Director refuses until one is chosen, then renders through that one only
  output = chain(arisuSaver('motion_context/fixed'));
  output[16] = { class_type: 'SaveVideo', inputs: { video: ['10', 0], filename_prefix: 'video/ComfyUI' } };
  output[17] = { class_type: 'SaveVideo', inputs: { video: ['9', 0], filename_prefix: 'elsewhere' } };
  assert.deepEqual(saverCandidates(director), []);
  await assert.rejects(render('a'));
  assert.equal(server.prompts.length, queued + 1);
  assert.deepEqual(saverCandidates(director), [
    { id: '11', type: 'ArisuSaveVideoSegment' },
    { id: '16', type: 'SaveVideo' },
  ]);
  director.properties.directorSaver = '16';
  await render('a');
  const chosen = renderTake(director, 'a');
  assert.deepEqual(last().partial_execution_targets, ['16', '6']);
  assert.equal(last().prompt[16].inputs.filename_prefix, `arisu_director/${chosen.id}/clip`);
  assert.deepEqual(last().prompt[11].inputs, output[11].inputs, 'the saver that was not chosen keeps its own inputs');
  assert.deepEqual([chosen.saver, chosen.project], ['SaveVideo', '']);

  // a chain with no saver behind Create Video is not a Director workflow
  output = chain({ class_type: 'SaveVideo', inputs: { video: ['9', 0], filename_prefix: 'elsewhere' } });
  await assert.rejects(render('a'));
  assert.deepEqual(saverCandidates(director), [], 'a stale choice list does not outlive the chain it came from');

  // The Sampling subgraph can return SelfLift directly or run Join Match first.
  // Save the very same switched result that both picture and sound decode.
  output = chain(arisuSaver('film'));
  const motion = '12:4';
  const sampler = '12:5';
  const match = '12:6';
  const toggle = '12:7';
  output[motion] = output[4];
  delete output[4];
  delete output[5];
  output[9].inputs.trim_frames = [motion, 1];
  output[sampler] = {
    class_type: 'ArisuMiniMaxH3SelfLiftProgressiveSampler',
    inputs: { conditioning: [motion, 0], latent_image: ['2', 1] },
  };
  output[match] = {
    class_type: 'MiniMaxH3JoinMatch',
    inputs: { samples: [sampler, 0], context_length: [motion, 1], context_latent: ['3', 0] },
  };
  output[toggle] = { class_type: 'ComfySwitchNode', inputs: { switch: false, on_false: [sampler, 0], on_true: [match, 0] } };
  output[6].inputs.latent = output[7].inputs.samples = output[8].inputs.samples = [toggle, 0];
  await render('a');
  const cut = renderTake(director, 'a');
  output[toggle].inputs.switch = true;
  await render('b');
  const continuation = last().prompt;
  assert.equal(continuation[3].inputs.latent_path, `${cut.latent.subfolder}/${LATENT}`);
  assert.equal(continuation[motion].inputs.context_length, '22');
  assert.deepEqual(continuation[toggle], output[toggle]);
  assert.deepEqual(
    [continuation[6].inputs.latent, continuation[7].inputs.samples, continuation[8].inputs.samples],
    Array(3).fill([toggle, 0]),
  );

  const beforeInvalid = server.prompts.length;
  output[8].inputs.samples = [sampler, 0];
  await assert.rejects(render('a'));
  output[8].inputs.samples = [toggle, 0];
  output[sampler].inputs.latent_image = ['2', 0];
  await assert.rejects(render('a'));
  output[sampler].inputs.latent_image = ['2', 1];
  output[match].inputs.samples = [toggle, 0];
  await assert.rejects(render('a'));
  output[match].inputs.samples = [sampler, 0];
  output[toggle].inputs.switch = ['13', 0];
  output[13] = { class_type: 'PrimitiveBoolean', inputs: { value: false } };
  output[toggle].inputs.on_false = ['3', 0];
  await assert.rejects(render('a'));
  assert.equal(server.prompts.length, beforeInvalid);
  output[toggle].inputs.on_false = [sampler, 0];
  await render('a');
  assert.deepEqual(last().prompt[toggle], output[toggle], 'the linked switch stays under workflow control');
});
