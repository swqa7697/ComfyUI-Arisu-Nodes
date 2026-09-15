// A compact prompt workbench: generation is explicit and every draft requires Apply.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { forwardToCanvas, keepScrollWheel } from '../common/canvas_gestures.js';
import { closeOnBackdropClick, el } from '../common/dom.js';
import { hideWidget, setWidget } from '../common/widgets.js';
import { ACTIVITY_STYLE, openAgentActivity } from './agent_activity.js';
import { agentStatus, openAgentSettings, workbenchRequest } from './agent_settings.js';
import { effectiveBundles, executionTarget } from './settings_broadcast.js';

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
];

const STYLE = `
.arisu-workbench{width:100%;height:100%;box-sizing:border-box;container-type:inline-size;padding:10px;
 --surface:var(--comfy-input-bg,#222);--panel:var(--comfy-menu-bg,#353535);--line:var(--border-color,#444);
 --text:var(--input-text,#ccc);--label:var(--descrip-text,#aaa);--accent:#64b5f6;--on-accent:#102331;
 --image:#64b5f6;--video:#d9a441;--audio:#b89be0;color:var(--text);font:12px/1.45 Arial,system-ui,sans-serif;}
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
.arisu-workbench .context summary{cursor:pointer;color:var(--label);padding:2px 0 6px;}
.arisu-workbench .context summary:focus-visible{outline-offset:-2px;}
.arisu-workbench .motion{border:1px solid var(--line);margin:0;padding:8px;border-radius:4px;background:color-mix(in srgb,var(--surface) 65%,var(--panel));
 display:flex;flex-direction:column;gap:6px;}.arisu-workbench .motion label{display:grid;grid-template-columns:1fr 90px;gap:8px;align-items:center;}
.arisu-workbench .motion textarea{min-height:64px;}
.arisu-workbench .motion .motion_notes{display:flex;align-items:stretch;}.arisu-workbench .motion_notes>.label{display:none;}
.arisu-workbench .generation-fields{display:flex;flex:1;min-height:0;flex-direction:column;gap:10px;overflow:auto;padding:2px 4px 4px;scrollbar-width:thin;}
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
.arisu-workbench button:hover{border-color:var(--accent);}.arisu-workbench button:active{transform:translateY(1px);}
.arisu-workbench .primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600;}
.arisu-workbench .primary:hover{background:color-mix(in srgb,var(--accent),white 15%);}.arisu-workbench button:disabled{opacity:.5;cursor:default;transform:none;}
.arisu-workbench .status{font-size:11px;color:var(--label);min-height:16px;overflow-wrap:anywhere;}
.arisu-workbench .hint{font-size:11px;color:var(--label);padding:4px 0;}
.arisu-workbench .review{border-color:var(--accent);}.arisu-workbench .footer{margin-top:auto;padding:8px 4px 2px;border-top:1px solid var(--line);}
@container(max-width:530px){.arisu-workbench .columns{grid-template-columns:1fr;overflow:auto;}.arisu-workbench .generation{overflow:visible;}.arisu-workbench .generation-fields{overflow:visible;flex:none;}
 .arisu-workbench .final{min-height:320px;}.arisu-workbench .final textarea{resize:vertical;}}
@media(pointer:coarse){.arisu-workbench input,.arisu-workbench select,.arisu-workbench button{min-height:44px;}
 .arisu-workbench .reference{grid-template-columns:4px minmax(60px,100px) minmax(0,1fr);}}
@media(prefers-reduced-motion:reduce){.arisu-workbench *{transition:none!important;animation:none!important;}}
.arisu-prompt-review{width:min(850px,94vw);max-height:92vh;border:1px solid var(--border-color,#555);border-radius:10px;box-sizing:border-box;box-shadow:0 24px 64px #0009;
 padding:18px;background:var(--comfy-menu-bg,#333);color:var(--fg-color,#ddd);font:14px/1.5 Arial,system-ui,sans-serif;}
.arisu-prompt-review[open]{display:flex;flex-direction:column;gap:12px;overflow:hidden;}
.arisu-prompt-review::backdrop{background:#0009;backdrop-filter:blur(3px);}.arisu-prompt-review h2{font-size:17px;margin:0;}
.arisu-prompt-review textarea{width:100%;height:50vh;min-height:100px;resize:none;scrollbar-width:thin;border-radius:4px;padding:12px;background:var(--comfy-input-bg,#222);
 color:var(--input-text,#ccc);border:1px solid var(--border-color,#555);font:14px/1.7 Arial,system-ui,sans-serif;box-sizing:border-box;}
.arisu-prompt-review footer{display:flex;justify-content:flex-end;gap:10px;padding-top:12px;border-top:1px solid var(--border-color,#444);flex-shrink:0;}
.arisu-prompt-review button{padding:9px 16px;border-radius:5px;cursor:pointer;border:1px solid var(--border-color,#555);
 background:var(--comfy-input-bg,#222);color:inherit;font:inherit;}.arisu-prompt-review .apply{background:#64b5f6;color:#102331;border-color:#64b5f6;}
.arisu-prompt-review :focus-visible{outline:2px solid #64b5f6;outline-offset:2px;}
.arisu-prompt-review textarea:focus{outline:none;border-color:#64b5f6;box-shadow:inset 0 0 0 1px #64b5f6;}
`;

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}
function value(node, name) {
  return widget(node, name)?.value;
}
function identity() {
  return globalThis.crypto?.randomUUID?.() ?? String(Date.now()) + '-' + Math.random().toString(36).slice(2);
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
    const graph = current.graph;
    return [
      current.id,
      current.type,
      current.mode,
      current.widgets?.filter((item) => !FIELDS.includes(item.name)).map((item) => [item.name, item.value]),
      current.inputs?.map((input) => {
        const link = graph?.links?.get?.(input.link) ?? graph?.links?.[input.link];
        return visit(graph?.getNodeById?.(link?.origin_id) ?? graph?.nodes?.find((item) => item.id === link?.origin_id));
      }),
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
  const sourceId = source ? String(source.graph?.id ?? 'root') + ':' + source.id : '';
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
  return source + ':' + item.id + ':' + item.root + ':' + item.path;
}

function invalidate(node) {
  const state = nodes.get(node);
  if (!state) return;
  if (state.running || state.draft) state.status = 'Context changed; generate a new draft.';
  state.epoch++;
  state.review?.close();
  state.review = null;
  state.draft = '';
  state.activity?.close();
  state.activity = null;
  state.activityJob = null;
  if (state.job) void workbenchRequest('/release', { id: state.job }).catch(() => {});
  state.job = null;
  state.running = false;
  if (state.generateButton) state.generateButton.disabled = !state.agents?.agents?.[value(node, 'agent')]?.ready;
}

function edit(node, name, next) {
  const target = widget(node, name);
  if (!target || target.value === next) return;
  if (name !== 'finalized_prompt') invalidate(node);
  node.graph?.beforeChange?.();
  try {
    setWidget(node, target, next);
  } finally {
    node.graph?.afterChange?.();
  }
}

function showDraft(node) {
  const state = nodes.get(node);
  if (!state?.draft || state.review) return;
  const dialog = el('dialog', { className: 'arisu-prompt-review', ariaLabel: 'Review generated prompt' });
  const draft = el('textarea', { value: state.draft, ariaLabel: 'Generated prompt draft', spellcheck: false });
  state.review = dialog;
  dialog.append(
    el('style', { textContent: STYLE }),
    el('h2', { textContent: 'Review generated prompt' }),
    draft,
    el('footer', {}, [
      el('button', {
        textContent: 'Discard',
        onclick: () => {
          state.status = 'Draft discarded';
          state.draft = '';
          dialog.close();
          render(node);
        },
      }),
      el('button', {
        textContent: 'Apply',
        className: 'apply',
        onclick: () => {
          if (sourceSnapshot(node).signature !== state.draftSignature) {
            invalidate(node);
            state.status = 'Context changed; generate a new draft.';
            render(node);
            return;
          }
          edit(node, 'finalized_prompt', draft.value);
          state.status = 'Draft applied';
          state.draft = '';
          dialog.close();
          render(node);
        },
      }),
    ]),
  );
  closeOnBackdropClick(dialog);
  dialog.onclose = () => {
    state.draft = state.draft ? draft.value : '';
    dialog.remove();
    state.review = null;
    state.generateButton?.focus();
  };
  document.body.append(dialog);
  dialog.showModal();
  draft.focus();
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function generate(node) {
  const state = nodes.get(node);
  if (!state || state.running) return;
  invalidate(node);
  state.running = true;
  state.status = 'Preparing workflow…';
  const epoch = state.epoch;
  const sourceSignature = sourceSnapshot(node).signature;
  const current = () => nodes.get(node) === state && state.epoch === epoch && sourceSnapshot(node).signature === sourceSignature;
  render(node);
  try {
    const prompt = await app.graphToPrompt();
    if (!current()) return;
    const target = executionTarget(node);
    if (!target) throw new Error('Unable to resolve this Workbench in the workflow.');
    const nodeId = target.id;
    const snapshot = sourceSnapshot(node);
    const options = Object.fromEntries(
      ['agent', 'skill', 'context_length', 'audio_context_length', 'motion_notes', 'trigger_words', 'requirements'].map((name) => [
        name,
        value(node, name),
      ]),
    );
    options.reference_notes = notes(node);
    options.source_id = snapshot.sourceId;
    const response = await workbenchRequest('/generate', {
      prompt: prompt.output,
      node_id: nodeId,
      workflow: state.workflow,
      client_id: api.clientId,
      options,
    });
    if (!current()) {
      void workbenchRequest('/release', { id: response.id }).catch(() => {});
      return;
    }
    state.job = response.id;
    state.activityJob = response.id;
    while (current()) {
      const response = await api.fetchApi('/arisu/workbench/jobs/' + state.job);
      if (!response.ok) throw new Error('Generation job is unavailable.');
      const job = await response.json();
      if (!current()) return;
      state.status =
        {
          preparing: 'Loading motion context…',
          preparing_media: 'Preparing selected references…',
          generating: 'Generating prompt…',
          complete: 'Draft ready for review',
          cancelled: 'Generation cancelled',
        }[job.state] ?? job.state;
      if (job.state === 'complete') {
        state.draft = job.draft;
        state.draftSignature = sourceSignature;
        break;
      }
      if (job.state === 'failed' || job.state === 'cancelled') throw new Error(job.error || state.status);
      if (state.statusElement) state.statusElement.textContent = state.status;
      await wait(750);
    }
  } catch (error) {
    if (current()) state.status = error.message;
  } finally {
    if (current()) {
      state.running = false;
      state.job = null;
      render(node);
      if (state.draft && !state.activity) showDraft(node);
    }
  }
}

function render(node) {
  const state = nodes.get(node);
  if (!state) return;
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
    return el('label', { className: 'field ' + name }, [el('span', { className: 'label', textContent: label }), input]);
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
      state.body.querySelector?.('[aria-label="' + label + '"]')?.focus();
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
    ariaLabel: 'Audio context length in frames',
  });
  audio.onchange = () => {
    edit(node, 'audio_context_length', Math.max(0, Math.min(240, Math.round(Number(audio.value) || 0))));
  };
  const motion = el('fieldset', { className: 'motion', disabled: !linked(node, 'context_latent') || !linked(node, 'vae') }, [
    el('label', {}, [
      el('span', { textContent: 'Video frames' }),
      combo('context_length', ['22', '5', '39', '56'], 'Context length in frames'),
    ]),
    el('label', {}, [el('span', { textContent: 'Audio frames' }), audio]),
    el('div', { className: 'hint', textContent: 'Frames at 24 fps · audio 0 follows video' }),
    textField('motion_notes', 'Notes', true, 'Notes on motion continuity…'),
  ]);
  const savedNotes = notes(node);
  const rows = source.resources.map((item) => {
    const key = noteKey(source.sourceId, item);
    const name = item.path?.split(/[\\/]/).at(-1) ?? item.id;
    const input = el('input', { value: savedNotes[key] ?? '', placeholder: 'Comment…', ariaLabel: 'Notes for ' + name });
    input.oninput = () => edit(node, 'reference_notes', JSON.stringify({ ...notes(node), [key]: input.value }));
    return el('div', { className: 'reference' }, [
      el('span', { className: 'kind ' + item.kind, ariaLabel: item.kind }),
      el('span', { className: 'filename', textContent: name, title: name }),
      input,
    ]);
  });
  const references = el('div', { className: 'field' }, [
    el('span', { className: 'label', textContent: 'Reference notes' }),
    el(
      'div',
      { className: 'references', onwheel: keepScrollWheel },
      rows.length ? rows : [el('span', { className: 'hint', textContent: 'Connect or advertise Resource Studio references.' })],
    ),
  ]);
  const generateButton = el('button', {
    textContent: 'Generate prompt',
    className: 'primary',
    disabled: !ready || state.running,
    onclick: () => void generate(node),
  });
  state.generateButton = generateButton;
  const activityButton = el('button', {
    textContent: 'Agent activity',
    disabled: !state.running,
    title: 'View live agent progress, reference calls and analysis',
    onclick: () => {
      if (!state.running || state.activity) return;
      state.activity = openAgentActivity(
        () => ({ job: state.activityJob, running: state.running, message: state.status }),
        () => {
          state.activity = null;
          if (state.draft) showDraft(node);
          else state.activityButton?.focus();
        },
      );
    },
  });
  state.activityButton = activityButton;
  const actions = [activityButton, generateButton];
  if (!ready && state.agents?.docker)
    actions.unshift(el('button', { textContent: 'Setup', onclick: () => openAgentSettings(value(node, 'agent')) }));
  if (state.running)
    actions.unshift(
      el('button', {
        textContent: 'Cancel',
        onclick: () => {
          invalidate(node);
          state.status = 'Generation cancelled';
          render(node);
        },
      }),
    );
  if (state.draft) actions.unshift(el('button', { textContent: 'Review draft', className: 'review', onclick: () => showDraft(node) }));
  const statusElement = el('div', {
    className: 'status' + (state.running ? ' running' : ''),
    role: 'status',
    ariaLive: 'polite',
    textContent: state.status || (ready ? 'Ready' : 'Complete agent setup to generate.'),
  });
  state.statusElement = statusElement;
  const left = el('fieldset', { className: 'generation', disabled: !state.agents?.docker }, [
    el('div', { className: 'section-title', textContent: 'Prompt direction' }),
    el('div', { className: 'generation-fields', onwheel: keepScrollWheel }, [
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
      textField('trigger_words', 'LoRA trigger words', false, 'e.g. aiko_style, filmgrain'),
      el('details', { className: 'context', open: linked(node, 'context_latent') && linked(node, 'vae') }, [
        el('summary', { textContent: 'Motion context' }),
        ...(!linked(node, 'context_latent') || !linked(node, 'vae')
          ? [el('div', { className: 'hint', textContent: 'Connect context_latent and vae to use motion context.' })]
          : []),
        motion,
      ]),
      references,
    ]),
    el('div', { className: 'footer' }, [statusElement, el('div', { className: 'actions' }, actions)]),
  ]);
  const final = textField('finalized_prompt', 'Finalized prompt', true, 'Write a prompt here, or generate a draft to review…');
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
  const snapshot = sourceSnapshot(node);
  if (state.sourceSignature !== snapshot.signature) {
    if (state.sourceSignature) invalidate(node);
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
      const state = { body, epoch: 0, workflow: identity(), status: '', running: false, draft: '', sourceSignature: '' };
      nodes.set(this, state);
      state.hide = () => {
        void workbenchRequest('/release', { workflow: state.workflow }).catch(() => {});
      };
      globalThis.addEventListener?.('pagehide', state.hide);
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
    chain('onConfigure', function () {
      const state = nodes.get(this);
      if (!state) return;
      invalidate(this);
      void workbenchRequest('/release', { workflow: state.workflow }).catch(() => {});
      state.workflow = identity();
      for (const name of FIELDS) {
        const control = widget(this, name);
        if (control) hideWidget(this, control);
      }
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
      invalidate(this);
      render(this);
      void refresh(this);
    });
    chain('onRemoved', function () {
      const state = nodes.get(this);
      if (!state) return;
      invalidate(this);
      clearInterval(state.timer);
      globalThis.removeEventListener?.('pagehide', state.hide);
      void workbenchRequest('/release', { workflow: state.workflow }).catch(() => {});
      state.body.remove();
      nodes.delete(this);
    });
  },
});
