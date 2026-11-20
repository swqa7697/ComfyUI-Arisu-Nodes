import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { forwardToCanvas, keepScrollWheel } from '../common/canvas_gestures.js';
import { el } from '../common/dom.js';
import { installSelectionGuards, preservingSelections, registerSelectionOwner } from '../common/selection_context.js';
import { hideWidget, setWidget } from '../common/widgets.js';
import { agentStatus, openAgentSettings } from './agent_settings.js';
import { ASPECTS, clearLocations, readDocument, secondsLabel, stableTags, timeline, timing } from './director_document.js';
import { bindingView, libraryView, moveItem } from './director_media.js';
import {
  installDirectorQueue,
  refreshRenderTakes,
  renderSegments,
  renderStatus,
  renderTake,
  stopRender,
  verifiedPredecessor,
} from './director_render.js';
import { applyDraft, openDirectorReview } from './director_review.js';
import { resourceId } from './media_selection.js';
import { captureWorkbenchPrompt, executionTarget } from './settings_broadcast.js';
import { generationTime, workbenchSessions } from './workbench_sessions.js';

const TYPE = 'ArisuMiniMaxH3DirectorWorkbench';
const nodes = new WeakMap();
const sessions = workbenchSessions(nodes, render, notify, { generating: 'Directing the film…', ready: 'Director draft ready to review.' });
const filmWidget = (node) => node.widgets.find((w) => w.name === 'film_json');
const read = (node) => readDocument(filmWidget(node).value);
const selected = (doc) => doc.segments.find((segment) => segment.id === doc.selected);
const label = (textContent) => el('span', { textContent });
const row = (children) => el('div', { className: 'actions' }, children);
const STYLE = `
.arisu-director{--surface:var(--comfy-input-bg,#222);--line:var(--border-color,#505050);--accent:var(--arisu-accent,#8ebcff);
 box-sizing:border-box;display:flex;flex-direction:column;gap:8px;padding:10px;width:100%;height:100%;min-width:0;
 background:var(--comfy-menu-bg,#343434);color:var(--input-text,#ddd);font:12px/1.45 Arial,system-ui,sans-serif;}
.arisu-director *{box-sizing:border-box}.arisu-director nav,.arisu-director .actions,.arisu-director .asset-title{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.arisu-director nav{border-bottom:1px solid var(--line);padding-bottom:7px}.arisu-director .scroll{flex:1;min-height:0;overflow:auto;scrollbar-width:thin;padding:2px 4px}
.arisu-director :is(button,input,textarea,select){color:inherit;background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:6px 9px;font:inherit}
.arisu-director button,.arisu-director select,.arisu-director summary{cursor:pointer}.arisu-director :disabled{opacity:.5;cursor:default}
.arisu-director :focus-visible{outline:2px solid var(--accent);outline-offset:1px}.arisu-director button[aria-pressed="true"],.arisu-director .primary{border-color:var(--accent)}
.arisu-director button:enabled:hover{background:color-mix(in srgb,var(--surface) 85%,var(--accent));border-color:var(--accent)}
.arisu-director .field,.arisu-director .card{display:flex;flex-direction:column;gap:4px;margin:0 0 8px}.arisu-director .field>span,.arisu-director small{color:var(--descrip-text,#bbb)}
.arisu-director .field>:is(input,select,textarea){width:100%;min-width:0}.arisu-director textarea{resize:vertical;min-height:64px;line-height:1.5}
.arisu-director .prompt textarea{min-height:116px}.arisu-director .card,.arisu-director details{padding:8px;border:1px solid var(--line);border-radius:5px}
.arisu-director details{margin:8px 0}.arisu-director details[open]>summary{margin-bottom:8px}
.arisu-director .list{display:grid;gap:4px;margin:7px 0 12px}.arisu-director .list button{text-align:left;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px}
.arisu-director .list button span,.arisu-director .status,.arisu-director strong{overflow-wrap:anywhere}.arisu-director footer{border-top:1px solid var(--line);padding-top:6px}
.arisu-director .status{margin-top:4px;min-height:1.4em}.arisu-director .asset-thumb{width:58px;height:43px;object-fit:contain;background:var(--surface)}
.arisu-director .asset-thumb.audio{display:grid;place-items:center}.arisu-director video{display:block;width:100%;max-height:260px}
.arisu-director .paired{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}
`;

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
  function field(name, value, update, { multiline = false, number = false, refresh = false } = {}) {
    const input = el(multiline ? 'textarea' : 'input', { ariaLabel: name, value: value ?? '' });
    if (number) input.type = 'number';
    if (number) input.step = 'any';
    const save = () => update(number ? Number(input.value) : input.value);
    if (number) input.onchange = save;
    else {
      input.oninput = save;
      if (refresh) input.onchange = () => render(node);
    }
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
    return el('label', {}, [input, label(name)]);
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
function filmView(ui, doc) {
  const f = doc.film;
  const update =
    (key, refresh = false) =>
    (v) =>
      ui.change((next) => {
        next.film[key] = v;
      }, refresh);
  return [
    ui.field('Creative brief', f.brief, update('brief'), { multiline: true }),
    ui.field(
      'Required story elements (one per line)',
      f.requirements.join('\n'),
      (v) =>
        update('requirements')(
          v
            .split('\n')
            .map((r) => r.trim())
            .filter(Boolean),
        ),
      { multiline: true },
    ),
    ui.field('Trigger words', f.triggers, update('triggers')),
    ui.field('Character, picture and sound continuity', f.continuity, update('continuity'), { multiline: true }),
    paired(
      ui.select(
        'Film aspect ratio',
        f.aspect_ratio,
        ASPECTS.map((k) => [k, k]),
        update('aspect_ratio', true),
      ),
      ui.field('Megapixels', f.megapixels, update('megapixels', true), { number: true }),
    ),
    paired(
      ui.field('Minimum generation (s)', f.min_seconds, update('min_seconds', true), { number: true }),
      ui.field('Maximum generation (s)', f.max_seconds, update('max_seconds', true), { number: true }),
    ),
    ...(!timing(f, f.min_seconds) ? [label('No valid H3 frame count fits. Adjust the generation range.')] : []),
    ui.field('Target film runtime (optional)', f.target_runtime, update('target_runtime')),
    ui.field(
      'Whole-film revision request',
      ui.state.filmRequest,
      (v) => {
        ui.state.filmRequest = v;
      },
      { multiline: true },
    ),
    paired(
      ui.select('Writing skill for the film', f.writing_skill, skillChoices(ui.state, f.writing_skill), update('writing_skill', true)),
      ui.select(
        'Keyframe picture tags',
        f.frame_picture_tags,
        [
          ['after_refs', 'After references'],
          ['before_refs', 'Before references'],
          ['none', 'No keyframe tags'],
        ],
        update('frame_picture_tags', true),
      ),
    ),
    ...(doc.outline
      ? [
          el('details', {}, [
            el('summary', { textContent: 'Applied plan and coverage' }),
            el('p', { textContent: doc.outline }),
            el('p', { textContent: doc.continuity }),
            ...f.requirements.map((r) =>
              el('p', { textContent: r + ' — ' + ((Array.isArray(doc.coverage[r]) && doc.coverage[r].join(', ')) || 'Uncovered') }),
            ),
          ]),
        ]
      : []),
  ];
}

function addSegment(ui) {
  ui.change((doc) => {
    const id = resourceId();
    doc.segments.push({
      id,
      intent: 'New segment',
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
}

function segmentView(ui, doc) {
  const { node, state } = ui;
  const seg = selected(doc),
    times = timeline(doc);
  const rows = doc.segments.map((s, i) => {
    const t = times[i];
    const b = ui.button('', () =>
      ui.change((next) => {
        next.selected = s.id;
      }),
    );
    b.ariaPressed = String(s === seg);
    b.replaceChildren(
      label(i + 1 + '. ' + s.intent),
      el('small', {
        textContent:
          secondsLabel(t.start) +
          ' – ' +
          secondsLabel(t.end) +
          ' · ' +
          secondsLabel(t.frames ?? 0) +
          ' generated · ' +
          (t.outside ? 'Adjust length' : renderStatus(node, s.id, doc)),
      }),
    );
    return b;
  });
  const children = [
    label(
      'Estimated film ' + secondsLabel(times.at(-1)?.end ?? 0) + (doc.film.target_runtime ? ' · Target ' + doc.film.target_runtime : ''),
    ),
    el('div', { className: 'list' }, rows),
  ];
  if (!seg) return [...children, ui.button('Add segment', () => addSegment(ui))];
  const index = doc.segments.indexOf(seg),
    duration = times[index];
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
        }, !!opts?.number),
      opts,
    );
  const prompt = ui.field(
    'Finalized prompt',
    seg.prompt,
    (v) =>
      modify((s) => {
        s.prompt = stableTags(doc, seg, v);
      }, false),
    { multiline: true },
  );
  prompt.className = 'field prompt';
  children.push(
    prompt,
    row([
      ui.button('Render current segment', () => startRender(ui, false), state.rendering),
      ui.button('Render remaining segments', () => startRender(ui, true), state.rendering),
      ...(state.rendering ? [ui.button('Stop after current', () => stopRender(node))] : []),
    ]),
  );
  const take = renderTake(node, seg.id);
  if (
    take?.video &&
    take.video.type === 'output' &&
    /^arisu_director\/[a-f0-9-]+$/.test(take.video.subfolder) &&
    /^clip_\d+_\.(mp4|mov|webm|mkv)$/.test(take.video.filename)
  )
    children.push(
      el('details', {}, [
        el('summary', { textContent: 'Rendered footage' }),
        el('video', {
          controls: true,
          preload: 'none',
          src: api.apiURL(
            '/view?' + new URLSearchParams({ type: 'output', subfolder: take.video.subfolder, filename: take.video.filename }),
          ),
        }),
      ]),
    );
  children.push(
    el('details', {}, [
      el('summary', { textContent: 'Segment direction · ' + secondsLabel(duration.frames ?? 0) + ' generated' }),
      field('Intent', 'intent', { refresh: true }),
      paired(
        field('Generation length (s)', 'seconds', { number: true }),
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
          ]
        : []),
      field('Opening state', 'opening'),
      field('Closing state', 'closing'),
      ui.select('Segment writing skill', seg.skill, skillChoices(state, seg.skill), (v) =>
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
      el('small', { textContent: seg.skill_reason }),
      row([
        ...ui.moves(doc.segments, index, (delta) => ui.change((next) => moveItem(next.segments, index, delta))),
        ui.button('Add segment', () => addSegment(ui), doc.segments.length >= 128),
        ui.button('Remove segment', () =>
          ui.change((next) => {
            next.segments.splice(index, 1);
            next.selected = next.segments[Math.min(index, next.segments.length - 1)]?.id ?? '';
            for (const ids of Object.values(next.coverage))
              if (Array.isArray(ids)) {
                const i = ids.indexOf(seg.id);
                if (i >= 0) ids.splice(i, 1);
              }
          }),
        ),
      ]),
    ]),
    bindingView(ui, doc, seg),
  );
  children.push(
    ui.field(
      'Revision request',
      state.request,
      (v) => {
        state.request = v;
      },
      { multiline: true },
    ),
    ui.check(
      'Reselect writing skill',
      state.reselect,
      (v) => {
        state.reselect = v;
      },
      seg.skill_locked,
    ),
    ui.select(
      'Actual tail frames',
      state.motion ?? '',
      [
        ['', 'None'],
        ['wired', 'Connected Motion Context'],
        ...(seg.transition === 'continuation' ? [['previous', 'Verified predecessor take']] : []),
      ],
      (v) => {
        state.motion = v;
        render(node);
      },
    ),
  );
  if (state.motion)
    children.push(
      ui.field('Actual visual notes', state.visual, (v) => {
        state.visual = v;
      }),
      ui.field('Actual audio notes', state.audio, (v) => {
        state.audio = v;
      }),
    );
  return children;
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

function generate(ui, task) {
  return sessions.generate(ui.node, (node) => {
    const doc = read(node),
      state = nodes.get(node);
    const motion = task === 'refine' ? state.motion : '';
    const target = executionTarget(node);
    if (!target) throw new Error('The Director is absent from this workflow.');
    const prompt = motion
      ? captureWorkbenchPrompt(node)
      : {
          nodeId: target.id,
          output: { [target.id]: { class_type: TYPE, inputs: {} } },
        };
    const source = prompt.output[prompt.nodeId];
    source.inputs.film_json = JSON.stringify(doc);
    if (motion && (!source.inputs.vae || !source.inputs.context_latent))
      throw new Error('Connect a Motion Context loader and a video VAE.');
    const payload = {
      node_id: prompt.nodeId,
      prompt: prompt.output,
      director: { task, request: (task === 'plan' ? state.filmRequest : state.request) ?? '', reselect_skill: !!state.reselect },
      options: {
        agent: state.agent,
        skill: 'bundled:sequence-director',
        motion_enabled: !!motion,
        motion_notes: state.visual ?? '',
        motion_audio_notes: state.audio ?? '',
        context_length: String(selected(doc)?.overlap_frames || 22),
      },
    };
    if (motion !== 'previous') return payload;
    const loader = prompt.output[source.inputs.context_latent[0]];
    if (loader?.class_type !== 'MiniMaxH3MotionContextLoadLatent') throw new Error('Connect the supported Motion Context loader.');
    return verifiedPredecessor(node, doc, doc.selected).then((path) => {
      Object.assign(loader.inputs, { latent_path: path, clip_index: 1, folder: 'output', stock_format: false });
      return payload;
    });
  });
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
        change(run.node, (doc) => applyDraft(doc, JSON.parse(run.draft)));
        run.status = 'Draft applied';
        sessions.updateRun(run);
      } catch (e) {
        ui.error(e.message);
      }
    },
  );
}

function render(node) {
  const state = nodes.get(node);
  if (!state) return;
  const ui = controls(node);
  let doc;
  try {
    doc = read(node);
  } catch (e) {
    state.body.replaceChildren(label(e.message));
    return;
  }
  const run = state.run ?? {};
  const tabs = ['Segments', 'Film', 'Asset library'].map((view) => {
    const tab = ui.button(view, () => {
      state.view = view;
      state.scroll = null;
      render(node);
    });
    tab.ariaPressed = String(state.view === view);
    return tab;
  });
  const previous = state.scroll;
  const scroll = el(
    'div',
    { className: 'scroll', onwheel: keepScrollWheel },
    state.view === 'Film' ? filmView(ui, doc) : state.view === 'Asset library' ? libraryView(ui, doc) : segmentView(ui, doc),
  );
  const getLabel = (d) => d.querySelector('summary')?.textContent?.split(' · ')[0].split(' (')[0];
  if (previous) {
    const open = new Set(Array.from(previous.querySelectorAll?.('details[open]') ?? [], getLabel));
    for (const detail of scroll.querySelectorAll?.('details') ?? []) detail.open = open.has(getLabel(detail));
  }
  const status = el('span', { role: 'status', textContent: run.status ?? '' });
  const elapsed = el('span', { textContent: run.elapsedMs != null ? ' · ' + generationTime(run) : '' });
  state.statusElement = status;
  state.timeElement = elapsed;
  const unavailable = !state.agents?.agents?.[state.agent]?.ready;
  const buttons = [
    ui.select(
      'Agent',
      state.agent,
      [
        ['codex', 'Codex'],
        ['grok', 'Grok'],
      ],
      (v) => {
        state.agent = v;
        render(node);
      },
    ),
    ui.button('Agent settings', () => openAgentSettings(state.agent)),
    ui.button('Plan the film', () => generate(ui, 'plan'), unavailable || run.running),
    ...(state.view === 'Segments' && selected(doc)
      ? [ui.button('Refine current segment', () => generate(ui, 'refine'), unavailable || run.running)]
      : []),
    ui.button('Review draft', () => review(ui), !run.hasOutput && !run.running && !run.started),
  ];
  if (run.running) buttons.push(ui.button('Cancel generation', () => sessions.cancelGeneration(run), run.cancelling));
  state.scroll = scroll;
  state.body.replaceChildren(
    el('style', { textContent: STYLE }),
    el('nav', {}, tabs),
    scroll,
    el('footer', {}, [
      row(buttons),
      el('div', { className: 'status' }, [status, elapsed, ...(state.message ? [label(' ' + state.message)] : [])]),
    ]),
  );
  if (previous) scroll.scrollTop = previous.scrollTop;
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
  nodes.get(node)?.media?.abort();
  stopRender(node, true);
}
registerSelectionOwner(TYPE, { fields: [['film_json', 0, clearLocations]], properties: ['directorRenders'], invalidate });
app.registerExtension({
  name: 'Arisu.MiniMaxH3.DirectorWorkbench',
  init: installSelectionGuards,
  setup() {
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
      nodes.set(this, { body, agent: 'codex', view: 'Segments', message: '' });
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
