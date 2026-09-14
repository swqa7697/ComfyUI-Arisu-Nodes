// One agent-management surface shared by ComfyUI Settings and the node's Setup button.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { closeOnBackdropClick, el } from '../common/dom.js';

const ROUTE = '/arisu/workbench';
let pending;
let cached;
let checked = 0;
let active;

const STYLE = `
.arisu-agents{width:min(700px,94vw);max-height:90vh;padding:0;border:1px solid var(--border-color,#444);border-radius:10px;
 background:var(--comfy-menu-bg,#303030);color:var(--fg-color,#ddd);font:13px/1.5 Arial,system-ui,sans-serif;}
.arisu-agents::backdrop{background:#0009;}.arisu-agents header,.arisu-agents footer{display:flex;align-items:center;gap:12px;padding:14px 18px;}
.arisu-agents header strong{flex:1;font-size:16px;}.arisu-agents .content{padding:0 18px 18px;overflow:auto;max-height:70vh;}
.arisu-agents section{padding:14px 0;border-top:1px solid var(--border-color,#444);}.arisu-agents h3{margin:0 0 8px;}
.arisu-agents p{margin:6px 0;color:var(--descrip-text,#aaa);}
.arisu-agents button,.arisu-agents select{font:inherit;color:inherit;background:var(--comfy-input-bg,#222);border:1px solid var(--border-color,#555);
 border-radius:5px;min-height:34px;padding:5px 10px;cursor:pointer;}.arisu-agents button:hover{border-color:#6cbfae;}
.arisu-agents button:disabled{opacity:.45;cursor:default;}.arisu-agents :focus-visible{outline:2px solid currentColor;outline-offset:2px;}
.arisu-agents .actions,.arisu-agents .fields{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;}
.arisu-agents label{display:flex;align-items:center;gap:8px;}.arisu-agents pre{white-space:pre-wrap;overflow-wrap:anywhere;
 background:var(--comfy-input-bg,#222);padding:12px;max-height:240px;overflow:auto;font:11px/1.6 monospace;}
.arisu-agents .error{color:var(--error-text,#efaaaa);}.arisu-agents .danger{border-color:#bd6c6c;}
@media(pointer:coarse){.arisu-agents button,.arisu-agents select{min-height:44px;}}
`;

/** Shared status requests prevent every Workbench node from launching its own Docker probes. */
export async function agentStatus(force = false) {
  if (!force && cached && Date.now() - checked < 3000) return cached;
  if (!pending) {
    pending = api
      .fetchApi(ROUTE + '/status')
      .then(async (response) => {
        if (!response.ok) throw new Error('Unable to read agent status');
        cached = await response.json();
        checked = Date.now();
        return cached;
      })
      .finally(() => {
        pending = null;
      });
  }
  return pending;
}

/** Post a fixed structured action, with consistent error handling. */
export async function workbenchRequest(path, value) {
  const response = await api.fetchApi(ROUTE + path, {
    method: 'POST',
    keepalive: path === '/release',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(value),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error ?? 'Workbench request failed');
  checked = 0;
  return data;
}

async function confirmRemoval(agent) {
  const dialog = el('dialog', { className: 'arisu-agents' });
  let confirmed = false;
  dialog.append(
    el('style', { textContent: STYLE }),
    el('header', {}, [el('strong', { textContent: 'Remove ' + agent + '?' })]),
    el('div', { className: 'content' }, [
      el('p', { textContent: 'This deletes this agent’s images and saved login. You will need to build and sign in again.' }),
      el('div', { className: 'actions' }, [
        el('button', { textContent: 'Cancel', onclick: () => dialog.close() }),
        el('button', {
          textContent: 'Remove completely',
          className: 'danger',
          onclick: () => {
            confirmed = true;
            dialog.close();
          },
        }),
      ]),
    ]),
  );
  closeOnBackdropClick(dialog);
  return new Promise((resolve) => {
    dialog.onclose = () => {
      dialog.remove();
      resolve(confirmed);
    };
    document.body.append(dialog);
    dialog.showModal();
  });
}

/** Open the same management dialog from Settings or any Workbench node. */
export function openAgentSettings(selected = 'codex') {
  if (active) {
    active.focus();
    return;
  }
  const dialog = el('dialog', { className: 'arisu-agents', ariaLabel: 'Prompt Workbench agents' });
  active = dialog;
  const content = el('div', { className: 'content' });
  const error = el('p', { className: 'error', role: 'status', ariaLive: 'polite' });
  const logs = el('pre', { tabIndex: 0, ariaLabel: 'Agent logs' });
  let closed = false;
  let timer;
  let busy = false;
  let signature = '';
  const sections = el('div');
  const logName = el('p');
  async function action(agent, operation, extra = {}) {
    if (operation === 'remove' && !(await confirmRemoval(agent === 'codex' ? 'Codex' : 'Grok Build'))) return;
    busy = true;
    error.textContent = '';
    try {
      await workbenchRequest('/action', { agent, action: operation, confirm: operation === 'remove', ...extra });
      signature = '';
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      busy = false;
      await refresh(true);
    }
  }
  function card(agent, status, docker, operation) {
    const info = status ?? {};
    const title = agent === 'codex' ? 'Codex' : 'Grok Build';
    const model = el(
      'select',
      { ariaLabel: title + ' model' },
      (info.models ?? []).map((item) => el('option', { value: item.id, textContent: item.name })),
    );
    model.value = info.selection?.model ?? '';
    const effort = el('select', { ariaLabel: title + ' effort' });
    function updateEfforts() {
      const supported = info.models?.find((item) => item.id === model.value)?.efforts ?? [];
      effort.replaceChildren(
        ...(supported.length ? supported : ['']).map((value) => el('option', { value, textContent: value || 'Provider default' })),
      );
      effort.value = supported.includes(info.selection?.effort)
        ? info.selection.effort
        : supported.includes('medium')
          ? 'medium'
          : (supported[0] ?? '');
      effort.disabled = !supported.length || busy || operation?.state === 'running';
    }
    updateEfforts();
    model.onchange = () => {
      updateEfforts();
      void action(agent, 'configure', { model: model.value, effort: effort.value });
    };
    effort.onchange = () => void action(agent, 'configure', { model: model.value, effort: effort.value });
    model.disabled = !info.models?.length || busy || operation?.state === 'running';
    const state = !docker
      ? 'Docker is unavailable to ComfyUI.'
      : !info.installed
        ? 'Build the image to begin.'
        : !info.auto
          ? 'Update required: compatible Auto mode is unavailable.'
          : !info.authenticated
            ? 'Sign in to enable generation.'
            : !info.ready
              ? 'No supported models available.'
              : 'Ready';
    const buttons = [
      ['Build image', 'build', info.installed],
      ['Update CLI', 'update', !info.installed],
      ['Login', 'login', !info.installed],
      ['Logout', 'logout', !info.authenticated],
      ['Remove completely', 'remove', !info.installed],
    ].map(([label, operationName, disabled]) =>
      el('button', {
        textContent: label,
        disabled: !docker || busy || disabled || operation?.state === 'running',
        onclick: () => void action(agent, operationName),
      }),
    );
    return el('section', { id: 'arisu-agent-' + agent }, [
      el('h3', { textContent: title + (agent === selected ? ' · selected' : '') }),
      el('p', { textContent: state + (info.version ? ' · ' + info.version : '') }),
      el('div', { className: 'actions' }, buttons),
      el('div', { className: 'fields' }, [
        el('label', {}, [el('span', { textContent: 'Model' }), model]),
        el('label', {}, [el('span', { textContent: 'Effort' }), effort]),
      ]),
    ]);
  }
  async function refresh(force = false) {
    try {
      const status = await agentStatus(force);
      if (closed) return;
      const next = JSON.stringify(status);
      if (next !== signature) {
        signature = next;
        sections.replaceChildren(...['codex', 'grok'].map((agent) => card(agent, status.agents?.[agent], status.docker, status.operation)));
      }
      const response = await api.fetchApi(ROUTE + '/logs');
      const data = await response.json();
      if (closed) return;
      logs.textContent = (data.lines ?? []).join('\n');
      logName.textContent = data.container ? 'Docker logs: ' + data.container : '';
      if (status.operation?.error) error.textContent = status.operation.error;
    } catch (failure) {
      if (!closed) error.textContent = failure.message;
    }
  }
  content.append(
    el('p', { textContent: 'Shared by trusted users of this ComfyUI instance. Login uses a browser device code shown in the logs below.' }),
    error,
    sections,
    el('h3', { textContent: 'Activity' }),
    logName,
    logs,
  );
  dialog.append(
    el('style', { textContent: STYLE }),
    el('header', {}, [
      el('strong', { textContent: 'Prompt Workbench · Agents' }),
      el('button', { textContent: 'Close', onclick: () => dialog.close() }),
    ]),
    content,
  );
  closeOnBackdropClick(dialog);
  dialog.onclose = () => {
    closed = true;
    clearInterval(timer);
    dialog.remove();
    active = null;
  };
  document.body.append(dialog);
  dialog.showModal();
  void refresh(true);
  timer = setInterval(() => void refresh(), 2000);
}

app.registerExtension({
  name: 'Arisu.MiniMaxH3.AgentSettings',
  settings: [
    {
      id: 'Arisu.PromptWorkbench.Agents',
      name: 'Prompt Workbench agents',
      category: ['Arisu', 'Prompt Workbench', 'Agents'],
      type: () =>
        el('div', {}, [el('button', { className: 'comfy-btn', textContent: 'Manage agents…', onclick: () => openAgentSettings() })]),
    },
  ],
});
