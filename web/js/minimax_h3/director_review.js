// Present the validated Director result alongside the current film, including changes made while preparing it.
import { el } from '../common/dom.js';
import { openAgentActivity } from './agent_activity.js';
import { secondsLabel, timeline, timing } from './director_document.js';
import { generationTime } from './workbench_sessions.js';

export function applyDraft(doc, draft) {
  if (draft.segment) {
    const index = doc.segments.findIndex((item) => item.id === draft.segment.id);
    if (index < 0) throw new Error('This segment was removed. Generate a new draft.');
    doc.segments[index] = draft.segment;
  } else {
    for (const field of ['outline', 'continuity', 'coverage', 'segments']) doc[field] = draft[field];
    if (!doc.segments.some((item) => item.id === doc.selected)) doc.selected = doc.segments[0].id;
  }
}

const section = (label, text) => el('section', {}, [el('strong', { textContent: label }), el('p', { textContent: text })]);

export function openDirectorReview(run, read, apply) {
  if (run.activity) return;
  const element = el('div', { className: 'arisu-film-review' });
  // Shared activity dialog owns focus, Escape, the streamed logs, and the Apply button.
  const style = el('style', {
    textContent: `
    .arisu-film-review{overflow:auto;flex:1;padding:12px 16px;scrollbar-width:thin;min-height:0}
    .arisu-film-review section,.arisu-film-review details{margin:0 0 12px}
    .arisu-film-review details{border:1px solid var(--border-color,#555);border-radius:5px;padding:8px 12px}
    .arisu-film-review p{white-space:pre-wrap;margin:4px 0;overflow-wrap:anywhere}
    .arisu-film-review summary{cursor:pointer;font-weight:600}
  `,
  });
  let last = '';
  const snapshot = () => {
    const doc = read();
    let applied = false;
    if (run.draft) {
      const copy = structuredClone(doc);
      try {
        applyDraft(copy, JSON.parse(run.draft));
        applied = JSON.stringify(copy) === JSON.stringify(doc);
      } catch {
        /* The target may have been deleted after submission. */
      }
    }
    return {
      job: run.activityJob,
      running: run.running,
      message: run.status,
      generationTime: generationTime(run),
      draft: run.draft,
      hasOutput: run.hasOutput,
      applied,
    };
  };
  run.activity = openAgentActivity(
    snapshot,
    () => {
      run.activity = null;
    },
    undefined,
    apply,
    {
      label: 'Review draft',
      hint: 'Apply saves the reviewed changes as one undoable edit.',
      element,
      refresh(state) {
        const doc = read();
        const signature = JSON.stringify([state.draft, doc]);
        if (signature === last) return;
        last = signature;
        if (!state.draft) {
          element.replaceChildren(style, el('p', { textContent: state.running ? 'Waiting for the director…' : 'No draft yet.' }));
          return;
        }
        const data = JSON.parse(state.draft);
        const segments = data.segments ?? [data.segment];
        const children = [];
        if (data.segments) {
          const times = timeline({ ...doc, segments });
          const runtime = secondsLabel(times.at(-1)?.end ?? 0);
          children.push(
            section('Film outline', data.outline),
            section('Continuity', data.continuity),
            section('Estimated runtime', runtime + (doc.film.target_runtime ? ' · Target ' + doc.film.target_runtime : '')),
          );
          for (const [req, ids] of Object.entries(data.coverage))
            children.push(
              section(
                req,
                ids.length ? ids.map((id) => 'Segment ' + (segments.findIndex((s) => s.id === id) + 1)).join(', ') : 'Uncovered',
              ),
            );
        }
        for (const segment of segments) {
          const old = doc.segments.find((item) => item.id === segment.id);
          const position = (data.segments ?? doc.segments).findIndex((item) => item.id === segment.id);
          children.push(
            el('details', { open: segments.length === 1 }, [
              el('summary', {
                textContent:
                  (position >= 0 ? position + 1 + '. ' : '') +
                  segment.intent +
                  ' · ' +
                  secondsLabel(timing(doc.film, segment.seconds) ?? 0) +
                  ' generated',
              }),
              section(
                'Transition',
                segment.transition === 'cut' ? 'Hard cut' : 'Continuation · ' + segment.overlap_frames + ' overlap frames',
              ),
              section('Opening', segment.opening),
              section('Closing', segment.closing),
              section('Bindings', segment.bindings.map((b) => b.role + ' · ' + b.asset_id).join('\n') || 'None'),
              section('Writing skill', segment.skill + ' · ' + segment.skill_reason),
              ...(old ? [section('Current prompt', old.prompt)] : []),
              section('Proposed prompt', segment.prompt),
            ]),
          );
        }
        if (data.suggestions?.length) children.push(section('Suggestions for neighbors', data.suggestions.join('\n')));
        element.replaceChildren(style, ...children);
      },
    },
  );
}
