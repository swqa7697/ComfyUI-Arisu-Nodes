import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openAgentSettings } from '../../../web/js/minimax_h3/agent_settings.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { extensionNamed } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';

const find = (root, label) => descendants(root).find((item) => item.textContent === label || item.ariaLabel === label);
const settle = () => new Promise((resolve) => setImmediate(resolve));
test('settings manage shared accounts, supported effort choices, logs and confirmed removal', async () => {
  resetApi();
  resetDom();
  const info = {
    installed: true,
    authenticated: true,
    auto: true,
    ready: true,
    version: 'test',
    models: [{ id: 'm1', name: 'Model one', efforts: ['low', 'medium', 'high'] }],
    selection: { model: 'm1', effort: 'medium' },
  };
  const status = { docker: true, agents: { codex: info, grok: { installed: false } } };
  const responses = () =>
    api.responses.push(jsonResponse(200, status), jsonResponse(200, { container: 'named-log', lines: ['[job test] preparing'] }));
  responses();
  const setting = extensionNamed('Arisu.MiniMaxH3.AgentSettings').settings[0].type();
  find(setting, 'Manage agents…').onclick();
  await settle();
  await settle();
  const dialog = body.children.find((item) => item.open);
  try {
    openAgentSettings();
    assert.equal(body.children.filter((item) => item.open).length, 1);
    assert.equal(find(dialog, 'Codex model').value, 'm1');
    assert.deepEqual(
      find(dialog, 'Codex effort').children.map((item) => item.value),
      ['low', 'medium', 'high'],
    );
    assert.equal(find(dialog, 'Agent logs').textContent, '[job test] preparing');
    const codex = descendants(dialog).find((item) => item.id === 'arisu-agent-codex');
    const effort = find(codex, 'Codex effort');
    api.responses.push(jsonResponse(400, { error: 'unsupported model or effort' }));
    responses();
    effort.value = 'high';
    effort.onchange();
    await settle();
    await settle();
    assert(find(dialog, 'unsupported model or effort'));
    const current = descendants(dialog).find((item) => item.id === 'arisu-agent-codex');
    const calls = api.calls.length;
    find(current, 'Remove completely').onclick();
    await settle();
    const confirm = body.children.find((item) => item !== dialog && item.open);
    find(confirm, 'Cancel').onclick();
    await settle();
    assert.equal(api.calls.length, calls);
    find(current, 'Remove completely').onclick();
    await settle();
    const approved = body.children.find((item) => item !== dialog && item.open);
    api.responses.push(jsonResponse(200, { accepted: true }));
    status.agents.codex = { installed: false };
    responses();
    find(approved, 'Remove completely').onclick();
    await settle();
    await settle();
    const removed = descendants(dialog).find((item) => item.id === 'arisu-agent-codex');
    assert.equal(find(removed, 'Login').disabled, true);
    assert.equal(find(removed, 'Build image').disabled, false);
  } finally {
    dialog.close();
  }
});
