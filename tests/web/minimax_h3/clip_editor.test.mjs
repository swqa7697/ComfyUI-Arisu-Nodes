// Drive the production modal through its GUI; no test-only exports or timer assumptions.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { editClip } from '../../../web/js/minimax_h3/clip_editor.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';

const control = (root, name) => descendants(root).find((element) => element.ariaLabel === name || element.textContent === name);
const handleOf = (timeline, name) => descendants(timeline).find((element) => element.handle === name);
const settle = () => new Promise((resolve) => setImmediate(resolve));
test('clip drafts snap to tenths on a draggable timeline, keep locked durations and selection playback, and release proxy interests on close', async () => {
  resetDom();
  resetApi();
  const item = { root: 'input', path: 'movie.mkv', kind: 'video' };
  let result = editClip(item, { kind: 'video', duration: 12, has_audio: true, revision: 'r' });
  let dialog = body.children[0];
  const player = descendants(dialog).find((element) => element.tagName === 'VIDEO');
  // The timeline is the only transport: the element carries no native controls.
  assert.ok(!player.controls);
  // Typed precision snaps to the default tenth grid; nothing finer exists in the editor.
  assert.deepEqual(
    control(dialog, 'Snapping').children.map((option) => option.value),
    ['0.1', '1'],
  );
  control(dialog, 'Start seconds').value = '1.23456';
  control(dialog, 'Start seconds').onchange();
  control(dialog, 'End seconds').value = '6.78901';
  control(dialog, 'End seconds').onchange();
  const readout = descendants(dialog).find((element) => element.tagName === 'OUTPUT' && element.textContent?.includes(' in '));
  assert.match(readout.textContent, /in 0:01\.2 · out 0:06\.8$/);
  assert.doesNotMatch(readout.textContent, /\d\.\d{2}/);
  // A 12 s source on a 1000 px track: dragging the in bracket moves only the start, on the grid.
  const timeline = control(dialog, 'Timeline');
  timeline.naturalWidth = 1000;
  timeline.onpointerdown({ clientX: 100, pointerId: 1, button: 0, target: handleOf(timeline, 'start') });
  timeline.onpointermove({ clientX: 300, pointerId: 1, target: timeline });
  timeline.onpointerup({ pointerId: 1 });
  assert.equal(control(dialog, 'Start seconds').value, '3.6');
  assert.equal(handleOf(timeline, 'start').style.left, '30%');
  // A press on the ruler scrubs, and the playhead keeps scrubbing while dragged.
  timeline.onpointerdown({ clientX: 500, pointerId: 1, button: 0, target: timeline });
  assert.equal(player.currentTime, 6);
  timeline.onpointermove({ clientX: 575, pointerId: 1, target: handleOf(timeline, 'playhead') });
  timeline.onpointerup({ pointerId: 1 });
  assert.equal(player.currentTime, 6.9);
  // O and I mark the brackets at the playhead; arrows nudge by a tenth, or a second with Shift; Space plays.
  timeline.onkeydown({ key: 'o' });
  assert.equal(control(dialog, 'End seconds').value, '6.9');
  timeline.onkeydown({ key: 'Home' });
  timeline.onkeydown({ key: 'ArrowRight', shiftKey: true });
  timeline.onkeydown({ key: 'ArrowLeft' });
  timeline.onkeydown({ key: 'ArrowRight' });
  assert.equal(player.currentTime, 1);
  timeline.onkeydown({ key: 'i' });
  assert.equal(control(dialog, 'Start seconds').value, '1');
  timeline.onkeydown({ key: ' ' });
  assert.equal(player.paused, false);
  timeline.onkeydown({ key: ' ' });
  assert.equal(player.paused, true);
  control(dialog, 'Apply').onclick();
  assert.deepEqual(await result, { clip: { start: 1, end: 6.9 }, include_audio: true });
  result = editClip(item, { kind: 'video', duration: 12, has_audio: false, revision: 'r' });
  dialog = body.children[0];
  assert.equal(control(dialog, 'Include audio'), undefined);
  assert.equal(control(dialog, '15s').disabled, true);
  control(dialog, '5s').onclick();
  control(dialog, 'Start seconds').value = '11';
  control(dialog, 'Start seconds').onchange();
  assert.equal(control(dialog, 'Start seconds').value, '7');
  assert.equal(control(dialog, 'End seconds').value, '12');
  const current = descendants(dialog).find((element) => element.tagName === 'VIDEO');
  current.currentTime = 0;
  await current.play();
  assert.equal(current.currentTime, 7);
  current.currentTime = 12;
  current.ontimeupdate();
  assert.equal(current.paused, true);
  control(dialog, 'Selection end behavior').value = 'loop';
  await current.play();
  current.currentTime = 12;
  current.ontimeupdate();
  assert.equal(current.currentTime, 7);
  // Codec errors request a proxy; network errors don't.
  current.error = { code: 2 };
  current.onerror();
  assert.equal(api.calls.length, 0);
  api.responses.push(
    jsonResponse(200, { revision: 'r' }),
    jsonResponse(202, { id: 'interest' }),
    jsonResponse(200, { state: 'ready', url: '/arisu/resources/proxy/interest/view' }),
  );
  current.error = { code: 4 };
  current.onerror();
  await settle();
  assert(current.src.includes('/proxy/interest/view'));
  api.responses.push(jsonResponse(200, { released: true }));
  control(dialog, 'Cancel').onclick();
  assert.equal(await result, null);
  await settle();
  assert(api.calls.some((call) => call.init?.method === 'DELETE'));
  assert.equal(current.paused, true);
  assert.equal(body.children.length, 0);
  assert.equal(player.paused, true);
  // Audio gets the compact dialog: the element plays but nothing previews, and the ruler labels the source.
  result = editClip({ root: 'input', path: 'voice.wav', kind: 'audio' }, { kind: 'audio', duration: 30, has_audio: true, revision: 'r' });
  dialog = body.children[0];
  const audio = descendants(dialog).find((element) => element.tagName === 'AUDIO');
  assert.equal(audio.hidden, true);
  assert.ok(!audio.controls);
  assert.equal(
    descendants(dialog).some((element) => element.className === 'arisu-clip-stage'),
    false,
  );
  const ruler = control(dialog, 'Timeline');
  assert.deepEqual(
    descendants(ruler)
      .filter((element) => element.className?.startsWith('arisu-clip-tick-label'))
      .map((element) => element.textContent),
    ['0:00', '0:05', '0:10', '0:15', '0:20', '0:25', '0:30'],
  );
  // Dragging the selected range keeps its length and stops at the source end.
  ruler.naturalWidth = 1000;
  ruler.onpointerdown({ clientX: 100, pointerId: 1, button: 0, target: handleOf(ruler, 'range') });
  ruler.onpointermove({ clientX: 1000, pointerId: 1, target: ruler });
  ruler.onpointerup({ pointerId: 1 });
  assert.equal(control(dialog, 'Start seconds').value, '25');
  assert.equal(control(dialog, 'End seconds').value, '30');
  control(dialog, 'Cancel').onclick();
  assert.equal(await result, null);
  assert.equal(body.children.length, 0);
});
