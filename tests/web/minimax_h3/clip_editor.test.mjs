// Drive the production modal through its GUI; no test-only exports or timer assumptions.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { editClip } from '../../../web/js/minimax_h3/clip_editor.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';

const control = (root, name) => descendants(root).find((element) => element.ariaLabel === name || element.textContent === name);
const settle = () => new Promise((resolve) => setImmediate(resolve));
test('clip drafts preserve free precision, fixed durations and selection playback, and release proxy interests on close', async () => {
  resetDom();
  resetApi();
  const item = { root: 'input', path: 'movie.mkv', kind: 'video' };
  let result = editClip(item, { kind: 'video', duration: 12, has_audio: true, revision: 'r' });
  let dialog = body.children[0];
  const player = descendants(dialog).find((element) => element.tagName === 'VIDEO');
  control(dialog, 'Snapping').value = '0';
  control(dialog, 'Start seconds').value = '1.23456';
  control(dialog, 'Start seconds').onchange();
  control(dialog, 'End seconds').value = '6.78901';
  control(dialog, 'End seconds').onchange();
  control(dialog, 'Apply').onclick();
  assert.deepEqual(await result, { clip: { start: 1.23456, end: 6.78901 }, include_audio: true });
  result = editClip(item, { kind: 'video', duration: 12, has_audio: false, revision: 'r' });
  dialog = body.children[0];
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
});
