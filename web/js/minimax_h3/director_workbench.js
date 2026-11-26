import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { forwardToCanvas, keepScrollWheel } from '../common/canvas_gestures.js';
import { closeOnBackdropClick, el } from '../common/dom.js';
import { installSelectionGuards, preservingSelections, registerSelectionOwner } from '../common/selection_context.js';
import { moveItem, resourceId } from '../common/shared.js';
import { registerTakeSource } from '../common/take_sources.js';
import { hideWidget, setWidget } from '../common/widgets.js';
import { agentStatus, openAgentSettings } from './agent_settings.js';
import { ASPECTS, clearLocations, readDocument, secondsLabel, stableTags, timeline } from './director_document.js';
import { assetButton, bindingView, browseAssets, libraryView } from './director_media.js';
import {
  installDirectorQueue,
  refreshRenderTakes,
  renderSegments,
  renderStatus,
  renderTake,
  saverCandidates,
  stopRender,
  takeLocation,
  verifiedPredecessor,
} from './director_render.js';
import { applyDraft, openDirectorReview } from './director_review.js';
import { DIRECTOR_STYLE } from './director_style.js';
import { captureWorkbenchPrompt, executionTarget } from './settings_broadcast.js';
import { generationTime, workbenchSessions } from './workbench_sessions.js';

const TYPE = 'ArisuMiniMaxH3DirectorWorkbench';
const nodes = new WeakMap();
const sessions = workbenchSessions(
  nodes,
  render,
  notify,
  { generating: 'Directing the film…', ready: 'Director draft ready to review.' },
  (run, job) => {
    const submitted = run.directorSubmission;
    const draft = JSON.parse(job.draft);
    submitted.boundAssets = new Set(
      (draft.segments ?? [draft.segment]).flatMap((segment) => segment.bindings.map((binding) => binding.asset_id)),
    );
    if (typeof job.director_tail_frames !== 'boolean' || !submitted?.request) return;
    submitted.context = job.director_tail_frames
      ? `Used tail frames from segment ${submitted.previousSegment}.`
      : submitted.previousSegment
        ? 'Used the film plan. Previous tail frames were unavailable.'
        : 'Used the film plan.';
  },
);
const filmWidget = (node) => node.widgets.find((w) => w.name === 'film_json');
const read = (node) => readDocument(filmWidget(node).value);
const selectedAgent = (node) => (node.properties?.directorAgent === 'grok' ? 'grok' : 'codex');
const selected = (doc) => doc.segments.find((segment) => segment.id === doc.selected);
const label = (textContent) => el('span', { textContent });
const row = (children) => el('div', { className: 'actions' }, children);
const text = (tag, textContent, className = '') => el(tag, { textContent, className });
const group = (title, children) => el('section', { className: 'stack' }, [text('h3', title), ...children]);
const meta = (value) => text('p', value, 'meta');
const columns = (...children) => el('div', { className: 'columns' }, children);

function notify(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Director Workbench', detail, life: 8000 });
}
function change(node, modify, refresh = true) {
  const doc = read(node);
  modify(doc);
  const value = JSON.stringify(doc);
  const target = filmWidget(node);
  if (value === target.value) return;
  node.graph?.beforeChange?.();
  try {
    setWidget(node, target, value);
  } finally {
    node.graph?.afterChange?.();
  }
  if (refresh) render(node);
}
function controls(node) {
  const state = nodes.get(node);
  const error = (message) => {
    state.message = message;
    notify('error', message);
    render(node);
  };
  function button(textContent, action, disabled = false) {
    return el('button', {
      textContent,
      disabled,
      onclick: async () => {
        try {
          await action();
        } catch (e) {
          if (nodes.has(node)) error(e.message);
        }
      },
    });
  }
  function field(name, value, update, { multiline = false, number = false } = {}) {
    const input = el(multiline ? 'textarea' : 'input', { ariaLabel: name, value: value ?? '' });
    if (multiline) input.onwheel = keepScrollWheel;
    if (number) {
      input.type = 'number';
      input.step = 'any';
      input.onchange = () => update(Number(input.value));
    } else input.oninput = () => update(input.value);
    return el('label', { className: 'field' }, [label(name), input]);
  }
  function select(name, value, choices, update) {
    const input = el(
      'select',
      { ariaLabel: name },
      choices.map(([id, title]) => el('option', { value: id, textContent: title })),
    );
    input.value = value;
    input.onchange = () => update(input.value);
    return el('label', { className: 'field' }, [label(name), input]);
  }
  function check(name, checked, update, disabled = false) {
    const input = el('input', { type: 'checkbox', checked: !!checked, ariaLabel: name, disabled });
    input.onchange = () => update(input.checked);
    return el('label', { className: 'check' }, [input, label(name)]);
  }
  return {
    node,
    state,
    button,
    field,
    select,
    check,
    error,
    read: () => read(node),
    change: (fn, refresh) => change(node, fn, refresh),
    moves: (list, index, move) => [
      button('Move up', () => move(-1), index === 0),
      button('Move down', () => move(1), index === list.length - 1),
    ],
  };
}
const paired = (...items) => el('div', { className: 'paired' }, items);
function skillChoices(state, current) {
  const catalog = state.agents?.writing_skills ?? [
    { id: 'bundled:no-ref', name: 'no-ref' },
    { id: 'bundled:with-ref', name: 'with-ref' },
  ];
  return [
    ['', 'Automatic'],
    ...catalog.map((s) => [s.id, s.name]),
    ...(current && !catalog.some((s) => s.id === current) ? [[current, current + ' (unavailable)']] : []),
  ];
}
function hasInstructions(input, message) {
  input.setCustomValidity(input.value.trim() ? '' : message);
  return input.reportValidity();
}

function filmRequirements(ui, doc) {
  const field = ui.field(
    'Film Requirements',
    doc.film.brief,
    (value) =>
      ui.change((next) => {
        next.film.brief = value;
      }, false),
    { multiline: true },
  );
  field.classList.add('film-requirements');
  const input = field.querySelector('textarea');
  input.rows = 11;
  input.placeholder = 'Describe the film in your own words, or paste a Markdown brief.';
  return field;
}

// Keep the host's unit-bearing text contract, including free-form goals from saved films.
function runtimeMinutes(target) {
  const match = /^(?:about\s+)?(\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*(min(?:ute)?s?|m|s(?:ec(?:ond)?s?)?|h(?:ours?)?)$/i.exec(target.trim());
  if (!match) return '';
  const unit = match[2][0].toLowerCase();
  const minutes = Number(match[1]) * (unit === 's' ? 1 / 60 : unit === 'h' ? 60 : 1);
  return Number.isFinite(minutes) && minutes > 0 ? minutes : '';
}

function filmNumber(name, value, attributes, save) {
  const input = el('input', { type: 'number', step: 'any', inputMode: 'decimal', ariaLabel: name, ...attributes, value });
  const error = meta('');
  error.hidden = true;
  error.setAttribute('role', 'alert');
  input.oninput = () => {
    error.hidden = true;
  };
  let saved = input.value;
  input.onchange = () => {
    if (!input.validity.valid || (input.value && input.valueAsNumber <= 0)) {
      error.textContent = input.validationMessage || 'Enter a positive number.';
      error.hidden = false;
      input.value = saved;
      return;
    }
    saved = input.value;
    save(saved ? input.valueAsNumber : null);
  };
  return el('label', { className: 'field' }, [label(name), input, error]);
}

function generationRange(ui, film) {
  const warning = meta(`Saved range: ${film.min_seconds}–${film.max_seconds} s. Move a slider to use the 5–15 s range.`);
  warning.setAttribute('role', 'status');
  warning.hidden = film.min_seconds >= 5 && film.max_seconds <= 15;
  function slider(name, value) {
    const input = el('input', { type: 'range', min: '5', max: '15', step: '0.1', value, ariaLabel: name });
    const display = label('');
    const show = () => {
      display.textContent = input.value + ' s';
      input.setAttribute('aria-valuetext', display.textContent);
    };
    show();
    return {
      input,
      show,
      field: el('label', { className: 'field range' }, [el('span', { className: 'bar' }, [label(name), display]), input]),
    };
  }
  const low = slider('Minimum Generation', film.min_seconds);
  const high = slider('Maximum Generation', film.max_seconds);
  let lastLow = low.input.valueAsNumber;
  let lastHigh = high.input.valueAsNumber;
  for (const control of [low, high]) {
    control.input.oninput = () => {
      if (control === low) high.input.value = Math.max(lastHigh, low.input.valueAsNumber);
      else low.input.value = Math.min(lastLow, high.input.valueAsNumber);
      low.show();
      high.show();
      warning.hidden = true;
    };
    control.input.onchange = () =>
      ui.change((next) => {
        lastLow = low.input.valueAsNumber;
        lastHigh = high.input.valueAsNumber;
        next.film.min_seconds = lastLow;
        next.film.max_seconds = lastHigh;
      }, false);
  }
  return [paired(low.field, high.field), warning];
}

function filmView(ui, doc) {
  const f = doc.film;
  const update = (key) => (value) =>
    ui.change((next) => {
      next.film[key] = value;
    }, false);
  const minutes = runtimeMinutes(f.target_runtime);
  const legacyTarget =
    f.target_runtime && minutes === ''
      ? row([meta('Saved target: ' + f.target_runtime), ui.button('Clear target', () => saveTarget(null))])
      : null;
  const saveTarget = (value) => {
    update('target_runtime')(value === null ? '' : value + ' min');
    legacyTarget?.remove();
  };
  return [
    columns(
      filmRequirements(ui, doc),
      el('div', { className: 'stack' }, [
        group('Canvas & Timing', [
          paired(
            ui.select(
              'Film Aspect Ratio',
              f.aspect_ratio,
              ASPECTS.map((k) => [k, k]),
              update('aspect_ratio'),
            ),
            filmNumber('Megapixels', f.megapixels, { min: '0.1', max: '16', required: true }, update('megapixels')),
          ),
          ...generationRange(ui, f),
          filmNumber('Target Film Runtime (min, optional)', minutes, { min: '0', placeholder: 'Approximate total length' }, saveTarget),
          ...(legacyTarget ? [legacyTarget] : []),
        ]),
        group('Planning', [
          paired(
            ui.select('Writing Skill for the Film', f.writing_skill, skillChoices(ui.state, f.writing_skill), update('writing_skill')),
            ui.select(
              'Keyframe Picture Tags',
              f.frame_picture_tags,
              [
                ['after_refs', 'After references'],
                ['before_refs', 'Before references'],
                ['none', 'No keyframe tags'],
              ],
              update('frame_picture_tags'),
            ),
          ),
        ]),
      ]),
    ),
    ...(doc.outline
      ? [
          el('details', {}, [
            el('summary', { textContent: 'Applied Plan and Coverage' }),
            el('p', { textContent: doc.outline }),
            el('p', { textContent: doc.continuity }),
            ...Object.entries(doc.coverage).map(([requirement, ids]) => {
              const segments = doc.segments.flatMap((segment, i) => (ids.includes(segment.id) ? [i + 1] : []));
              return el('p', { textContent: requirement + ' — ' + (segments.length ? 'Segment ' + segments.join(', ') : 'Uncovered') });
            }),
          ]),
        ]
      : []),
  ];
}

function confirmClearSegments(ui, parent, trigger) {
  const count = ui.read().segments.length;
  const title = 'Clear all segments?';
  const dialog = el('dialog', { className: 'arisu-director-dialog clear-segments-dialog', ariaLabel: title });
  const message = text(
    'p',
    `Remove ${count} ${count === 1 ? 'segment' : 'segments'} and their prompts from this film. You can undo this change.`,
  );
  const cancel = ui.button('Cancel', () => dialog.close());
  const clear = ui.button('Clear segments', () => dialog.close('clear'));
  clear.className = 'danger';
  dialog.append(
    el('header', { className: 'dialog-head dialog-title' }, [text('h2', title)]),
    el('div', { className: 'dialog-body' }, [message]),
    el('footer', { className: 'dialog-foot actions' }, [cancel, clear]),
  );
  dialog.ariaDescribedByElements = [message];
  closeOnBackdropClick(dialog);
  dialog.onclose = () => {
    dialog.remove();
    if (!parent.open) return;
    if (dialog.returnValue === 'clear') {
      // The dialog closes after the canvas has handled mouseup. Record this edit for both pointer and keyboard confirmation.
      const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
      tracker?.captureCanvasState?.();
      ui.change((doc) => {
        doc.segments = [];
        doc.selected = '';
        for (const ids of Object.values(doc.coverage)) ids.length = 0;
      });
      tracker?.captureCanvasState?.();
      parent.querySelector('textarea')?.focus();
    } else trigger.focus();
  };
  parent.append(dialog);
  dialog.showModal();
  cancel.focus();
}

function addSegment(ui) {
  ui.change((doc) => {
    const id = resourceId();
    doc.segments.push({
      id,
      intent: 'New Segment',
      seconds: doc.film.min_seconds,
      transition: 'cut',
      overlap_frames: 0,
      prompt: '',
      opening: '',
      closing: '',
      bindings: [],
      skill: doc.film.writing_skill || 'bundled:no-ref',
      skill_reason: '',
      skill_locked: false,
    });
    doc.selected = id;
  });
  openEditor(ui, SEGMENT);
}

function directionView(ui, doc, seg) {
  const index = doc.segments.indexOf(seg);
  const modify = (fn, refresh = true) =>
    ui.change((next) => {
      const target = next.segments.find((s) => s.id === seg.id);
      if (target) fn(target);
    }, refresh);
  const field = (name, key, opts) =>
    ui.field(
      name,
      seg[key],
      (v) =>
        modify((s) => {
          s[key] = v;
        }, false),
      opts,
    );
  return [
    field('Intent', 'intent'),
    columns(
      group('Timing & Transition', [
        paired(
          field('Generation Length (s)', 'seconds', { number: true }),
          ui.select(
            'Transition',
            seg.transition,
            [
              ['cut', 'Hard cut'],
              ['continuation', 'Continuation'],
            ],
            (v) =>
              modify((s) => {
                s.transition = v;
                s.overlap_frames = v === 'cut' ? 0 : 22;
              }),
          ),
        ),
        ...(seg.transition === 'continuation'
          ? [
              ui.select(
                'Overlap (frames)',
                String(seg.overlap_frames),
                [5, 22, 39, 56].map((n) => [String(n), String(n)]),
                (v) =>
                  modify((s) => {
                    s.overlap_frames = Number(v);
                  }),
              ),
              meta(
                index
                  ? 'The previous take carries into this shot. Its overlap is trimmed from picture and sound.'
                  : 'The first segment has no preceding take; no overlap is trimmed.',
              ),
            ]
          : [meta('Start a new shot without carrying motion from the previous segment.')]),
      ]),
      group('Continuity', [field('Opening State', 'opening', { multiline: true }), field('Closing State', 'closing', { multiline: true })]),
    ),
    group('Sequence Order', [
      row([
        ...ui.moves(doc.segments, index, (delta) => ui.change((next) => moveItem(next.segments, index, delta))),
        ui.button('Remove segment', () => {
          ui.state.dialog.close();
          ui.change((next) => {
            next.segments.splice(index, 1);
            next.selected = next.segments[Math.min(index, next.segments.length - 1)]?.id ?? '';
            for (const ids of Object.values(next.coverage))
              if (Array.isArray(ids)) {
                const i = ids.indexOf(seg.id);
                if (i >= 0) ids.splice(i, 1);
              }
          });
        }),
      ]),
    ]),
  ];
}

function bindingsView(ui, doc, seg) {
  const modify = (fn) => ui.change((next) => fn(next.segments.find((s) => s.id === seg.id)));
  return [
    columns(
      group('Asset Bindings', [meta('Only these assets are sent to Hybrid for this segment.'), bindingView(ui, doc, seg)]),
      group('Writing Skill', [
        ui.select('Segment Writing Skill', seg.skill, skillChoices(ui.state, seg.skill), (v) =>
          modify((s) => {
            s.skill = v;
            s.skill_locked = !!v;
            s.skill_reason = v ? 'Selected manually.' : '';
          }),
        ),
        ui.check(
          'Lock this writing skill',
          seg.skill_locked,
          (v) =>
            modify((s) => {
              s.skill_locked = v;
            }),
          !seg.skill,
        ),
        ...(seg.skill_reason ? [meta(seg.skill_reason)] : []),
      ]),
    ),
  ];
}

function promptView(ui, doc, seg) {
  const prompt = ui.field(
    'Finalized Prompt',
    seg.prompt,
    (v) =>
      ui.change((next) => {
        next.segments.find((s) => s.id === seg.id).prompt = stableTags(doc, seg, v);
      }, false),
    { multiline: true },
  );
  prompt.classList.add('prompt');
  return [
    meta('This is the text sent to Hybrid. Edit it directly, or use Revise Prompt to prepare a draft for review.'),
    prompt,
    ...footageView(ui.node, seg),
  ];
}

// Capture the preparation graph before file verification yields to other graph edits.
async function revisionMotion(node, doc, index) {
  if (index <= 0 || doc.segments[index].transition !== 'continuation' || !renderTake(node, doc.segments[index - 1].id)) return null;
  try {
    const prompt = captureWorkbenchPrompt(node);
    const inputs = prompt.output[prompt.nodeId].inputs;
    const loader = prompt.output[inputs.context_latent?.[0]];
    if (loader?.class_type !== 'MiniMaxH3MotionContextLoadLatent' || prompt.output[inputs.vae?.[0]]?.class_type !== 'VAELoader')
      return null;
    const path = await verifiedPredecessor(node, doc, doc.segments[index].id);
    Object.assign(loader.inputs, { latent_path: path, clip_index: 1, folder: 'output', stock_format: false });
    return prompt;
  } catch {
    // A missing receipt or unusable preparation graph still allows a storyboard revision.
    return null;
  }
}

function revisionView(ui, doc, seg) {
  const index = doc.segments.indexOf(seg);
  const requests = ui.state.revisions;
  const draft = requests.get(seg.id) ?? {};
  const update = (key, value) => requests.set(seg.id, { ...requests.get(seg.id), [key]: value });
  const request = ui.field(`What should change in segment ${index + 1}?`, draft.request, (v) => update('request', v), {
    multiline: true,
  });
  request.classList.add('revision-request');
  const context = meta('Using the film plan.');
  context.setAttribute('role', 'status');
  if (index > 0 && seg.transition === 'continuation') {
    context.textContent = 'Checking previous tail frames…';
    void revisionMotion(ui.node, doc, index).then((prompt) => {
      context.textContent = prompt
        ? `Tail frames from segment ${index} are available for this revision.`
        : 'Using the film plan. Previous tail frames are unavailable.';
    });
  }
  return [
    group('Current Prompt', [text('p', seg.prompt || 'No finalized prompt yet.', 'current-prompt')]),
    request,
    context,
    ui.check('Reselect writing skill', !seg.skill_locked && draft.reselect, (v) => update('reselect', v), seg.skill_locked),
  ];
}
async function startRender(ui, remaining) {
  ui.state.rendering = true;
  render(ui.node);
  try {
    await renderSegments(ui.node, ui.read(), remaining, (message) => {
      ui.state.message = message;
      render(ui.node);
    });
  } finally {
    ui.state.rendering = false;
    render(ui.node);
  }
}

async function generate(ui, task) {
  const { state, node } = ui;
  const doc = read(node);
  const index = doc.segments.findIndex((seg) => seg.id === doc.selected);
  const refine = task === 'refine';
  const draft = refine ? state.revisions.get(doc.selected) : null;
  let submittedRun;
  await sessions.generate(node, async (_, run) => {
    submittedRun = run;
    const previousSegment = index > 0 && doc.segments[index].transition === 'continuation' ? index : null;
    const submitted = refine ? { request: draft.request, previousSegment } : { brief: doc.film.brief };
    submitted.assets = new Map(doc.assets.map((asset) => [asset.id, asset]));
    run.directorSubmission = submitted;
    state.message = '';
    const target = executionTarget(node);
    if (!target) throw new Error('The Director is absent from this workflow.');
    const agent = selectedAgent(node);
    const motion = refine && (await revisionMotion(node, doc, index));
    const prompt = motion || { nodeId: target.id, output: { [target.id]: { class_type: TYPE, inputs: {} } } };
    prompt.output[prompt.nodeId].inputs.film_json = JSON.stringify(doc);
    if (refine) submitted.context = motion ? `Requested tail frames from segment ${index}.` : 'Using the film plan.';
    return {
      node_id: prompt.nodeId,
      prompt: prompt.output,
      director: { task, request: draft?.request ?? '', reselect_skill: !!draft?.reselect && !doc.segments[index]?.skill_locked },
      options: {
        agent,
        skill: 'bundled:sequence-director',
        motion_enabled: !!motion,
        context_length: String(doc.segments[index]?.overlap_frames || 22),
      },
    };
  });
  // Keep failed requests for a retry, and preserve edits made while the submitted revision was running.
  if (draft && submittedRun?.hasOutput && state.revisions.get(doc.selected) === draft) {
    state.revisions.delete(doc.selected);
    if (nodes.get(node) === state) render(node);
  }
}
function review(ui) {
  const run = ui.state.run;
  if (!run) return;
  openDirectorReview(
    run,
    () => read(run.node ?? ui.node),
    () => {
      if (!run.node) return;
      try {
        const draft = JSON.parse(run.draft);
        change(run.node, (doc) => applyDraft(doc, draft, run.directorSubmission.assets));
        if (draft.segments) nodes.get(run.node)?.revisions.clear();
        run.status = 'Draft applied';
        sessions.updateRun(run);
      } catch (e) {
        ui.error(e.message);
      }
    },
  );
}

function action(ui, name, fn, disabled = false) {
  const button = ui.button(name, fn, disabled);
  button.className = 'primary';
  return button;
}

const FILM = 'Film Setup',
  LIBRARY = 'Asset Library',
  SEGMENT = 'Edit Segment',
  PROMPT = 'Prompt',
  DIRECTION = 'Direction',
  BINDINGS = 'Assets & Skill',
  REVISION = 'Revise Prompt';

function launcher(ui, title) {
  const button = ui.button(title, () => openEditor(ui, title));
  button.dataset.editor = title;
  button.setAttribute('aria-haspopup', 'dialog');
  return button;
}

// A render can follow a select change, a graph edit, or an asynchronous status update.
// Keep the active control, caret and scroll when its part of the form still exists.
function retainFocus(root) {
  const active = document.activeElement;
  if (!root.contains(active)) return () => {};
  const asset = active.closest('[data-asset]')?.dataset.asset;
  const key = (control) => control.dataset.focus ?? control.ariaLabel ?? control.textContent;
  const selector = 'button,input,textarea,select,summary';
  const matches = () =>
    Array.from(root.querySelectorAll(selector)).filter(
      (control) =>
        control.tagName === active.tagName && key(control) === key(active) && control.closest('[data-asset]')?.dataset.asset === asset,
    );
  const index = matches().indexOf(active);
  const start = active.selectionStart,
    end = active.selectionEnd;
  return () => {
    const next = matches()[index];
    next?.focus({ preventScroll: true });
    if (start != null && next?.setSelectionRange) next.setSelectionRange(start, end);
  };
}

function openEditor(ui, title) {
  const { state, node } = ui;
  if (state.dialog?.open) return;
  const segmentEditor = title === SEGMENT;
  let tab = PROMPT;
  const dialog = el('dialog', { className: 'arisu-director-dialog', ariaLabel: title });
  dialog.classList.toggle('segment-dialog', segmentEditor);
  dialog.classList.toggle('compact', title === LIBRARY);
  const close = ui.button('×', () => dialog.close());
  close.title = close.ariaLabel = 'Close';
  close.className = 'dialog-close';
  const body = el('div', { className: 'dialog-body stack' });
  const foot = el('div', { className: 'dialog-foot bar' });
  const heading = text('h2', title);
  const context = text('small', '');
  const browse = title === LIBRARY ? assetButton(ui, 'Browse assets', 'plus', () => browseAssets(ui)) : null;
  const clearSegments = title === FILM ? ui.button('Clear all segments', () => confirmClearSegments(ui, dialog, clearSegments)) : null;
  clearSegments?.setAttribute('aria-haspopup', 'dialog');
  const headActions = row(browse ? [browse, close] : [close]);
  const head = el('header', { className: 'dialog-head bar' }, [el('div', { className: 'dialog-title' }, [heading, context]), headActions]);
  const segmentId = ui.read().selected;
  const tabs = el('div', { className: 'editor-tabs', role: 'tablist', ariaLabel: 'Segment sections' });
  const tabButtons = [PROMPT, DIRECTION, BINDINGS, REVISION].map((name, index) => {
    const button = ui.button(name, () => {
      tab = name;
      body.scrollTop = 0;
      state.refreshEditor(ui.read());
    });
    button.setAttribute('role', 'tab');
    button.id = `director-tab-${segmentId}-${index}`;
    button.setAttribute('aria-controls', `director-panel-${segmentId}`);
    button.onkeydown = (event) => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % 4;
      if (event.key === 'ArrowLeft') next = (index + 3) % 4;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = 3;
      if (next == null) return;
      event.preventDefault();
      tabButtons[next].click();
      tabButtons[next].focus();
    };
    return button;
  });
  if (segmentEditor) {
    tabs.append(...tabButtons);
    body.id = `director-panel-${segmentId}`;
    body.setAttribute('role', 'tabpanel');
  }
  dialog.append(head, ...(segmentEditor ? [tabs] : []), body, foot);
  closeOnBackdropClick(dialog);
  dialog.addEventListener('keydown', (event) => event.stopPropagation());
  state.dialog = dialog;
  state.refreshEditor = (doc) => {
    const seg = selected(doc);
    if (segmentEditor && (!seg || seg.id !== segmentId)) {
      dialog.close();
      return;
    }
    const restore = retainFocus(dialog);
    if (segmentEditor) {
      const index = doc.segments.indexOf(seg),
        time = timeline(doc)[index];
      heading.textContent = `Segment ${String(index + 1).padStart(2, '0')} · ${seg.intent || 'Untitled Segment'}`;
      context.textContent = `${secondsLabel(time.start)} – ${secondsLabel(time.end)} · ${secondsLabel(time.frames ?? 0)} generated · ${seg.transition === 'continuation' ? 'Continuation' : 'Hard cut'}`;
      for (const button of tabButtons) {
        const active = button.textContent === tab;
        button.setAttribute('aria-selected', String(active));
        button.tabIndex = active ? 0 : -1;
        if (active) body.setAttribute('aria-labelledby', button.id);
      }
    }
    if (title === LIBRARY) {
      context.textContent = doc.assets.length + (doc.assets.length === 1 ? ' asset' : ' assets');
      browse.disabled = doc.assets.length >= 256;
    }
    const top = body.scrollTop;
    const planOpen = body.querySelector('details')?.open;
    if (title === FILM) body.replaceChildren(...filmView(ui, doc));
    if (title === LIBRARY) body.replaceChildren(...libraryView(ui, doc));
    if (segmentEditor) {
      const view = { [PROMPT]: promptView, [DIRECTION]: directionView, [BINDINGS]: bindingsView, [REVISION]: revisionView }[tab];
      body.replaceChildren(...view(ui, doc, seg));
    }
    const planning = title === FILM;
    if (planning || (segmentEditor && tab === REVISION)) {
      const provider = state.agents?.agents?.[selectedAgent(node)];
      if (clearSegments) clearSegments.disabled = !doc.segments.length || !!state.rendering;
      foot.replaceChildren(
        row([
          ui.select(
            'Agent',
            selectedAgent(node),
            [
              ['codex', 'Codex'],
              ['grok', 'Grok'],
            ],
            (v) => {
              node.graph?.beforeChange?.();
              node.graph?.canvasAction?.((canvas) => canvas.emitBeforeChange?.());
              try {
                node.properties ??= {};
                node.properties.directorAgent = v;
              } finally {
                node.graph?.afterChange?.();
                node.graph?.canvasAction?.((canvas) => canvas.emitAfterChange?.());
              }
              render(node);
            },
          ),
          ui.button('Agent settings', () => openAgentSettings(selectedAgent(node))),
          ...(!provider?.ready
            ? [provider?.update_required ? text('p', provider.error, 'update-required') : meta('Agent unavailable')]
            : []),
        ]),
        row([
          ...(clearSegments ? [clearSegments] : []),
          action(
            ui,
            planning ? (doc.segments.length ? 'Replan the film' : 'Plan the film') : 'Refine current segment',
            () => {
              const message = planning ? 'Enter the film requirements.' : 'Enter a revision request for this segment.';
              if (!hasInstructions(body.querySelector('textarea'), message)) return;
              dialog.close();
              return generate(ui, planning ? 'plan' : 'refine');
            },
            !provider?.ready || state.run?.running,
          ),
        ]),
      );
    } else if (segmentEditor)
      foot.replaceChildren(
        meta('Edits are saved as you work.'),
        ui.button('Done', () => dialog.close()),
      );
    else foot.replaceChildren();
    foot.hidden = !planning && !segmentEditor;
    if (planOpen && body.querySelector('details')) body.querySelector('details').open = true;
    body.scrollTop = top;
    restore();
  };
  dialog.onclose = () => {
    dialog.remove();
    if (state.dialog !== dialog) return;
    state.dialog = null;
    state.refreshEditor = null;
    if (nodes.get(node) !== state) return;
    render(node);
    const opener =
      (segmentEditor
        ? Array.from(state.body.querySelectorAll('[data-focus]')).find((button) => button.dataset.focus === segmentId)
        : null) ??
      state.body.querySelector(`[data-editor="${title}"]`) ??
      state.body.querySelector('.timeline-head button');
    opener?.focus({ preventScroll: true });
  };
  state.refreshEditor(ui.read());
  document.body.append(dialog);
  dialog.showModal();
  ((browse && !browse.disabled ? browse : body.querySelector('input,textarea,button:enabled,select')) ?? close).focus({
    preventScroll: true,
  });
}

function sequenceView(ui, doc, times) {
  const list = el('div', { className: 'list' });
  for (const [i, seg] of doc.segments.entries()) {
    const t = times[i];
    const status = t.outside ? 'Adjust length' : renderStatus(ui.node, seg.id, doc);
    const button = ui.button('', () => {
      ui.change((next) => {
        next.selected = seg.id;
      });
      openEditor(ui, SEGMENT);
    });
    button.ariaPressed = String(seg.id === doc.selected);
    button.setAttribute('aria-haspopup', 'dialog');
    button.dataset.focus = seg.id;
    button.title = seg.intent;
    button.append(
      text('span', String(i + 1).padStart(2, '0'), 'index'),
      text('span', seg.intent || 'Untitled Segment', 'intent'),
      text('small', secondsLabel(t.start) + ' – ' + secondsLabel(t.end), 'card-time'),
      text(
        'small',
        (seg.transition === 'continuation' ? 'Continuation' : 'Hard cut') + ' · ' + seg.bindings.length + ' assets',
        'card-detail',
      ),
      el('span', { className: 'card-bottom' }, [text('small', status), text('span', 'Edit →', 'card-edit')]),
    );
    list.append(button);
  }
  const add = ui.button('+ Add', () => addSegment(ui), doc.segments.length >= 128);
  add.ariaLabel = 'Add segment';
  return el('section', { className: 'timeline', ariaLabel: 'Sequence', onwheel: keepScrollWheel }, [
    el('div', { className: 'timeline-head bar' }, [text('h3', 'Sequence'), add]),
    ...(doc.segments.length
      ? [list]
      : [
          el('div', { className: 'empty-sequence' }, [
            text('span', '01 —', 'empty-index'),
            text('h2', 'Start with a story'),
            meta('Set the film requirements to plan a sequence, or add a segment to write it yourself.'),
            action(ui, 'Set up the film', () => openEditor(ui, FILM)),
          ]),
        ]),
  ]);
}

function renderControls(ui, doc) {
  const seg = selected(doc);
  if (!seg) return el('div');
  const savers = saverCandidates(ui.node);
  return el('section', { className: 'render-group' }, [
    el('div', { className: 'bar' }, [
      meta(`Selected · Segment ${String(doc.segments.indexOf(seg) + 1).padStart(2, '0')} · ${seg.intent || 'Untitled Segment'}`),
      launcher(ui, SEGMENT),
    ]),
    // Shown only after a render found several savers behind Create Video.
    ...(savers.length
      ? [
          ui.select(
            'Video saver for renders',
            ui.node.properties?.directorSaver ?? '',
            [['', 'Choose a saver'], ...savers.map(({ id, type }) => [id, `${type} #${id}`])],
            (id) => {
              ui.node.properties ??= {};
              ui.node.properties.directorSaver = id;
              ui.node.graph?.change?.();
            },
          ),
        ]
      : []),
    row([
      action(ui, 'Render current segment', () => startRender(ui, false), ui.state.rendering),
      ui.button('Render remaining segments', () => startRender(ui, true), ui.state.rendering),
      ...(ui.state.rendering ? [ui.button('Stop after current', () => stopRender(ui.node))] : []),
    ]),
  ]);
}

function footageView(node, seg) {
  const take = renderTake(node, seg.id);
  if (takeLocation(take))
    return [
      el('details', {}, [
        el('summary', { textContent: 'Rendered Footage' }),
        el('video', {
          controls: true,
          preload: 'none',
          src: api.apiURL(
            '/view?' +
              new URLSearchParams({
                type: 'output',
                subfolder: take.video.subfolder,
                filename: take.video.filename,
              }),
          ),
        }),
      ]),
    ];
  return [];
}

function render(node) {
  const state = nodes.get(node);
  if (!state) return;
  const { body } = state,
    ui = controls(node);
  let doc;
  try {
    doc = read(node);
  } catch (e) {
    state.dialog?.close();
    body.replaceChildren(label(e.message));
    return;
  }
  const times = timeline(doc),
    run = state.run ?? {};
  const restore = retainFocus(body);
  const listTop = body.querySelector('.timeline')?.scrollTop ?? 0;
  const timelinePane = sequenceView(ui, doc, times);
  const status = label(run.status ?? '');
  const elapsed = label(run.elapsedMs != null ? ' · ' + generationTime(run) : '');
  state.statusElement = status;
  state.timeElement = elapsed;
  const summary = [
    String(doc.film.aspect_ratio).split(' ')[0],
    doc.segments.length + (doc.segments.length === 1 ? ' segment' : ' segments'),
    ...(times.length ? [secondsLabel(times.at(-1).end) + ' estimated'] : []),
    ...(doc.film.target_runtime ? ['Target ' + doc.film.target_runtime] : []),
  ];
  const library = launcher(ui, LIBRARY);
  library.ariaLabel = LIBRARY;
  library.append(text('span', String(doc.assets.length), 'count'));
  const provider = state.agents?.agents?.[selectedAgent(node)];
  const message = state.message || ((run.running || run.hasOutput) && run.directorSubmission?.context);
  const feedback = el('div', { className: 'status', role: 'status' }, [
    ...(provider?.update_required
      ? [text('p', provider.error, 'update-required')]
      : !run.status && !state.message
        ? [label((selectedAgent(node) === 'codex' ? 'Codex' : 'Grok') + (provider?.ready ? ' ready' : ' unavailable'))]
        : []),
    status,
    elapsed,
    ...(message ? [label(' ' + message)] : []),
  ]);
  const reviewButton = ui.button('Review Draft', () => review(ui), !run.started && !run.running && !run.hasOutput);
  if (run.hasOutput) reviewButton.className = 'review';
  body.replaceChildren(
    el('header', { className: 'film-head bar' }, [
      el('div', {}, [text('h2', 'Film Overview'), meta(summary.join(' · '))]),
      row([launcher(ui, FILM), library]),
    ]),
    el('div', { className: 'workspace' }, [timelinePane]),
    renderControls(ui, doc),
    el('footer', { className: 'bar' }, [
      feedback,
      row([...(run.running ? [ui.button('Cancel generation', () => sessions.cancelGeneration(run), run.cancelling)] : []), reviewButton]),
    ]),
  );
  timelinePane.scrollTop = listTop;
  if (state.selected !== doc.selected) {
    const active = timelinePane.querySelector('[aria-pressed=true]');
    if (active) {
      const offset = active.offsetTop;
      if (offset < listTop || offset + active.offsetHeight > listTop + timelinePane.clientHeight) timelinePane.scrollTop = offset;
    }
  }
  state.selected = doc.selected;
  restore();
  if (state.dialog?.open) state.refreshEditor(doc);
}
async function refresh(node) {
  const state = nodes.get(node);
  if (!state) return;
  try {
    const agents = await agentStatus();
    if (nodes.get(node) === state && JSON.stringify(state.agents) !== JSON.stringify(agents)) {
      state.agents = agents;
      render(node);
    }
  } catch {
    /* Manual editing and rendering remain available. */
  }
}
function invalidate(node) {
  nodes.get(node)?.dialog?.close();
  nodes.get(node)?.revisions.clear();
  nodes.get(node)?.media?.abort();
  stopRender(node, true);
}
registerSelectionOwner(TYPE, { fields: [['film_json', 0, clearLocations]], properties: ['directorRenders'], invalidate });
// Film-order takes for other panels: locations come from saved receipts, statuses from the same checks the cards show.
registerTakeSource(TYPE, (node) => {
  const doc = read(node);
  return {
    label: `Director #${node.id}`,
    segments: doc.segments.map((segment, index) => {
      const take = renderTake(node, segment.id);
      return {
        segment: segment.id,
        label: `${String(index + 1).padStart(2, '0')} · ${segment.intent || 'Untitled Segment'}`,
        transition: segment.transition === 'continuation' ? 'continuation' : 'cut',
        status: renderStatus(node, segment.id, doc),
        take: takeLocation(take)
          ? {
              take: take.id,
              root: 'output',
              path: `${take.video.subfolder}/${take.video.filename}`,
              revision: take.files?.video ?? '',
              predecessor: take.predecessor ?? null,
            }
          : null,
      };
    }),
  };
});
app.registerExtension({
  name: 'Arisu.MiniMaxH3.DirectorWorkbench',
  init: installSelectionGuards,
  setup() {
    document.head.append(el('style', { textContent: DIRECTOR_STYLE }));
    installDirectorQueue(sessions.views);
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== TYPE) return;
    function chain(name, fn) {
      const previous = nodeType.prototype[name];
      nodeType.prototype[name] = function (...args) {
        const result = previous?.apply(this, args);
        fn.apply(this, args);
        return result;
      };
    }
    chain('onNodeCreated', function () {
      const body = el('div', { className: 'arisu-director' });
      forwardToCanvas(body);
      nodes.set(this, { body, message: '', revisions: new Map() });
      sessions.views.add(this);
      sessions.bindSession(this);
      const w = filmWidget(this);
      if (w) hideWidget(this, w);
      const dom = this.addDOMWidget('director', 'arisu-director', body, { serialize: false, hideOnZoom: false, getMinHeight: () => 460 });
      dom.serialize = false;
      this.setSize([720, 640]);
      render(this);
      void refresh(this);
      const timer = setInterval(() => void refresh(this), 3000);
      timer.unref?.();
      nodes.get(this).timer = timer;
    });
    chain('onAdded', function () {
      sessions.bindSession(this);
      render(this);
    });
    chain('onConfigure', function () {
      const state = nodes.get(this);
      if (!state) return;
      invalidate(this);
      const linked = this.inputs?.some((input) => input.name === 'film_json' && input.link != null);
      for (let i = (this.inputs?.length ?? 0) - 1; i >= 0; i--) if (this.inputs[i].name === 'film_json') this.removeInput(i);
      if (linked || !preservingSelections() || !app.configuringGraph) {
        const w = filmWidget(this);
        w.value = clearLocations(w.value);
        if (this.properties) delete this.properties.directorRenders;
        if (linked) notify('warn', 'Film location wire removed. Reselect assets.');
      } else if (this.properties?.directorRenders?.takes?.length) {
        void refreshRenderTakes(this, read(this), () => render(this)).catch((error) => {
          state.message = error.message;
          render(this);
        });
      }
      sessions.bindSession(this);
      render(this);
    });
    chain('onResize', (size) => {
      size[0] = Math.max(400, size[0]);
      size[1] = Math.max(500, size[1]);
    });
    chain('onRemoved', function () {
      invalidate(this);
      const state = nodes.get(this);
      clearInterval(state?.timer);
      sessions.remove(this);
      state?.body.remove();
      nodes.delete(this);
    });
  },
});
