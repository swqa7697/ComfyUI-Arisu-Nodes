import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openAgentSettings } from '../../../web/js/minimax_h3/agent_settings.js';
import { api, jsonResponse, resetApi } from '../support/api.mjs';
import { app, extensionNamed } from '../support/app.mjs';
import { body, descendants, resetDom } from '../support/dom.mjs';

const find = (root, label) => descendants(root).find((item) => item.textContent === label || item.ariaLabel === label);
const settle = () => new Promise((resolve) => setImmediate(resolve));
test('settings manage shared accounts, model options, logs and confirmed removal', async () => {
  resetApi();
  resetDom();
  const info = {
    installed: true,
    authenticated: true,
    policy_ready: true,
    ready: true,
    version: 'test',
    models: [{ id: 'm1', name: 'Model one', efforts: ['low', 'medium', 'high'] }],
    selection: { model: 'm1', effort: 'medium' },
  };
  const error = 'Codex image is out of date. Choose Update CLI.';
  const status = {
    docker: true,
    agents: {
      codex: { installed: true, ready: false, update_required: true, error },
      grok: {
        ...info,
        models: [
          { ...info.models[0], context_windows: [256000, 500000], default_context_window: 256000 },
          { id: 'm2', name: 'Model two', efforts: [], context_windows: [500000], default_context_window: 500000 },
        ],
      },
    },
  };
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
  const shortcut = find(menu, 'Manage Agents');
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
  assert(find(shortcutDialog, error));
  assert(find(shortcutDialog, 'Login').disabled);
  assert(!find(shortcutDialog, 'Update CLI').disabled);
  status.agents.codex = info;
  api.responses.push(jsonResponse(202, { accepted: true }));
  responses();
  find(shortcutDialog, 'Update CLI').onclick();
  await settle();
  await settle();
  assert(!find(shortcutDialog, error));
  assert.equal(find(shortcutDialog, 'Codex Model').value, 'm1');
  shortcutDialog.close();
  responses();
  const setting = extension.settings[0].type();
  body.append(setting);
  find(setting, 'Manage Agents…').onclick();
  await settle();
  await settle();
  const dialog = descendants(setting).find((item) => item.open);
  try {
    openAgentSettings();
    assert.equal(descendants(body).filter((item) => item.open).length, 1);
    assert.equal(find(dialog, 'Codex Model').value, 'm1');
    assert.deepEqual(
      find(dialog, 'Codex Effort').children.map((item) => item.value),
      ['low', 'medium', 'high'],
    );
    assert(find(find(dialog, 'Agent Logs'), '[job test] preparing'));
    const login = find(dialog, 'https://example.test/device');
    assert.equal(login.href, 'https://example.test/device');
    assert.equal(login.rel, 'noopener noreferrer');
    assert(find(dialog, '<script>untrusted</script>'));
    assert.equal(descendants(dialog).filter((item) => item.tagName === 'SCRIPT').length, 0);
    assert.equal(descendants(dialog).filter((item) => item.role === 'tabpanel').length, 1);
    assert(!find(dialog, 'Context window (tokens)'));
    find(dialog, 'Grok Build').onclick();
    await settle();
    assert(find(dialog, 'Grok Build Model') && !find(dialog, 'Codex Model'));
    const windowSelect = () => find(dialog, 'Grok Build Context Window');
    assert.deepEqual(
      windowSelect().children.map((option) => option.textContent),
      ['Model default (256,000)', '256,000', '500,000'],
    );
    assert.equal(windowSelect().value, '');
    async function choose(label, value) {
      api.responses.push((_route, init) => {
        const { model, effort, context_window } = JSON.parse(init.body);
        status.agents.grok.selection = { model, effort, context_window };
        return jsonResponse(200, { accepted: true });
      });
      responses();
      const control = find(dialog, label);
      assert.equal(control.disabled, false);
      control.value = value;
      control.onchange();
      await settle();
    }
    await choose('Grok Build Context Window', '500000');
    await choose('Grok Build Effort', 'high');
    assert.equal(windowSelect().value, '500000');
    await choose('Grok Build Context Window', '');
    assert.equal(windowSelect().value, '');
    await choose('Grok Build Context Window', '500000');
    await choose('Grok Build Model', 'm2');
    assert.equal(windowSelect().value, '');
    assert.equal(windowSelect().disabled, true);
    assert.equal(windowSelect().children[0].textContent, 'Model default (500,000)');
    find(dialog, 'Codex').onclick();
    await settle();
    await settle();
    const codex = descendants(dialog).find((item) => item.id === 'arisu-agent-codex');
    const effort = find(codex, 'Codex Effort');
    api.responses.push(jsonResponse(400, { error: 'unsupported model or effort' }));
    responses();
    effort.value = 'high';
    effort.onchange();
    await settle();
    await settle();
    assert(find(dialog, 'unsupported model or effort'));
    const current = descendants(dialog).find((item) => item.id === 'arisu-agent-codex');
    const calls = api.calls.length;
    find(current, 'Remove Completely').onclick();
    await settle();
    const confirm = descendants(dialog).find((item) => item.open);
    find(confirm, 'Cancel').onclick();
    await settle();
    assert.equal(api.calls.length, calls);
    find(current, 'Remove Completely').onclick();
    await settle();
    const approved = descendants(dialog).find((item) => item.open);
    api.responses.push(jsonResponse(200, { accepted: true }));
    status.agents.codex = { installed: false };
    responses();
    find(approved, 'Remove Completely').onclick();
    await settle();
    await settle();
    const removed = descendants(dialog).find((item) => item.id === 'arisu-agent-codex');
    assert.equal(find(removed, 'Login').disabled, true);
    assert.equal(find(removed, 'Build Image').disabled, false);
  } finally {
    dialog.close();
  }
});
