// One agent-management surface shared by ComfyUI Settings and the node's Setup button.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { closeOnBackdropClick, el } from '../common/dom.js';
import { ACTIVITY_STYLE, createActivity } from './agent_activity.js';

const ROUTE = '/arisu/workbench';
let pending;
let cached;
let checked = 0;
let active;
let shortcut;
const SHORTCUT_SETTING = 'Arisu.PromptWorkbench.ShowAgentsShortcut';

function showShortcut(visible) {
  if (!shortcut) return;
  // Register with the group so later toolbar rebuilds retain the shortcut.
  const group = app.menu.actionsGroup;
  if (visible) {
    if (!group.buttons.includes(shortcut)) group.append(shortcut);
  } else group.remove(shortcut);
}

const STYLE = `
.arisu-agents{width:min(1000px,96vw);max-height:92vh;padding:0;border:1px solid var(--border-color,#444);border-radius:10px;box-sizing:border-box;box-shadow:0 24px 64px #0009;
 background:var(--comfy-menu-bg,#303030);color:var(--fg-color,#ddd);font:13px/1.5 Arial,system-ui,sans-serif;}
.arisu-agents.management{height:92vh;}
.arisu-agents[open]{display:flex;flex-direction:column;overflow:hidden;}
.arisu-agents::backdrop{background:#0009;backdrop-filter:blur(3px);}.arisu-agents header,.arisu-agents footer{display:flex;align-items:center;gap:12px;padding:14px 18px;flex-shrink:0;border-bottom:1px solid var(--border-color,#444);}
.arisu-agents header strong{flex:1;font-size:16px;}.arisu-agents .content{padding:12px 18px 18px;overflow:auto;min-height:0;scrollbar-width:thin;}
.arisu-agents section{padding:12px;margin:0;border:1px solid var(--border-color,#444);border-radius:6px;}.arisu-agents h3{margin:0 0 8px;}
.arisu-agents p{margin:6px 0;color:var(--descrip-text,#aaa);}
.arisu-agents button,.arisu-agents select{font:inherit;color:inherit;background:var(--comfy-input-bg,#222);border:1px solid var(--border-color,#555);
 border-radius:5px;min-height:34px;padding:5px 10px;cursor:pointer;}.arisu-agents button:enabled:hover{border-color:var(--arisu-blue);}
.arisu-agents button:disabled{opacity:.45;cursor:default;}.arisu-agents :focus-visible{outline:2px solid var(--arisu-blue);outline-offset:2px;}
.arisu-agents select{min-width:0;max-width:100%;}
.arisu-agents select:focus{outline:none;border-color:var(--arisu-blue);box-shadow:inset 0 0 0 1px var(--arisu-blue);}
.arisu-agents .fields label{flex:1;min-width:0;align-items:stretch;flex-direction:column;gap:4px;}
.arisu-agents .actions,.arisu-agents .fields{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;}
.arisu-agents label{display:flex;align-items:center;gap:8px;}.arisu-agents pre{white-space:pre-wrap;overflow-wrap:anywhere;
 background:var(--comfy-input-bg,#222);padding:12px;max-height:240px;overflow:auto;font:11px/1.6 monospace;}
.arisu-agents.management>.content{display:flex;flex-direction:column;flex:1;gap:10px;overflow:hidden;}
.arisu-agents .settings-area{flex-shrink:0;max-height:48vh;overflow:auto;padding:2px;scrollbar-width:thin;}
.arisu-agents .tabs{display:flex;gap:6px;margin-bottom:8px;}.arisu-agents .tabs button{flex:1;}
.arisu-agents .tabs button[aria-selected="true"]{border-color:var(--arisu-blue);background:color-mix(in srgb,var(--comfy-input-bg,#222) 85%,var(--arisu-blue));}
.arisu-agents .error:empty{display:none;}
.arisu-agents .error{color:var(--error-text,#efaaaa);}.arisu-agents .danger{border-color:#bd6c6c;}
@media(pointer:coarse){.arisu-agents button,.arisu-agents select{min-height:44px;}}
`;

/** Shared status requests prevent every Workbench node from launching its own Docker probes. */
export async function agentStatus(force = false) {
  if (!force && cached && Date.now() - checked < 3000) return cached;
  if (!pending) {
    pending = api
      .fetchApi(`${ROUTE}/status`)
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

async function confirmRemoval(agent, parent) {
  const dialog = el('dialog', { className: 'arisu-agents' });
  let confirmed = false;
  dialog.append(
    el('style', { textContent: STYLE }),
    el('header', {}, [el('strong', { textContent: `Remove ${agent}?` })]),
    el('div', { className: 'content' }, [
      el('p', { textContent: 'This deletes this agent’s images and saved login. You will need to build and sign in again.' }),
      el('div', { className: 'actions' }, [
        el('button', { textContent: 'Cancel', onclick: () => dialog.close() }),
        el('button', {
          textContent: 'Remove Completely',
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
    parent.append(dialog);
    dialog.showModal();
  });
}

/** Open the same management dialog from Settings or any Workbench node. */
export function openAgentSettings(selected = 'codex', parent = document.body) {
  if (active) {
    active.focus();
    return;
  }
  const dialog = el('dialog', { className: 'arisu-agents management', ariaLabel: 'Prompt Workbench Agents' });
  active = dialog;
  const content = el('div', { className: 'content' });
  const error = el('p', { className: 'error', role: 'status', ariaLive: 'polite' });
  const activity = createActivity();
  selected = selected === 'grok' ? 'grok' : 'codex';
  let latest;
  let refreshing = false;
  let closed = false;
  let timer;
  let busy = false;
  let signature = '';
  const sections = el('div');
  const tabs = el('div', { className: 'tabs', role: 'tablist', ariaLabel: 'Agents' });
  const tabButtons = ['codex', 'grok'].map((agent, index) => {
    const button = el('button', {
      id: `arisu-tab-${agent}`,
      role: 'tab',
      textContent: agent === 'codex' ? 'Codex' : 'Grok Build',
      onclick: () => select(agent),
      onkeydown: (event) => {
        const next =
          event.key === 'Home' ? 0 : event.key === 'End' ? 1 : ['ArrowLeft', 'ArrowRight'].includes(event.key) ? 1 - index : null;
        if (next === null) return;
        event.preventDefault();
        select(next ? 'grok' : 'codex');
        tabButtons[next].focus();
      },
    });
    button.setAttribute('aria-controls', `arisu-agent-${agent}`);
    return button;
  });
  tabs.append(...tabButtons);
  function select(agent) {
    selected = agent;
    signature = '';
    activity.reset();
    draw();
    void refresh();
  }
  function draw() {
    tabButtons.forEach((button, index) => {
      const chosen = selected === (index ? 'grok' : 'codex');
      button.setAttribute('aria-selected', String(chosen));
      button.tabIndex = chosen ? 0 : -1;
    });
    if (latest) sections.replaceChildren(card(selected, latest.agents?.[selected], latest.docker, latest.operation));
  }
  async function action(agent, operation, extra = {}) {
    if (operation === 'remove' && !(await confirmRemoval(agent === 'codex' ? 'Codex' : 'Grok Build', dialog))) return;
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
      { ariaLabel: `${title} Model` },
      (info.models ?? []).map((item) => el('option', { value: item.id, textContent: item.name })),
    );
    model.value = info.selection?.model ?? '';
    const effort = el('select', { ariaLabel: `${title} Effort` });
    function updateEfforts() {
      const supported = info.models?.find((item) => item.id === model.value)?.efforts ?? [];
      effort.replaceChildren(
        ...(supported.length ? supported : ['']).map((value) =>
          el('option', { value, textContent: value ? value[0].toUpperCase() + value.slice(1) : 'Provider Default' }),
        ),
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
        : !info.policy_ready
          ? 'Update required: Workbench policy is incompatible.'
          : !info.authenticated
            ? 'Sign in to enable generation.'
            : !info.ready
              ? 'No supported models available.'
              : 'Ready';
    const buttons = [
      ['Build Image', 'build', info.installed],
      ['Update CLI', 'update', !info.installed],
      ['Login', 'login', !info.installed],
      ['Logout', 'logout', !info.authenticated],
      ['Remove Completely', 'remove', !info.installed],
    ].map(([label, operationName, disabled]) =>
      el('button', {
        textContent: label,
        className: operationName === 'remove' ? 'danger' : 'arisu-action',
        disabled: !docker || busy || disabled || operation?.state === 'running',
        onclick: () => void action(agent, operationName),
      }),
    );
    const panel = el('section', { id: `arisu-agent-${agent}`, role: 'tabpanel' }, [
      el('p', { textContent: state + (info.version ? ` · ${info.version}` : '') }),
      el('div', { className: 'actions' }, buttons),
      el('div', { className: 'fields' }, [
        el('label', {}, [el('span', { textContent: 'Model' }), model]),
        el('label', {}, [el('span', { textContent: 'Effort' }), effort]),
      ]),
    ]);
    panel.setAttribute('aria-labelledby', `arisu-tab-${agent}`);
    return panel;
  }
  async function refresh(force = false) {
    if (refreshing || closed) return;
    refreshing = true;
    try {
      const status = await agentStatus(force);
      if (closed) return;
      latest = status;
      const next = JSON.stringify(status);
      if (next !== signature) {
        signature = next;
        draw();
      }
      const more = await activity.read({ agent: selected });
      if (more && !closed) setTimeout(() => void refresh(), 0);
      if (status.operation?.error) error.textContent = status.operation.error;
    } catch (failure) {
      if (!closed) error.textContent = failure.message;
    } finally {
      refreshing = false;
    }
  }
  content.append(
    el('p', { textContent: 'Shared by trusted users of this ComfyUI instance. Login uses a browser device code shown in the logs below.' }),
    error,
    el('div', { className: 'settings-area' }, [tabs, sections]),
    activity.element,
  );
  dialog.append(
    el('style', { textContent: STYLE + ACTIVITY_STYLE }),
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
    activity.reset();
    dialog.remove();
    active = null;
  };
  parent.append(dialog);
  dialog.showModal();
  draw();
  void refresh(true);
  timer = setInterval(() => void refresh(), 2000);
}

app.registerExtension({
  name: 'Arisu.MiniMaxH3.AgentSettings',
  setup() {
    shortcut = el(
      'button',
      {
        className: 'comfy-btn arisu-agents-shortcut',
        title: 'Manage Prompt Workbench Agents',
        ariaLabel: 'Manage Agents',
        type: 'button',
        onclick: () => openAgentSettings(),
      },
      [
        el('img', { src: new URL('../../assets/icon.svg', import.meta.url).href, alt: '', width: 20, height: 20 }),
        el('span', { textContent: 'Agents' }),
      ],
    );
    document.body.append(
      el('style', {
        textContent: `
      .arisu-agents-shortcut{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;
        min-height:32px;padding:6px 10px;border-radius:6px;font:inherit;cursor:pointer;}
      .arisu-agents-shortcut img{display:block;width:20px;height:20px;flex-shrink:0;}
      .arisu-agents-shortcut:focus-visible{outline:2px solid var(--fg-color);outline-offset:2px;}
    `,
      }),
    );
    showShortcut(app.extensionManager.setting.get(SHORTCUT_SETTING) === true);
  },
  settings: [
    {
      id: 'Arisu.PromptWorkbench.Agents',
      name: 'Prompt Workbench Agents',
      category: ['Arisu Nodes', 'Prompt Workbench', 'Agents'],
      type: () => {
        // Keep native modals inside Settings so its outside-click handler sees them as descendants.
        const container = el('div', { className: 'arisu-settings-entry' });
        container.append(
          el('button', {
            className: 'comfy-btn',
            textContent: 'Manage Agents…',
            onclick: () => openAgentSettings('codex', container),
          }),
        );
        return container;
      },
    },
    {
      id: SHORTCUT_SETTING,
      name: 'Show Agents Shortcut',
      category: ['Arisu Nodes', 'Prompt Workbench', 'Show Agents Shortcut'],
      type: 'boolean',
      defaultValue: false,
      tooltip: 'Show an Agents button in the ComfyUI menu to open agent management.',
      onChange: (value) => showShortcut(value === true),
    },
  ],
});
