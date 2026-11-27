// Present the validated Director result alongside the current film, including changes made while preparing it.
import { el } from '../common/dom.js';
import { openAgentActivity } from './agent_activity.js';
import { bindingKind, orderedTags, secondsLabel, timeline, timing } from './director_document.js';
import { generationTime } from './workbench_sessions.js';

export function applyDraft(doc, draft, submission) {
  const index = draft.segment ? doc.segments.findIndex((item) => item.id === draft.segment.id) : -1;
  if (draft.segment && (index < 0 || (submission?.uid && doc.segments[index].uid !== submission.uid)))
    throw new Error('This segment was removed. Undo its removal or generate a new draft.');
  const assets = new Map(doc.assets.map((asset) => [asset.id, asset]));
  for (const segment of draft.segments ?? [draft.segment]) {
    for (const { asset_id, role } of segment.bindings) {
      const asset = assets.get(asset_id);
      const submitted = submission?.assets?.get(asset_id);
      const needed = `Segment ${segment.id} needs ${submitted?.path ?? asset?.path ?? asset_id}.`;
      if (!asset) throw new Error(needed + ' Reselect the missing asset in Asset Library or undo its removal.');
      if (asset.muted) throw new Error(needed + ' Unmute the asset in Asset Library to apply this draft.');
      if (asset.kind !== bindingKind(role))
        throw new Error(
          needed + ` The ${role} role requires a file of type ${bindingKind(role)}. Restore the source or generate a new draft.`,
        );
      if (
        submitted &&
        (asset.root !== submitted.root || asset.path !== submitted.path || (submitted.revision && asset.revision !== submitted.revision))
      )
        throw new Error(needed + ' Its source has changed. Restore the submitted source or generate a new draft.');
    }
    if (!segment.prompt.includes('<')) continue;
    const tags = orderedTags(doc, segment, assets);
    for (const [tag, kind, id] of segment.prompt.matchAll(/<(Picture|Video|Audio):([^<>\s]+)>/g)) {
      if (!tags[kind].some((binding) => binding.asset_id === id))
        throw new Error(`Segment ${segment.id} uses ${tag}. Restore its soundtrack or keyframe tag setting, or generate a new draft.`);
    }
  }
  if (draft.segment) {
    doc.segments[index] = { ...draft.segment, uid: doc.segments[index].uid ?? draft.segment.uid };
  } else {
    const existing = new Map(doc.segments.map((segment) => [segment.id, segment.uid]));
    doc.segments = draft.segments.map((segment) => ({ ...segment, uid: existing.get(segment.id) ?? segment.uid }));
    for (const field of ['outline', 'continuity', 'coverage']) doc[field] = draft[field];
    if (!doc.segments.some((item) => item.id === doc.selected)) doc.selected = doc.segments[0].id;
  }
}

const grid = (...items) => el('div', { className: 'review-grid' }, items);
const section = (label, text) => el('section', {}, [el('strong', { textContent: label }), el('p', { textContent: text })]);

export function openDirectorReview(run, read, apply) {
  if (run.activity) return;
  const element = el('div', { className: 'arisu-film-review' });
  // Shared activity dialog owns focus, Escape, the streamed logs, and the Apply button.
  const style = el('style', {
    textContent: `
    .arisu-film-review{overflow:auto;flex:1;padding:2px;scrollbar-width:thin;min-height:0}
    .arisu-film-review{--edge:var(--border-color,#555)}
    .arisu-film-review section{min-width:0}
    .arisu-film-review .review-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(190px,100%),1fr));gap:12px 18px}
    .arisu-film-review>.review-grid,.arisu-film-review>section{margin-bottom:16px}
    .arisu-film-review details{border:1px solid var(--edge);border-radius:6px;margin-bottom:6px}
    .arisu-film-review p{white-space:pre-wrap;margin:4px 0 0;overflow-wrap:anywhere;line-height:1.55}
    .arisu-film-review summary{cursor:pointer;font-weight:600;padding:10px 12px;overflow-wrap:anywhere}
    .arisu-film-review details[open]>summary{background:color-mix(in srgb,var(--arisu-blue,#adbfd2) 12%,transparent)}
    .arisu-film-review details>p{padding:0 12px 10px}
    .arisu-film-review .review-grid.prompts,.arisu-film-review .shot-info{padding:12px}
    .arisu-film-review .shot-info{border-top:1px solid var(--edge);background:var(--comfy-input-bg,#222)}
    .arisu-film-review .shot-info section:last-child{grid-column:1/-1}
    .arisu-film-review .prompts section{padding:8px 10px;border-inline-start:2px solid var(--edge);background:var(--comfy-input-bg,#222)}
    .arisu-film-review .prompts section:last-child{border-inline-start-color:var(--arisu-blue)}
    .arisu-film-review h3{font-size:14px;margin:0 0 8px}
    .arisu-film-review strong{color:color-mix(in srgb,var(--input-text,#ddd) 82%,var(--comfy-menu-bg,#222));overflow-wrap:anywhere}
    .arisu-film-review .prompts section:last-child strong{color:var(--arisu-blue,#b5cbdf)}

  `,
  });
  let last = '';
  const snapshot = () => {
    const doc = read();
    let applied = false;
    let applyError = '';
    if (run.draft) {
      const copy = structuredClone(doc);
      try {
        applyDraft(copy, JSON.parse(run.draft), run.directorSubmission);
        applied = JSON.stringify(copy) === JSON.stringify(doc);
      } catch (error) {
        applyError = error.message;
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
      applyError,
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
      label: 'Review Draft',
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
            grid(
              section('Film Outline', data.outline),
              section('Continuity', data.continuity),
              section('Estimated Runtime', runtime + (doc.film.target_runtime ? ' · Target ' + doc.film.target_runtime : '')),
            ),
          );
          if (run.directorSubmission?.brief)
            children.push(
              el('details', {}, [
                el('summary', { textContent: 'Submitted Film Requirements' }),
                el('p', { textContent: run.directorSubmission.brief }),
              ]),
            );
          const coverage = Object.entries(data.coverage).map(([req, ids]) =>
            section(req, ids.length ? ids.map((id) => 'Segment ' + (segments.findIndex((s) => s.id === id) + 1)).join(', ') : 'Uncovered'),
          );
          if (coverage.length) children.push(el('section', {}, [el('h3', { textContent: 'Story Coverage' }), grid(...coverage)]));
        } else if (run.directorSubmission?.request) {
          children.push(
            grid(section('Revision Request', run.directorSubmission.request), section('Revision Context', run.directorSubmission.context)),
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
              el('div', { className: 'review-grid prompts' }, [
                ...(old ? [section('Current Prompt', old.prompt)] : []),
                section('Proposed Prompt', segment.prompt),
              ]),
              el('div', { className: 'review-grid shot-info' }, [
                section(
                  'Transition',
                  segment.transition === 'cut' ? 'Hard cut' : 'Continuation · ' + segment.overlap_frames + ' overlap frames',
                ),
                section('Opening', segment.opening),
                section('Closing', segment.closing),
                section('Bindings', segment.bindings.map((b) => b.role + ' · ' + b.asset_id).join('\n') || 'None'),
                section('Writing Skill', segment.skill + ' · ' + segment.skill_reason),
              ]),
            ]),
          );
        }
        if (data.suggestions?.length) children.push(section('Suggestions for Neighbors', data.suggestions.join('\n')));
        element.replaceChildren(style, ...children);
      },
    },
  );
}
