import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openAgentSettings } from '../../../web/js/minimax_h3/agent_settings.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';

const find = (root, label) => descendants(root).find((item) => item.textContent === label || item.ariaLabel === label);
const settle = () => new Promise((resolve) => setImmediate(resolve));
test('settings manage shared accounts, supported effort choices, logs and confirmed removal', async () => {
  resetApi();
  resetDom();
  const info = {
    installed: true,
    authenticated: true,
    restricted: true,
    ready: true,
    version: 'test',
    models: [{ id: 'm1', name: 'Model one', efforts: ['low', 'medium', 'high'] }],
    selection: { model: 'm1', effort: 'medium' },
  };
  const status = { docker: true, agents: { codex: info, grok: { installed: false } } };
  const responses = () =>
    api.responses.push(
      jsonResponse(200, status),
      jsonResponse(200, {
        session: 'test',
        agent: 'codex',
        cursor: 3,
        lines: ['[job test] preparing', 'Login: https://example.test/device.', '<script>untrusted</script>'],
      }),
    );
  responses();
  const extension = extensionNamed('Arisu.MiniMaxH3.AgentSettings');
  const menu = document.createElement('div');
  const group = {
    buttons: [],
    append(button) {
      this.buttons.push(button);
      this.update();
    },
    remove(button) {
      this.buttons = this.buttons.filter((item) => item !== button);
      this.update();
    },
    update() {
      menu.replaceChildren(...this.buttons);
    },
  };
  app.menu = { actionsGroup: group };
  body.append(menu);
  extension.setup();
  assert.equal(menu.children.length, 0);
  const visibility = extension.settings.find((item) => item.type === 'boolean');
  visibility.onChange(true);
  const shortcut = find(menu, 'Manage agents');
  assert(shortcut);
  // Other extensions rebuild toolbar groups after startup; keep one registered shortcut.
  visibility.onChange(true);
  group.update();
  assert.deepEqual(menu.children, [shortcut]);
  visibility.onChange(false);
  assert.equal(menu.children.length, 0);
  visibility.onChange(true);
  shortcut.onclick();
  await settle();
  await settle();
  const shortcutDialog = descendants(body).find((item) => item.open);
  assert(shortcutDialog);
  shortcutDialog.close();
  responses();
  const setting = extension.settings[0].type();
  body.append(setting);
  find(setting, 'Manage agents…').onclick();
  await settle();
  await settle();
  const dialog = descendants(setting).find((item) => item.open);
  try {
    openAgentSettings();
    assert.equal(descendants(body).filter((item) => item.open).length, 1);
    assert.equal(find(dialog, 'Codex model').value, 'm1');
    assert.deepEqual(
      find(dialog, 'Codex effort').children.map((item) => item.value),
      ['low', 'medium', 'high'],
    );
    assert(find(find(dialog, 'Agent logs'), '[job test] preparing'));
    const login = find(dialog, 'https://example.test/device');
    assert.equal(login.href, 'https://example.test/device');
    assert.equal(login.rel, 'noopener noreferrer');
    assert(find(dialog, '<script>untrusted</script>'));
    assert.equal(descendants(dialog).filter((item) => item.tagName === 'SCRIPT').length, 0);
    assert.equal(descendants(dialog).filter((item) => item.role === 'tabpanel').length, 1);
    find(dialog, 'Grok Build').onclick();
    assert(find(dialog, 'Grok Build model') && !find(dialog, 'Codex model'));
    find(dialog, 'Codex').onclick();
    await settle();
    await settle();
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
    const confirm = descendants(dialog).find((item) => item.open);
    find(confirm, 'Cancel').onclick();
    await settle();
    assert.equal(api.calls.length, calls);
    find(current, 'Remove completely').onclick();
    await settle();
    const approved = descendants(dialog).find((item) => item.open);
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
