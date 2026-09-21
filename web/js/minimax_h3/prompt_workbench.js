// A compact prompt workbench: generation is explicit and every draft requires Apply.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { forwardToCanvas, keepScrollWheel } from '../common/canvas_gestures.js';
import { el } from '../common/dom.js';
import { installSelectionGuards, observeWorkflowLoads } from '../common/selection_context.js';
import { hideWidget, setWidget } from '../common/widgets.js';
import { ACTIVITY_STYLE, openAgentActivity } from './agent_activity.js';
import { agentStatus, openAgentSettings, workbenchRequest } from './agent_settings.js';
import { captureWorkbenchPrompt, effectiveBundles, executionTarget, inputSource } from './settings_broadcast.js';

const TYPE = 'ArisuMiniMaxH3PromptWorkbench';
const nodes = new WeakMap();
const FIELDS = [
  'agent',
  'skill',
  'context_length',
  'audio_context_length',
  'motion_notes',
  'reference_notes',
  'trigger_words',
  'requirements',
  'finalized_prompt',
  'prepare_job',
  'motion_enabled',
];

const STYLE = `
.arisu-workbench{width:100%;height:100%;box-sizing:border-box;container-type:inline-size;padding:10px;
 --surface:var(--comfy-input-bg,#222);--panel:var(--comfy-menu-bg,#353535);--line:var(--border-color,#444);
 --text:var(--input-text,#ccc);--label:color-mix(in srgb,var(--descrip-text,#aaa),var(--fg-color,#ddd) 30%);--accent:var(--arisu-accent);
 --image:var(--arisu-image);--video:var(--arisu-video);--audio:var(--arisu-audio);color:var(--text);font:12px/1.45 Arial,system-ui,sans-serif;}
.arisu-workbench *{box-sizing:border-box;}.arisu-workbench .columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
 gap:12px;height:100%;min-height:0;}.arisu-workbench .generation{display:flex;flex-direction:column;gap:10px;min-width:0;overflow:hidden;
 border:0;margin:0;padding:0;}.arisu-workbench .field{display:flex;flex-direction:column;gap:4px;min-width:0;}
.arisu-workbench .label{color:var(--label);font-size:12px;line-height:20px;}
.arisu-workbench input,.arisu-workbench textarea,.arisu-workbench select{color:var(--text);background:var(--surface);border:1px solid var(--line);
 border-radius:4px;padding:7px 9px;min-width:0;width:100%;font:inherit;transition:border-color 130ms ease,background-color 130ms ease;}
.arisu-workbench select{border-radius:4px;min-height:32px;cursor:pointer;padding:5px 8px;}
.arisu-workbench textarea{resize:vertical;line-height:1.6;scrollbar-width:thin;}.arisu-workbench input{min-height:28px;}
.arisu-workbench textarea:focus,.arisu-workbench input:focus,.arisu-workbench select:focus{border-color:var(--accent);}
.arisu-workbench :focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
.arisu-workbench :is(textarea,input,select):focus{outline:none;box-shadow:inset 0 0 0 1px var(--accent);}
.arisu-workbench .field:focus-within>.label,.arisu-workbench .final:focus-within>.label{color:var(--accent);}
.arisu-workbench .selectors{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;}
.arisu-workbench .section-title{font-size:12px;line-height:20px;color:var(--text);font-weight:600;}
.arisu-workbench .final>.label{font-weight:600;color:var(--text);}
.arisu-workbench .generation>.section-title{margin-bottom:-6px;}
.arisu-workbench :is(input,textarea)::placeholder{color:var(--label);opacity:.75;}
.arisu-workbench .context{border-top:1px solid var(--line);padding-top:8px;}
.arisu-workbench .motion-switch{float:right;display:inline-flex;align-items:center;gap:6px;margin-left:8px;cursor:pointer;}
.arisu-workbench .context summary .motion-toggle{width:16px;height:16px;min-height:16px;margin:0;padding:0;accent-color:var(--accent);}
.arisu-workbench .motion-switch:has(input:disabled){opacity:.5;cursor:not-allowed;}
.arisu-workbench .context summary{cursor:pointer;color:var(--label);padding:2px 0 6px;}
.arisu-workbench .context summary:focus-visible{outline-offset:-2px;}
.arisu-workbench .motion{border:1px solid var(--line);margin:0;padding:8px;border-radius:4px;background:color-mix(in srgb,var(--surface) 65%,var(--panel));
 display:flex;flex-direction:column;gap:6px;}.arisu-workbench .motion label{display:grid;grid-template-columns:1fr 90px;gap:8px;align-items:center;}
.arisu-workbench .motion textarea{min-height:64px;}
.arisu-workbench .motion .motion_notes{display:flex;align-items:stretch;}.arisu-workbench .motion_notes>.label{display:none;}
.arisu-workbench .generation-fields{border:0;margin:0;display:flex;flex:1;min-height:0;flex-direction:column;gap:10px;overflow:auto;padding:2px 4px 4px;scrollbar-width:thin;}
.arisu-workbench .footer{flex-shrink:0;}.arisu-workbench fieldset:disabled{opacity:.6;}
.arisu-workbench .references{border:1px solid var(--line);padding:8px;border-radius:4px;background:var(--surface);display:flex;flex-direction:column;gap:6px;max-height:210px;overflow:auto;}
.arisu-workbench .reference{display:grid;grid-template-columns:4px minmax(70px,110px) minmax(0,1fr);align-items:center;gap:7px;min-width:0;}
.arisu-workbench .kind{height:22px;background:var(--image);}.arisu-workbench .kind.video{background:var(--video);}
.arisu-workbench .kind.audio{background:var(--audio);}.arisu-workbench .filename{font-size:11px;color:var(--label);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.arisu-workbench .reference input{font-size:11px;padding:4px 6px;}.arisu-workbench .requirements textarea{min-height:130px;}
.arisu-workbench .final{display:flex;flex-direction:column;min-height:300px;gap:4px;min-width:0;}
.arisu-workbench .final textarea{flex:1;min-height:280px;font:13px/1.7 Arial,system-ui,sans-serif;resize:none;padding:12px;}
.arisu-workbench .actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;}
.arisu-workbench button{font:inherit;color:var(--text);border:1px solid var(--line);border-radius:5px;
 background:var(--surface);padding:8px 12px;min-height:34px;cursor:pointer;transition:background-color 140ms ease,transform 100ms ease;}
.arisu-workbench button:enabled:hover{border-color:var(--accent);}.arisu-workbench button:enabled:active{transform:translateY(1px);}
.arisu-workbench button:disabled{opacity:.5;cursor:default;transform:none;}
.arisu-workbench .status-row{font-size:11px;color:var(--label);min-height:16px;overflow-wrap:anywhere;}
.arisu-workbench .status{font-size:11px;color:var(--label);min-height:16px;overflow-wrap:anywhere;}
.arisu-workbench .hint{font-size:11px;color:var(--label);padding:4px 0;}
.arisu-workbench .review{border-color:var(--accent);}.arisu-workbench .footer{margin-top:auto;padding:8px 4px 2px;border-top:1px solid var(--line);}
@container(max-width:530px){.arisu-workbench .columns{grid-template-columns:1fr;overflow:auto;}.arisu-workbench .generation{overflow:visible;}.arisu-workbench .generation-fields{overflow:visible;flex:none;}
 .arisu-workbench .final{min-height:320px;}.arisu-workbench .final textarea{resize:vertical;}}
@media(pointer:coarse){.arisu-workbench input,.arisu-workbench select,.arisu-workbench button{min-height:44px;}
 .arisu-workbench .reference{grid-template-columns:4px minmax(60px,100px) minmax(0,1fr);}}
@media(prefers-reduced-motion:reduce){.arisu-workbench *{transition:none!important;animation:none!important;}}
`;

function widget(node, name) {
  return node?.widgets?.find((item) => item.name === name);
}
function value(node, name) {
  return widget(node, name)?.value ?? (name === 'motion_enabled' ? true : undefined);
}
function identity() {
  return globalThis.crypto?.randomUUID?.() ?? `${String(Date.now())}-${Math.random().toString(36).slice(2)}`;
}
function linked(node, name) {
  return node.inputs?.some((item) => item.name === name && item.link != null);
}

function notes(node) {
  try {
    const result = JSON.parse(value(node, 'reference_notes') || '{}');
    return result && typeof result === 'object' && !Array.isArray(result) ? result : {};
  } catch {
    return {};
  }
}

function upstreamSignature(node) {
  const seen = new Set();
  function visit(current) {
    if (!current || seen.has(current)) return null;
    seen.add(current);
    return [
      current.id,
      current.type,
      current.mode,
      current.widgets?.filter((item) => !FIELDS.includes(item.name)).map((item) => [item.name, item.value]),
      current.inputs?.map((input) => visit(inputSource(current, input.name))),
    ];
  }
  return visit(node);
}

function sourceSnapshot(node) {
  const owners = effectiveBundles(node);
  const source = owners.resources;
  let resources = [];
  let serialized = '';
  if (source?.type === 'ArisuMiniMaxH3ResourceStudio') {
    serialized = value(source, 'resources_json') ?? '';
    try {
      resources = (JSON.parse(serialized).references ?? []).filter(
        (item) => item && ['image', 'video', 'audio'].includes(item.kind) && !item.muted,
      );
    } catch {
      /* backend reports malformed state */
    }
  }
  const sourceId = source ? `${String(source.graph?.id ?? 'root')}:${source.id}` : '';
  return {
    resources,
    sourceId,
    signature: JSON.stringify([
      sourceId,
      serialized,
      owners.settings?.id,
      owners.settings?.widgets?.map((item) => [item.name, item.value]),
      upstreamSignature(node),
      upstreamSignature(owners.motion),
      upstreamSignature(owners.vae),
    ]),
  };
}

function noteKey(source, item) {
  return `${source}:${item.id}:${item.root}:${item.path}`;
}

// Sessions belong to frontend workflow objects, never serialized workflow IDs or node objects.
const sessions = new Map();
const views = new Set();
let loading = false;
let loadOwner = null;
let sessionTimer;

function workflowOwner() {
  return loading ? loadOwner : (app.extensionManager?.workflow?.activeWorkflow ?? app.rootGraph ?? app.graph);
}

function bindSession(node) {
  const state = nodes.get(node);
  if (!state || loading || !node.graph) return;
  let target;
  try {
    target = executionTarget(node);
  } catch {
    return;
  }
  if (!target) return;
  const owner = workflowOwner();
  let owned = sessions.get(owner);
  if (!owned) {
    owned = new Map();
    sessions.set(owner, owned);
  }
  let run = owned.get(target.id);
  if (!run && state.run?.owner === owner && !state.run.disposed) {
    run = state.run;
    owned.delete(run.key);
    run.key = target.id;
    owned.set(target.id, run);
  }
  if (!run) {
    run = { epoch: 0, workflow: identity(), running: false, draft: '', hasOutput: false, status: '', owner, key: target.id };
    owned.set(target.id, run);
  }
  if (state.run && state.run !== run && state.run.node === node) state.run.node = null;
  state.run = run;
  run.node = node;
  if (!sessionTimer) sessionTimer = setInterval(reapSessions, 1500);
  sessionTimer.unref?.();
}

function updateRun(run) {
  if (run.node && nodes.get(run.node)?.run === run) render(run.node);
  run.activity?.refreshOutput();
}

async function cancelGeneration(run) {
  if (run.cancelling) return;
  run.cancelling = true;
  run.status = 'Cancelling…';
  updateRun(run);
  if (!run.job) return;
  const epoch = run.epoch;
  try {
    await workbenchRequest('/release', { id: run.job });
  } catch (error) {
    if (run.disposed || run.epoch !== epoch || !run.running) return;
    run.cancelling = false;
    run.status = error.message;
    notify('error', error.message);
    updateRun(run);
  }
}

function generationTime(run) {
  if (run.elapsedMs == null) return '';
  const seconds = Math.floor(run.elapsedMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const duration =
    minutes < 60
      ? `${minutes}:${String(seconds % 60).padStart(2, '0')}`
      : `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  return `Agent time ${duration}${run.timingUnavailable ? ' (updates unavailable)' : ''}`;
}

function refreshProgress(run) {
  const state = nodes.get(run.node);
  if (state?.run === run) {
    if (state.statusElement?.textContent !== run.status) state.statusElement.textContent = run.status;
    const time = generationTime(run);
    if (state.timeElement) state.timeElement.textContent = time ? ` · ${time}` : '';
  }
  run.activity?.refreshOutput();
}

function disposeSession(run) {
  run.epoch++;
  run.disposed = true;
  run.running = false;
  run.activity?.close();
  if (run.started) void workbenchRequest('/release', { workflow: run.workflow }).catch(() => {});
  sessions.get(run.owner)?.delete(run.key);
}

function reapSessions() {
  if (loading) return;
  const manager = app.extensionManager?.workflow;
  const open = manager?.openWorkflows;
  for (const [owner, owned] of sessions) {
    if (Array.isArray(open) && owner !== manager.activeWorkflow && !open.includes(owner)) {
      for (const run of owned.values()) disposeSession(run);
    }
    if (!owned.size) sessions.delete(owner);
  }
  if (!sessions.size) {
    clearInterval(sessionTimer);
    sessionTimer = null;
  }
}

globalThis.addEventListener?.('pagehide', () => {
  for (const owned of sessions.values()) for (const run of owned.values()) disposeSession(run);
  reapSessions();
});

observeWorkflowLoads({
  before(_current, target) {
    loading = true;
    loadOwner = target;
    for (const owned of sessions.values()) for (const run of owned.values()) run.activity?.close();
  },
  after(active, succeeded) {
    loading = false;
    // A failed or imported load cannot borrow a previous workflow's runtime state.
    if (!succeeded || !loadOwner) {
      const owned = sessions.get(active);
      if (owned) for (const run of owned.values()) disposeSession(run);
    }
    for (const node of views) {
      bindSession(node);
      render(node);
    }
    const owned = sessions.get(active);
    if (owned) for (const run of owned.values()) if (!run.node || !views.has(run.node)) disposeSession(run);
    loadOwner = null;
    reapSessions();
  },
});

function edit(node, name, next) {
  const target = widget(node, name);
  if (!target || target.value === next) return;
  node.graph?.beforeChange?.();
  try {
    setWidget(node, target, next);
  } finally {
    node.graph?.afterChange?.();
  }
  if (name === 'finalized_prompt') refreshApplied(node);
}

function refreshApplied(node) {
  const state = nodes.get(node);
  const run = state?.run;
  if (!run) return;
  const applied = run.hasOutput && run.draft === value(node, 'finalized_prompt');
  if (state.applyButton) {
    state.applyButton.disabled = applied || !run.draft.trim();
    state.applyButton.textContent = applied ? 'Applied' : 'Apply Output';
  }
  run.activity?.refreshOutput();
}

function notify(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Prompt Workbench', detail, life: 8000 });
}

function applyOutput(node) {
  const run = nodes.get(node)?.run;
  if (!run?.draft?.trim()) return;
  edit(node, 'finalized_prompt', run.draft);
  run.status = 'Output applied';
  updateRun(run);
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function generate(node) {
  bindSession(node);
  const run = nodes.get(node)?.run;
  if (!run || run.running) return;
  run.epoch++;
  run.draft = '';
  run.hasOutput = false;
  run.activityJob = null;
  run.activity?.close();
  run.running = true;
  run.cancelling = false;
  run.elapsedMs = null;
  run.timingUnavailable = false;
  run.status = 'Preparing workflow…';
  const epoch = run.epoch;
  const current = () => !run.disposed && run.epoch === epoch;
  let terminal = false;
  try {
    // Capture everything in one synchronous turn. Edits after this point belong to the next Generate.
    const snapshot = sourceSnapshot(node);
    const prompt = captureWorkbenchPrompt(node);
    const options = Object.fromEntries(
      ['agent', 'skill', 'context_length', 'audio_context_length', 'motion_notes', 'trigger_words', 'requirements', 'motion_enabled'].map(
        (name) => [name, value(node, name)],
      ),
    );
    options.reference_notes = notes(node);
    options.source_id = snapshot.sourceId;
    run.started = true;
    updateRun(run);
    const response = await workbenchRequest('/generate', {
      prompt: prompt.output,
      node_id: prompt.nodeId,
      workflow: run.workflow,
      client_id: api.clientId,
      options,
    });
    if (!current()) {
      void workbenchRequest('/release', { id: response.id }).catch(() => {});
      return;
    }
    run.job = response.id;
    run.activityJob = response.id;
    if (run.cancelling) {
      run.cancelling = false;
      await cancelGeneration(run);
    }
    while (current()) {
      const response = await api.fetchApi(`/arisu/workbench/jobs/${run.job}`);
      if (!response.ok) throw new Error('Generation job is unavailable.');
      const job = await response.json();
      if (!current()) return;
      if (Number.isFinite(job.generation_elapsed_ms) && job.generation_elapsed_ms >= 0) run.elapsedMs = job.generation_elapsed_ms;
      terminal = ['complete', 'failed', 'cancelled'].includes(job.state);
      run.status =
        run.cancelling && !terminal
          ? 'Cancelling…'
          : ({
              preparing: 'Loading motion context…',
              preparing_media: 'Preparing selected references…',
              generating: 'Generating prompt…',
              complete: 'Output ready to apply',
              cancelled: 'Generation cancelled',
            }[job.state] ?? job.state);
      if (job.state === 'complete') {
        run.draft = job.draft;
        run.hasOutput = true;
        notify('success', 'Prompt ready. Open Generation results to review it, or choose Apply output.');
        break;
      }
      if (job.state === 'cancelled') break;
      if (job.state === 'failed') throw new Error(job.error || run.status);
      refreshProgress(run);
      await wait(750);
    }
  } catch (error) {
    if (current()) {
      run.timingUnavailable = !terminal;
      run.status = error.message;
      notify('error', error.message);
    }
  } finally {
    if (current()) {
      run.running = false;
      run.job = null;
      updateRun(run);
    }
  }
}

function render(node) {
  const state = nodes.get(node);
  if (!state) return;
  const run = state.run ?? { running: false, draft: '', status: '' };
  const applied = run.hasOutput && run.draft === value(node, 'finalized_prompt');
  const source = sourceSnapshot(node);
  const provider = state.agents?.agents?.[value(node, 'agent')];
  const ready = state.agents?.docker && provider?.ready;
  function textField(name, label, multiline = false, placeholder = '') {
    const input = el(multiline ? 'textarea' : 'input', {
      value: value(node, name) ?? '',
      placeholder,
      ariaLabel: label,
      oninput: () => edit(node, name, input.value),
      onwheel: keepScrollWheel,
    });
    return el('label', { className: `field ${name}` }, [el('span', { className: 'label', textContent: label }), input]);
  }
  function combo(name, choices, label) {
    const control = el(
      'select',
      { ariaLabel: label },
      choices.map((item) => el('option', { value: item.value ?? item, textContent: item.label ?? item })),
    );
    control.value = String(value(node, name));
    control.onchange = () => {
      edit(node, name, control.value);
      render(node);
      state.body.querySelector?.(`[aria-label="${label}"]`)?.focus();
    };
    return control;
  }
  const skills = state.agents?.skills?.map((item) => ({
    value: item.id,
    label: item.name + (item.source === 'custom' ? ' · custom' : ''),
  })) ?? [{ value: 'bundled:with-ref', label: 'with-ref' }];
  const audio = el('input', {
    type: 'number',
    min: '0',
    max: '240',
    step: '1',
    value: String(value(node, 'audio_context_length')),
    ariaLabel: 'Audio Context Length in Frames',
  });
  audio.onchange = () => {
    edit(node, 'audio_context_length', Math.max(0, Math.min(240, Math.round(Number(audio.value) || 0))));
  };
  const motion = el(
    'fieldset',
    { className: 'motion', disabled: !value(node, 'motion_enabled') || !linked(node, 'context_latent') || !linked(node, 'vae') },
    [
      el('label', {}, [
        el('span', { textContent: 'Video Frames' }),
        combo('context_length', ['22', '5', '39', '56'], 'Context Length in Frames'),
      ]),
      el('label', {}, [el('span', { textContent: 'Audio Frames' }), audio]),
      el('div', { className: 'hint', textContent: 'Frames at 24 fps · audio 0 follows video' }),
      textField('motion_notes', 'Notes', true, 'Notes on motion continuity…'),
    ],
  );
  const motionToggle = el('input', {
    type: 'checkbox',
    className: 'motion-toggle',
    checked: value(node, 'motion_enabled'),
    disabled: !linked(node, 'context_latent') || !linked(node, 'vae'),
    ariaLabel: 'Enable motion context',
    title: 'Enable motion context',
    onclick: (event) => event.stopPropagation(),
    onkeydown: (event) => event.stopPropagation(),
  });
  motionToggle.onchange = () => {
    edit(node, 'motion_enabled', motionToggle.checked);
    motion.disabled = !motionToggle.checked || !linked(node, 'context_latent') || !linked(node, 'vae');
  };
  const savedNotes = notes(node);
  const rows = source.resources.map((item) => {
    const key = noteKey(source.sourceId, item);
    const name = item.path?.split(/[\\/]/).at(-1) ?? item.id;
    const input = el('input', { value: savedNotes[key] ?? '', placeholder: 'Comment…', ariaLabel: `Notes for ${name}` });
    input.oninput = () => edit(node, 'reference_notes', JSON.stringify({ ...notes(node), [key]: input.value }));
    return el('div', { className: 'reference' }, [
      el('span', { className: `kind ${item.kind}`, ariaLabel: item.kind }),
      el('span', { className: 'filename', textContent: name, title: name }),
      input,
    ]);
  });
  const references = el('div', { className: 'field' }, [
    el('span', { className: 'label', textContent: 'Reference Notes' }),
    el(
      'div',
      { className: 'references', onwheel: keepScrollWheel },
      rows.length ? rows : [el('span', { className: 'hint', textContent: 'Connect or advertise Resource Studio references.' })],
    ),
  ]);
  const generateButton = el('button', {
    textContent: 'Generate Prompt',
    className: 'primary',
    disabled: !ready || run.running,
    onclick: () => void generate(node),
  });
  state.generateButton = generateButton;
  const activityButton = el('button', {
    textContent: 'Generation Results',
    title: 'View agent activity and the latest output prompt',
    onclick: () => {
      if (run.activity) return;
      run.activity = openAgentActivity(
        () => ({
          job: run.activityJob,
          running: run.running,
          message: run.status,
          generationTime: generationTime(run),
          draft: run.draft,
          hasOutput: run.hasOutput,
          applied: run.hasOutput && run.draft === value(run.node, 'finalized_prompt'),
        }),
        () => {
          run.activity = null;
          state.activityButton?.focus();
        },
        (draft) => {
          run.draft = draft;
          render(node);
        },
        () => {
          if (run.node) applyOutput(run.node);
        },
      );
    },
  });
  state.activityButton = activityButton;
  const actions = [activityButton, generateButton];
  if (!ready && state.agents?.docker)
    actions.unshift(el('button', { textContent: 'Setup', onclick: () => openAgentSettings(value(node, 'agent')) }));
  if (run.running)
    actions.unshift(
      el('button', {
        textContent: run.cancelling ? 'Cancelling…' : 'Cancel',
        disabled: run.cancelling,
        onclick: () => {
          void cancelGeneration(run);
          render(node);
        },
      }),
    );
  state.applyButton = null;
  if (run.draft) {
    state.applyButton = el('button', {
      textContent: applied ? 'Applied' : 'Apply Output',
      className: 'review',
      disabled: applied || !run.draft.trim(),
      onclick: () => applyOutput(node),
    });
    actions.unshift(state.applyButton);
  }
  const statusElement = el('span', {
    className: `status${run.running ? ' running' : ''}`,
    role: 'status',
    ariaLive: 'polite',
    textContent: run.status || (ready ? 'Ready' : 'Complete agent setup to generate.'),
  });
  state.statusElement = statusElement;
  const time = generationTime(run);
  state.timeElement = el('span', { className: 'generation-time', textContent: time ? ` · ${time}` : '', ariaLive: 'off' });
  const statusRow = el('div', { className: 'status-row' }, [statusElement, state.timeElement]);
  state.motionContext = el(
    'details',
    { className: 'context', open: state.motionContext?.open ?? (linked(node, 'context_latent') && linked(node, 'vae')) },
    [
      el('summary', {}, [
        el('span', { textContent: 'Motion Context' }),
        el('label', { className: 'motion-switch', onclick: (event) => event.stopPropagation() }, [
          el('span', { textContent: 'Enable' }),
          motionToggle,
        ]),
      ]),
      ...(!linked(node, 'context_latent') || !linked(node, 'vae')
        ? [el('div', { className: 'hint', textContent: 'Connect context_latent and vae to use motion context.' })]
        : []),
      motion,
    ],
  );
  const left = el('div', { className: 'generation' }, [
    el('div', { className: 'section-title', textContent: 'Prompt Direction' }),
    el('fieldset', { className: 'generation-fields', disabled: !state.agents?.docker, onwheel: keepScrollWheel }, [
      el('div', { className: 'selectors' }, [
        el('label', { className: 'field' }, [
          el('span', { className: 'label', textContent: 'Agent' }),
          combo(
            'agent',
            [
              { value: 'codex', label: 'Codex' },
              { value: 'grok', label: 'Grok Build' },
            ],
            'Agent',
          ),
        ]),
        el('label', { className: 'field' }, [el('span', { className: 'label', textContent: 'Skill' }), combo('skill', skills, 'Skill')]),
      ]),
      textField('requirements', 'Requirements', true, 'Describe the shot, motion, pacing…'),
      textField('trigger_words', 'LoRA Trigger Words', false, 'e.g. aiko_style, filmgrain'),
      state.motionContext,
      references,
    ]),
    el('div', { className: 'footer' }, [statusRow, el('div', { className: 'actions' }, actions)]),
  ]);
  const final = textField('finalized_prompt', 'Finalized Prompt', true, 'Write a prompt here, or generate a draft to review…');
  final.className = 'final';
  const unavailable = state.agents?.docker
    ? ''
    : state.agents
      ? 'Docker unavailable · finalized prompt remains editable'
      : 'Checking agent availability…';
  if (unavailable) final.append(el('div', { className: 'status', textContent: unavailable }));
  state.body.replaceChildren(el('style', { textContent: STYLE + ACTIVITY_STYLE }), el('div', { className: 'columns' }, [left, final]));
}

async function refresh(node) {
  const state = nodes.get(node);
  if (!state) return;
  bindSession(node);
  refreshApplied(node);
  const snapshot = sourceSnapshot(node);
  if (state.sourceSignature !== snapshot.signature) {
    state.sourceSignature = snapshot.signature;
    render(node);
  }
  try {
    const status = await agentStatus();
    if (nodes.get(node) !== state) return;
    if (JSON.stringify(state.agents) !== JSON.stringify(status)) {
      state.agents = status;
      render(node);
    }
  } catch {
    if (nodes.get(node) === state && !state.agents) {
      state.agents = { docker: false };
      render(node);
    }
  }
}

app.registerExtension({
  name: 'Arisu.MiniMaxH3.PromptWorkbench',
  init: installSelectionGuards,
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== TYPE) return;
    function chain(name, callback) {
      const previous = nodeType.prototype[name];
      nodeType.prototype[name] = function (...args) {
        const result = previous?.apply(this, args);
        callback.apply(this, args);
        return result;
      };
    }
    chain('onNodeCreated', function () {
      const body = el('div', { className: 'arisu-workbench' });
      forwardToCanvas(body);
      const state = { body, sourceSignature: '' };
      nodes.set(this, state);
      views.add(this);
      bindSession(this);
      for (const name of FIELDS) {
        const control = widget(this, name);
        if (control) hideWidget(this, control);
      }
      widget(this, 'prepare_job').value = '';
      const dom = this.addDOMWidget('workbench', 'arisu-workbench', body, { serialize: false, hideOnZoom: false, getMinHeight: () => 560 });
      dom.serialize = false;
      this.setSize([720, 740]);
      this.arisuRefreshSources = () => {
        void refresh(this);
      };
      render(this);
      void refresh(this);
      state.timer = setInterval(() => void refresh(this), 1500);
    });
    chain('onAdded', function () {
      bindSession(this);
    });
    chain('onConfigure', function (info) {
      const size = info?.size ?? this.size;
      const savedSize = size ? [...size] : null;
      const enabled = widget(this, 'motion_enabled');
      if (enabled && Array.isArray(info?.widgets_values) && typeof info.widgets_values[this.widgets.indexOf(enabled)] !== 'boolean') {
        enabled.value = true;
      }
      const state = nodes.get(this);
      if (!state) return;
      bindSession(this);
      for (const name of FIELDS) {
        const control = widget(this, name);
        if (control) hideWidget(this, control);
      }
      if (savedSize) this.setSize(savedSize);
      widget(this, 'prepare_job').value = '';
      state.sourceSignature = '';
      render(this);
      void refresh(this);
    });
    chain('onResize', (size) => {
      size[0] = Math.max(350, size[0]);
      size[1] = Math.max(500, size[1]);
    });
    chain('onConnectionsChange', function () {
      render(this);
      void refresh(this);
    });
    chain('onRemoved', function () {
      const state = nodes.get(this);
      if (!state) return;
      clearInterval(state.timer);
      views.delete(this);
      if (state.run?.node === this) {
        state.run.node = null;
        if (!loading) disposeSession(state.run);
      }
      reapSessions();
      state.body.remove();
      nodes.delete(this);
    });
  },
});
