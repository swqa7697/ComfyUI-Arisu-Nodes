// Assemble Video: an ordered edit list of saved takes, a checked export plan and one explicit export.
//
// The edit lives in the hidden `edit_json` widget, so the server and API clients read the same document.
// Editing never queues a run and never touches a file; deleting from disk is a separate, confirmed action
// that the server authorizes on its own. Rows keep their files only for workflows the frontend itself
// reopened: an imported, pasted or duplicated edit keeps its order and loses every location.

import { app } from '../../../../scripts/app.js';
import { deletePlan, describe, forget, known, listTakes, preflight } from './assembly_api.js';
import { confirmDeletion, editEntry } from './assembly_dialogs.js';
import {
  bound,
  EMPTY,
  entryFrames,
  entryFrom,
  freshJoin,
  insertEntries,
  moveEntry,
  normalizeJoins,
  previousIncluded,
  readEdit,
  rebindEntry,
  removeEntries,
  setIncluded,
  totals,
  unbindLocations,
  verifiedJoin,
} from './assembly_document.js';
import { detachExport, exportState, recoverExport, runExport, stopExport } from './assembly_export.js';
import { audioLabel, fileName, seconds, specLabel } from './assembly_format.js';
import { previewJoin } from './assembly_join.js';
import { pickTakes } from './assembly_takes.js';
import { forwardToCanvas, keepScrollWheel } from './canvas_gestures.js';
import { el } from './dom.js';
import { joinPath, promptNodeId, resolveString } from './prompt_paths.js';
import { browseResources, posterUrl, VIDEO_ICON } from './resource_browser.js';
import { installSelectionGuards, preservingSelections, registerSelectionOwner } from './selection_context.js';
import { takeSources } from './take_sources.js';
import { installCodecCrf } from './video_encoding.js';
import { hideWidget, setWidget } from './widgets.js';

const TYPE = 'ArisuAssembleVideo';
const EDIT = 'edit_json';
const REQUEST = 'export_request';
const DEFAULT_PROJECT = 'arisu_video';
// Bound of a row's still: a 58 × 40 CSS pixel thumb at a 2× device pixel ratio.
const POSTER_MAX = 116;
const FLAGS = { unbound: 'Needs rebinding', missing: 'Missing', unusable: 'Unusable', changed: 'Changed', stale: 'Stale', pending: '…' };
const nodes = new WeakMap();
// Locations whose description is being fetched or could not be fetched; Refresh asks again.
const asked = new Set();
const STYLE = `
.arisu-assembly{box-sizing:border-box;width:100%;height:100%;overflow:hidden;display:flex;flex-direction:column;gap:8px;padding:8px 10px 12px;
 font:11px/1.3 Arial,system-ui,sans-serif;--surface:var(--comfy-input-bg,#2a2a2a);--row:var(--comfy-menu-bg,#333);--line:var(--border-color,#444);
 --label:color-mix(in srgb,var(--descrip-text,#999),var(--fg-color,#ddd) 30%);--text:var(--input-text,#ccc);--dim:var(--descrip-text,#999);
 --strong:var(--fg-color,#fff);--hover:color-mix(in srgb,var(--row),var(--strong) 8%);--kind:var(--arisu-video);color:var(--text);}
.arisu-assembly *{box-sizing:border-box;}
.arisu-assembly button{font:inherit;color:inherit;background:none;border:0;border-radius:2px;padding:0;cursor:pointer;}
.arisu-assembly .heading{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:24px;}
.arisu-assembly .label{color:var(--label);line-height:20px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.arisu-assembly .icons,.arisu-assembly .tools{display:flex;align-items:center;gap:4px;flex-wrap:wrap;}
.arisu-assembly .icon{width:24px;height:24px;flex:none;border-radius:4px;display:inline-flex;align-items:center;justify-content:center;color:var(--label);font-size:14px;line-height:1;}
.arisu-assembly .icon.dot{font-size:12px;color:var(--kind);}.arisu-assembly .icon.off{color:var(--dim);}
.arisu-assembly .icon:hover{color:var(--strong);background:var(--hover);}
.arisu-assembly :is(.tool,.arisu-action,.primary,.danger){display:inline-flex;align-items:center;justify-content:center;min-height:24px;padding:0 9px;border-radius:3px;
 border:1px solid color-mix(in srgb,var(--line),var(--strong) 10%);}
.arisu-assembly .tool{background:var(--hover);color:var(--text);}
.arisu-assembly .tool:enabled:hover{border-color:var(--label);color:var(--strong);}
.arisu-assembly .status{font-size:11px;color:var(--text);display:flex;flex-wrap:wrap;align-items:center;gap:6px;}
.arisu-assembly .box{flex:1;min-height:90px;display:flex;flex-direction:column;padding:6px;background:var(--surface);border:1px solid var(--line);}
.arisu-assembly .box.empty{align-items:center;justify-content:center;padding:14px 10px;text-align:center;color:var(--dim);line-height:1.5;}
.arisu-assembly .entries{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:4px;scrollbar-width:thin;}
.arisu-assembly .entry{display:flex;align-items:center;gap:7px;height:52px;flex:none;padding:0 5px 0 4px;background:var(--row);border-left:3px solid var(--kind);}
.arisu-assembly .entry.muted{opacity:.55;border-left-color:rgba(120,126,132,.6);}.arisu-assembly .entry.muted .name{text-decoration:line-through;}
.arisu-assembly .entry:not([data-state=ok]){border-left-color:var(--arisu-red);}
.arisu-assembly .entry:focus-within,.arisu-assembly .entry:hover{background:var(--hover);}
.arisu-assembly .entry[data-dragging]{opacity:.4;}
.arisu-assembly .entry[data-drop=before]{box-shadow:0 -4px 0 -1px var(--strong);}
.arisu-assembly .entry[data-drop=after]{box-shadow:0 4px 0 -1px var(--strong);}
.arisu-assembly input[type=checkbox]{width:14px;height:14px;margin:0;flex:none;accent-color:var(--arisu-accent);}
.arisu-assembly .handle{width:14px;flex:none;text-align:center;color:var(--dim);font-size:12px;cursor:grab;}
.arisu-assembly .handle:hover{color:var(--text);}
.arisu-assembly .thumb{width:58px;height:40px;flex:none;display:flex;align-items:center;justify-content:center;object-fit:contain;color:var(--kind);
 background:color-mix(in srgb,var(--kind) 12%,transparent);border:1px solid color-mix(in srgb,var(--kind) 30%,transparent);}
.arisu-assembly .thumb svg{width:16px;height:16px;}
.arisu-assembly .edit{flex:1;min-width:0;text-align:left;}
.arisu-assembly .edit:disabled{cursor:default;}
.arisu-assembly .edit>span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.arisu-assembly .name{color:var(--text);font-size:12px;line-height:16px;}
.arisu-assembly .detail{font-size:11px;line-height:14px;color:var(--dim);font-variant-numeric:tabular-nums;}.arisu-assembly .detail .lead{color:var(--text);}
.arisu-assembly .badge{flex:none;font-size:10px;color:var(--arisu-red);}
.arisu-assembly .move{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);}
.arisu-assembly .move:focus{position:static;width:auto;height:auto;clip-path:none;}
.arisu-assembly .join{display:flex;align-items:center;gap:8px;flex:none;padding:0 6px 0 28px;font-size:10px;color:var(--dim);}
.arisu-assembly .join::before{content:'';flex:1;height:1px;background:var(--line);order:1;}
.arisu-assembly .join .tool{order:2;min-height:20px;}
.arisu-assembly .totals{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-variant-numeric:tabular-nums;}
.arisu-assembly .totals .sum{flex:1;min-width:120px;color:var(--label);}
.arisu-assembly .plan{display:flex;flex-direction:column;gap:3px;max-height:150px;overflow:auto;padding:6px;background:var(--surface);border:1px solid var(--line);border-radius:4px;scrollbar-width:thin;}
.arisu-assembly .plan .need,.arisu-assembly .plan .flag{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-left:6px;border-left:3px solid var(--arisu-red);color:var(--strong);}
.arisu-assembly .plan .warn{color:var(--label);}
.arisu-assembly .export{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.arisu-assembly .receipt{flex:1;min-width:120px;color:var(--label);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
`;

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}
function toast(detail, severity = 'warn') {
  app.extensionManager?.toast?.add?.({ severity, summary: 'Assemble Video', detail, life: 8000 });
}
function read(node) {
  return readEdit(widget(node, EDIT)?.value);
}
const locationKey = (entry) => `${entry.root}|${entry.path}`;
const location = (entry) => ({ root: entry.root, path: entry.path, revision: entry.revision, range: entry.range });

/** The file's description as it applies to this entry: a different revision on disk is a changed source. */
function info(entry) {
  const description = bound(entry) ? known(entry.root, entry.path) : undefined;
  if (!description || description.state === 'missing' || description.state === 'unusable') return description;
  return { ...description, state: entry.revision && description.revision !== entry.revision ? 'changed' : 'ok' };
}

/** What Director reports now, by segment and by take: the stale flag and the predecessor a receipt records. */
function directorView() {
  const segments = new Map();
  const predecessors = new Map();
  for (const source of takeSources())
    for (const segment of source.segments) {
      segments.set(segment.segment, segment);
      if (segment.take) predecessors.set(segment.take.take, segment.take.predecessor ?? null);
    }
  return { segments, predecessors };
}

function rowState(entry, director) {
  if (!bound(entry)) return 'unbound';
  const description = info(entry);
  if (!description) return 'pending';
  if (description.state !== 'ok') return description.state;
  const segment = entry.source === 'director' ? director.segments.get(entry.segment) : null;
  if (segment && (segment.status === 'Needs rerender' || (segment.take && segment.take.take !== entry.take))) return 'stale';
  return 'ok';
}

function invalidate(node) {
  const state = nodes.get(node);
  if (!state) return;
  state.generation++;
  state.controller?.abort();
  state.controller = null;
  detachExport(node);
}

/** Start one editing task; an earlier dialog or request of this node is abandoned. */
function begin(node) {
  const state = nodes.get(node);
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const generation = state.generation;
  const sameGraph = () => nodes.get(node) === state && state.generation === generation;
  return { signal: controller.signal, current: () => !controller.signal.aborted && sameGraph(), sameGraph };
}

/**
 * Make `write` one step of ComfyUI's history, whatever started it.
 *
 * The change tracker records a state on mouse release and on the canvas change events. A drop, an arrow
 * key or Ctrl+Z inside the panel produces neither, so the canvas events are raised here; the graph hooks
 * are kept for frontends that forward them.
 */
function undoable(node, write) {
  node.graph?.beforeChange?.();
  app.canvas?.emitBeforeChange?.();
  try {
    write();
  } finally {
    app.canvas?.emitAfterChange?.();
    node.graph?.afterChange?.();
  }
}

/** Write the edit as one undoable step. Joins whose neighbours or cut changed fall back to a direct cut. */
function commit(node, doc) {
  const state = nodes.get(node);
  const control = widget(node, EDIT);
  let before;
  try {
    before = read(node);
  } catch {
    before = readEdit(EMPTY);
  }
  normalizeJoins(before, doc);
  const text = JSON.stringify(doc);
  if (text !== control.value)
    undoable(node, () => {
      control.value = text;
    });
  const ids = new Set(doc.entries.map((entry) => entry.id));
  for (const id of [...state.selection]) if (!ids.has(id)) state.selection.delete(id);
  state.plan = null;
  render(node);
  node.setDirtyCanvas(true, true);
}

function mutate(node, action) {
  const next = read(node);
  action(next);
  commit(node, next);
}

function reportInsert(result) {
  if (result.dropped) toast(`The edit list is full; ${result.dropped} videos were not added.`);
  if (result.excluded) toast(`An export takes at most 100 videos; ${result.excluded} were added excluded.`);
}

/** The project as typed, or `undefined` while a wire decides it. */
function typedProject(node) {
  const input = node.inputs?.find((entry) => (entry.widget?.name ?? entry.name) === 'project_prefix');
  return input?.link == null ? String(widget(node, 'project_prefix')?.value ?? '') : undefined;
}

/**
 * The project this node works in, known before a run where the text allows it.
 *
 * A wired project is read through Path Builder, string primitives and String Concatenate; anything
 * else falls back to what the last execution reported. The server resolves the input again on export.
 */
async function resolveProject(node) {
  const state = nodes.get(node);
  let value = typedProject(node);
  if (value === undefined) {
    try {
      const prompt = await app.graphToPrompt();
      const resolved = resolveString(prompt.output, prompt.output[promptNodeId(prompt.output, node, TYPE)].inputs.project_prefix);
      value = resolved.unresolved ? state.executed : resolved.value;
    } catch {
      value = state.executed;
    }
    if (value === undefined)
      throw new Error('The project is computed during a run. Type it, connect Path Builder, or run the workflow once.');
  }
  state.project = joinPath([value]) || DEFAULT_PROJECT;
  return state.project;
}

function shownProject(node) {
  const typed = typedProject(node);
  if (typed !== undefined) return joinPath([typed]) || DEFAULT_PROJECT;
  return nodes.get(node)?.project ?? null;
}

/** Fetch descriptions for rows that have none yet, once per location, then draw again. */
function ensureDescribed(node, doc) {
  const state = nodes.get(node);
  const missing = doc.entries.filter((entry) => bound(entry) && !known(entry.root, entry.path) && !asked.has(locationKey(entry)));
  if (!missing.length) return;
  for (const entry of missing) asked.add(locationKey(entry));
  void (async () => {
    try {
      await describe(missing);
      for (const entry of missing) asked.delete(locationKey(entry));
    } catch {
      // The rows stay pending; Refresh asks again.
    }
    if (nodes.get(node) === state) render(node);
  })();
}

/** Describe every bound row again; a file that changed on disk is flagged, never accepted. */
async function revalidate(node) {
  const state = nodes.get(node);
  let doc;
  try {
    doc = read(node);
  } catch {
    return;
  }
  const rows = doc.entries.filter(bound);
  for (const entry of rows) asked.add(locationKey(entry));
  try {
    await describe(rows);
    for (const entry of rows) asked.delete(locationKey(entry));
  } catch (error) {
    if (nodes.get(node) === state) toast(error.message, 'error');
  }
  if (nodes.get(node) === state) render(node);
}

async function addTakes(node) {
  const task = begin(node);
  try {
    const project = await resolveProject(node);
    if (!task.current()) return;
    const doc = read(node);
    const picked = await pickTakes({
      project,
      mode: 'add',
      taken: (root, path) => doc.entries.some((entry) => entry.root === root && entry.path === path),
      signal: task.signal,
    });
    if (!picked?.length || !task.current()) return;
    const state = nodes.get(node);
    const next = read(node);
    const after = next.entries.findLastIndex((entry) => state.selection.has(entry.id));
    const entries = picked.map((take) => entryFrom(take, 'take'));
    const result = insertEntries(next, entries, after);
    reportInsert(result);
    const count = entries.length - result.dropped;
    if (count) state.selection = new Set(entries.slice(0, count).map((entry) => entry.id));
    commit(node, next);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}

async function importDirector(node, source) {
  const state = nodes.get(node);
  const sources = takeSources();
  state.choices = null;
  if (!sources.length) return toast('This workflow has no Director Workbench with a film.');
  if (!source && sources.length > 1) {
    state.choices = sources;
    return render(node);
  }
  const chosen = source ?? sources[0];
  const ready = chosen.segments.filter((segment) => segment.take);
  const skipped = chosen.segments.length - ready.length;
  if (!ready.length) return toast('Director has no rendered takes yet.');
  const task = begin(node);
  try {
    const descriptions = await describe(
      ready.map((segment) => segment.take),
      task.signal,
    );
    if (!task.current()) return;
    const next = read(node);
    reportInsert(
      insertEntries(
        next,
        // The receipt's own take ID and revision are kept, so a file replaced since the render is flagged.
        ready.map((segment, index) => ({
          ...entryFrom(descriptions[index], 'director', segment.segment),
          take: segment.take.take,
          revision: segment.take.revision || descriptions[index].revision || '',
        })),
      ),
    );
    state.message = `Imported ${ready.length} takes in film order${skipped ? `; ${skipped} segments have no render` : ''}.`;
    commit(node, next);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}

/** Follow Director's current takes for rows that were imported from it; every other row is left alone. */
async function refreshDirector(node) {
  const { segments } = directorView();
  const doc = read(node);
  const moved = doc.entries.filter((entry) => {
    const take = entry.source === 'director' ? segments.get(entry.segment)?.take : null;
    return take && (take.path !== entry.path || take.take !== entry.take || (take.revision && take.revision !== entry.revision));
  });
  const state = nodes.get(node);
  if (!moved.length) {
    state.message = 'Director takes are already current.';
    return render(node);
  }
  const task = begin(node);
  try {
    const descriptions = await describe(
      moved.map((entry) => segments.get(entry.segment).take),
      task.signal,
    );
    if (!task.current()) return;
    const next = read(node);
    moved.forEach((entry, index) => {
      const take = segments.get(entry.segment).take;
      rebindEntry(next, entry.id, descriptions[index], 'director');
      Object.assign(
        next.entries.find((item) => item.id === entry.id),
        { take: take.take, segment: entry.segment, revision: take.revision || descriptions[index].revision || '' },
      );
    });
    state.message = `Updated ${moved.length} rows from Director.`;
    commit(node, next);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}

/** Browse for one video; `apply(description)` receives a file the server could describe. */
async function browseVideo(node, start, apply) {
  const task = begin(node);
  const doc = read(node);
  const adapter = {
    widgets: [
      { name: 'root', value: start?.root ?? 'output' },
      { name: 'path', value: start?.path ?? '' },
    ],
  };
  await browseResources(adapter, {
    mixed: true,
    kinds: ['video'],
    selected: (root, path) => doc.entries.some((entry) => entry.root === root && entry.path === path),
    signal: task.signal,
    isCurrent: task.current,
    onPick: async (path, root) => {
      try {
        forget(root, path);
        const [description] = await describe([{ root, path }], task.signal);
        if (!task.current()) return;
        if (description.state !== 'ok')
          return toast('This video cannot be used: it is missing, incomplete or not a supported format.', 'error');
        apply(description);
      } catch (error) {
        if (task.current()) toast(error.message, 'error');
      }
    },
  });
}

function addExisting(node) {
  const doc = read(node);
  const project = shownProject(node);
  const start = doc.entries.findLast(bound) ?? (project ? { root: 'output', path: `${project}/videos` } : null);
  return browseVideo(node, start, (description) => {
    const next = read(node);
    reportInsert(insertEntries(next, [entryFrom(description)]));
    commit(node, next);
  });
}

/** Replace or reselect the footage of one row, keeping its place: a take picker for takes, Browse for plain files. */
async function replace(node, entry) {
  const apply = (description) => mutate(node, (next) => rebindEntry(next, entry.id, description, description.take ? 'take' : 'file'));
  if (entry.source === 'file') return browseVideo(node, bound(entry) ? entry : null, apply);
  const task = begin(node);
  try {
    const project = await resolveProject(node);
    if (!task.current()) return;
    const picked = await pickTakes({ project, mode: 'replace', current: bound(entry) ? entry : null, signal: task.signal });
    if (!picked?.length || !task.current()) return;
    // The picker listed the file as it is now; accepting it records that revision.
    apply(picked[0]);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}

/** One explicit action: find unbound rows again by take ID inside this node's project. Nothing rebinds on its own. */
async function rebind(node) {
  const task = begin(node);
  const state = nodes.get(node);
  try {
    const project = await resolveProject(node);
    if (!task.current()) return;
    const waiting = read(node).entries.filter((entry) => !bound(entry) && entry.take);
    const { takes } = await listTakes(
      project,
      waiting.some((entry) => entry.source === 'director'),
      task.signal,
    );
    if (!task.current()) return;
    const found = new Map(takes.filter((take) => take.state === 'ok' && take.take?.take).map((take) => [take.take.take, take]));
    const next = read(node);
    let count = 0;
    for (const entry of next.entries) {
      const take = !bound(entry) && entry.take ? found.get(entry.take) : null;
      if (!take) continue;
      Object.assign(entry, { root: take.root, path: take.path, revision: take.revision ?? '' });
      count++;
    }
    state.message = `Rebound ${count} of ${waiting.length} rows from ${project}.`;
    commit(node, next);
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}

async function editRow(node, entry) {
  const description = info(entry);
  if (!description || description.state === 'missing' || description.state === 'unusable') return;
  const task = begin(node);
  const result = await editEntry(entry, description, { signal: task.signal });
  if (!result || !task.current()) return;
  mutate(node, (next) => {
    const target = next.entries.find((item) => item.id === entry.id);
    if (target) Object.assign(target, { audio: result.audio, range: result.range });
  });
}

async function auditionJoin(node, id) {
  const doc = read(node);
  const index = doc.entries.findIndex((entry) => entry.id === id);
  const incoming = doc.entries[index];
  const outgoing = incoming ? previousIncluded(doc, index) : null;
  if (!outgoing) return;
  const task = begin(node);
  const result = await previewJoin({
    outgoing: location(outgoing),
    incoming: location(incoming),
    join: incoming.join,
    verified: verifiedJoin(doc, index, info, directorView().predecessors),
    signal: task.signal,
  });
  if (!result || !task.current()) return;
  mutate(node, (next) => {
    const target = next.entries.find((entry) => entry.id === id);
    if (!target) return;
    // The basis names the two frames the correction was judged on; the server refuses it once they differ.
    const basis = {
      prev_revision: outgoing.revision,
      prev_end: outgoing.range?.[1] ?? info(outgoing)?.frames ?? null,
      revision: incoming.revision,
      start: incoming.range?.[0] ?? 0,
    };
    target.join = { correction: result.correction ? { ...result.correction, basis } : null, fade: result.fade };
  });
}

async function check(node) {
  const state = nodes.get(node);
  const task = begin(node);
  const project = await resolveProject(node);
  const body = {
    project,
    export_name: String(widget(node, 'export_name')?.value ?? ''),
    encoding: widget(node, 'encoding')?.value,
    codec: widget(node, 'codec')?.value,
    crf: widget(node, 'crf')?.value,
    document: read(node),
  };
  const plan = await preflight(body, task.signal);
  if (!task.current()) return null;
  state.plan = plan;
  render(node);
  return plan;
}

async function checkExport(node) {
  try {
    await check(node);
  } catch (error) {
    toast(error.message, 'error');
  }
}

/** Follow a submitted or recovered export to its receipt and report how it ended. */
async function follow(node, job) {
  const state = nodes.get(node);
  const progress = (message) => {
    state.progress = message;
    // Draw the whole panel only when the job appears or ends; a progress tick changes one line.
    if (Boolean(exportState(node).pending) !== state.shownPending) render(node);
    else if (state.receipt) state.receipt.textContent = message;
  };
  render(node);
  try {
    const receipt = await job(progress);
    if (receipt && nodes.get(node) === state) toast(`Exported ${receipt.path}`, 'success');
  } catch (error) {
    if (nodes.get(node) === state) toast(error.stopped ? 'The export was stopped.' : error.message, error.stopped ? 'info' : 'error');
  } finally {
    state.progress = '';
    if (nodes.get(node) === state) render(node);
  }
}

async function exportFilm(node) {
  const state = nodes.get(node);
  if (state.busy || exportState(node).running) return;
  state.busy = true;
  try {
    // The plan is checked again at the moment of export; edits made after this point belong to the next one.
    const plan = await check(node);
    if (!plan?.ready) return plan && toast('The export check found problems. Resolve them first.');
  } catch (error) {
    return toast(error.message, 'error');
  } finally {
    state.busy = false;
  }
  await follow(node, (progress) => runExport(node, progress));
}

async function stop(node) {
  try {
    await stopExport(node);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function deleteFiles(node) {
  const state = nodes.get(node);
  const selected = read(node).entries.filter((entry) => state.selection.has(entry.id));
  const rows = selected.filter(bound);
  const locations = new Map(rows.map((entry) => [locationKey(entry), entry]));
  if (!locations.size) return;
  const task = begin(node);
  try {
    const plan = await deletePlan([...locations.values()], false, task.signal);
    if (!task.current()) return;
    if (!(await confirmDeletion(plan, { signal: task.signal, unbound: selected.length - rows.length })) || !task.current()) return;
    const reviewed = plan.entries.filter((entry) => entry.state === 'deletable');
    const done = await deletePlan(reviewed, true);
    const deleted = new Set();
    for (const entry of done.entries) {
      if (entry.state !== 'deleted' && entry.state !== 'partial') continue;
      const removed = entry.state === 'partial' ? entry.removed : entry.files?.map((file) => file.path);
      for (const path of removed ?? [entry.path]) {
        deleted.add(locationKey({ root: entry.root, path }));
        forget(entry.root, path);
      }
    }
    // Another dialog can open while the confirmed delete runs. Update only the edit that accepted it.
    if (!task.sameGraph()) return;
    if (done.entries.some((entry) => entry.state === 'deferred')) toast('Files in use by an export will be deleted when it finishes.');
    if (done.entries.some((entry) => entry.state === 'partial'))
      toast('Deletion stopped before it finished. Some of the reviewed files or folders remain on disk.');
    if (done.entries.some((entry) => entry.state === 'refused')) toast('Some files changed or could not be removed. Review them again.');
    // Rows of deleted files leave the edit in one step; Undo brings the rows back, not the files.
    if (deleted.size)
      mutate(node, (next) =>
        removeEntries(next, new Set(next.entries.filter((entry) => deleted.has(locationKey(entry))).map((entry) => entry.id))),
      );
  } catch (error) {
    if (task.current()) toast(error.message, 'error');
  }
}

function clearOutput(node) {
  mutate(node, (next) => {
    next.output = null;
  });
}

function resolveNeed(node, need) {
  const { kind, entries = [], suggested = {} } = need;
  const affected = new Set(entries);
  if (kind === 'choose_codec') {
    undoable(node, () => {
      setWidget(node, widget(node, 'encoding'), 'encode');
      setWidget(node, widget(node, 'codec'), suggested.codec);
      setWidget(node, widget(node, 'crf'), suggested.crf);
    });
  } else
    mutate(node, (next) => {
      if (kind === 'confirm_output') next.output = suggested;
      for (const entry of next.entries) {
        if (!affected.has(entry.id)) continue;
        if (kind === 'switch_audio') entry.audio = suggested.audio ?? 'embedded';
        if (kind === 'refresh_correction') entry.join = freshJoin();
      }
    });
  return checkExport(node);
}

function needText(need) {
  const rows = need.entries?.length ?? 0;
  if (need.kind === 'choose_codec')
    return [
      'The sources have no single codec to inherit.',
      `Use ${String(need.suggested?.codec).toUpperCase()} CRF ${need.suggested?.crf}`,
    ];
  if (need.kind === 'confirm_output') return ['The sources differ in size, frame rate or sound.', `Confirm ${specLabel(need.suggested)}`];
  if (need.kind === 'switch_audio') return [`Saved PCM is missing or changed for ${rows} rows.`, 'Use Embedded Audio'];
  return [`A colour match no longer fits its join on ${rows} rows.`, 'Clear Stale Corrections'];
}

/** Keep keyboard focus on the same control when the panel is drawn again, for example after a dialog returns it. */
function retainFocus(root) {
  const active = document.activeElement;
  if (!active || !root.contains?.(active)) return () => {};
  const row = (control) => control.closest('[data-entry-id]')?.dataset.entryId;
  const key = (control) => control.ariaLabel ?? control.textContent;
  const owner = row(active);
  return () =>
    Array.from(root.querySelectorAll('button,input,select,[tabindex]'))
      .find((control) => control.tagName === active.tagName && key(control) === key(active) && row(control) === owner)
      ?.focus({ preventScroll: true });
}

function render(node) {
  const state = nodes.get(node);
  if (!state) return;
  let doc;
  try {
    doc = read(node);
  } catch (error) {
    state.body.replaceChildren(el('span', { textContent: error.message }));
    return;
  }
  const director = directorView();
  const flow = exportState(node);
  const working = state.busy || flow.running;
  const button = (text, action, title = text, className = 'icon', extra = {}) =>
    el('button', {
      className,
      textContent: text,
      title,
      ariaLabel: title,
      onclick: (event) => {
        event?.stopPropagation?.();
        return action();
      },
      ...extra,
    });
  const command = (id) => app.extensionManager?.command?.execute?.(id);
  const move = (id, offset) => {
    state.focus = id;
    mutate(node, (next) => moveEntry(next, id, offset));
  };
  const clearDrop = () => {
    if (state.dropRow) delete state.dropRow.dataset.drop;
    state.dropRow = null;
  };
  const endDrag = () => {
    clearDrop();
    if (state.dragRow) delete state.dragRow.dataset.dragging;
    state.dragRow = null;
    state.drag = null;
  };
  const flagged = new Map(
    (state.plan?.entries ?? []).filter((entry) => entry.state !== 'ok' || entry.message).map((entry) => [entry.id, entry]),
  );
  state.rows = new Map();
  const rows = doc.entries.flatMap((entry, index) => {
    const description = info(entry);
    const status = rowState(entry, director);
    const usable = description && description.state !== 'missing' && description.state !== 'unusable';
    const frames = usable ? entryFrames(entry, description) : null;
    const name = `${entry.segment ? `${entry.segment} · ` : ''}${bound(entry) ? fileName(entry.path) : entry.take || 'Unbound video'}`;
    const lead = frames
      ? `${entry.range ? `${frames} of ${description.frames}` : frames} f · ${seconds((frames * description.fps[1]) / description.fps[0])}`
      : FLAGS[status] || '—';
    const rest = usable
      ? ` · ${description.width}×${description.height} · ${entry.audio === 'none' ? 'Silent' : entry.audio === 'embedded' && description.audio ? 'Embedded' : audioLabel(description.audio)}`
      : '';
    const icon = () => {
      const span = el('span', { className: 'thumb', ariaHidden: 'true' });
      span.innerHTML = VIDEO_ICON;
      return span;
    };
    const poster = () => {
      const key = `${locationKey(entry)}|${entry.range?.[0] ?? 0}`;
      let image = state.posters.get(key);
      if (!image) {
        const at = usable && entry.range ? (entry.range[0] * description.fps[1]) / description.fps[0] : 0;
        image = el('img', { className: 'thumb', alt: '', loading: 'lazy', src: posterUrl(entry.root, entry.path, at, POSTER_MAX) });
        image.onerror = () => {
          state.posters.delete(key);
          image.replaceWith(icon());
        };
        state.posters.set(key, image);
      }
      return image;
    };
    const select = el('input', {
      type: 'checkbox',
      checked: state.selection.has(entry.id),
      ariaLabel: `Select ${name}`,
      onchange: (event) => {
        if (event.target.checked) state.selection.add(entry.id);
        else state.selection.delete(entry.id);
        render(node);
      },
    });
    const handle = el('span', {
      className: 'handle',
      textContent: '⠿',
      draggable: true,
      tabIndex: 0,
      role: 'button',
      ariaLabel: `Reorder ${name} with the arrow keys`,
      onkeydown: (event) => {
        if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
        event.preventDefault();
        move(entry.id, event.key === 'ArrowUp' ? -1 : 1);
      },
    });
    const edit = el(
      'button',
      { className: 'edit', ariaLabel: `Preview and edit ${name}`, disabled: !usable, onclick: () => editRow(node, entry) },
      [
        el('span', { className: 'name', textContent: name, title: bound(entry) ? `${entry.root}:${entry.path}` : '' }),
        el('span', { className: 'detail' }, [el('span', { className: 'lead', textContent: lead }), el('span', { textContent: rest })]),
      ],
    );
    const note = flagged.get(entry.id)?.message;
    const row = el(
      'div',
      {
        className: `entry${entry.included ? '' : ' muted'}`,
        role: 'listitem',
        // The pointer half of the hovered row decides whether the dragged row lands above or below it.
        ondragover: (event) => {
          event.preventDefault();
          if (!state.drag || state.drag === entry.id) return clearDrop();
          const rect = row.getBoundingClientRect();
          if (state.dropRow !== row) clearDrop();
          row.dataset.drop = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after';
          state.dropRow = row;
        },
        ondrop: (event) => {
          event.preventDefault();
          const side = row.dataset.drop ?? 'after';
          const id = state.drag;
          const from = doc.entries.findIndex((item) => item.id === id);
          endDrag();
          if (from < 0 || from === index) return;
          const insert = (side === 'before' ? index : index + 1) - (from < index ? 1 : 0);
          if (insert !== from) move(id, insert - from);
        },
      },
      [
        select,
        handle,
        bound(entry) ? poster() : icon(),
        edit,
        // A row without measured frames already shows its flag in place of them.
        ...((status === 'ok' || !frames) && !note
          ? []
          : [el('span', { className: 'badge', textContent: note || FLAGS[status], title: note || FLAGS[status] })]),
        ...(status === 'ok' || status === 'pending' ? [] : [button('Reselect', () => replace(node, entry), `Reselect ${name}`, 'tool')]),
        button('⇄', () => replace(node, entry), `Replace ${name}`),
        button(
          entry.included ? '●' : '⦸',
          () => mutate(node, (next) => setIncluded(next, entry.id, !entry.included) || toast('An export takes at most 100 videos.')),
          entry.included ? `Exclude ${name}` : `Include ${name}`,
          `icon dot${entry.included ? '' : ' off'}`,
        ),
        button('×', () => mutate(node, (next) => removeEntries(next, new Set([entry.id]))), `Remove ${name} from the edit`),
        ...[-1, 1].map((offset) => button(offset < 0 ? 'Move Up' : 'Move Down', () => move(entry.id, offset), undefined, 'move')),
      ],
    );
    row.dataset.entryId = entry.id;
    row.dataset.state = status;
    handle.ondragstart = (event) => {
      state.drag = entry.id;
      state.dragRow = row;
      row.dataset.dragging = '';
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', entry.id);
      }
    };
    handle.ondragend = endDrag;
    state.rows.set(entry.id, { row, handle });
    const before = entry.included && bound(entry) ? previousIncluded(doc, index) : null;
    if (!before || !bound(before)) return [row];
    const treatment = [entry.join.correction ? 'Colour match' : null, entry.join.fade ? `Fade ${entry.join.fade} ms` : null].filter(
      Boolean,
    );
    const join = el('div', { className: 'join' }, [
      el('span', { textContent: treatment.join(' · ') || 'Direct cut' }),
      button('Preview Join', () => auditionJoin(node, entry.id), `Preview the join before ${name}`, 'tool'),
    ]);
    join.dataset.join = entry.id;
    return [join, row];
  });

  const sum = totals(doc, info);
  const selected = doc.entries.filter((entry) => state.selection.has(entry.id));
  const waiting = doc.entries.filter((entry) => !bound(entry) && entry.take).length;
  const unbound = doc.entries.filter((entry) => !bound(entry)).length;
  const project = shownProject(node);
  const status = [
    ...(state.message ? [el('span', { textContent: state.message })] : []),
    ...(unbound
      ? [
          el('span', { textContent: `${unbound} rows lost their files when this edit was imported or copied.` }),
          ...(waiting
            ? [button(`Rebind from Project ${project ?? ''}`.trim(), () => rebind(node), 'Find these takes again in the project', 'tool')]
            : []),
        ]
      : []),
    ...(state.choices ?? []).map((source) => button(`Import ${source.label}`, () => importDirector(node, source), undefined, 'tool')),
  ];
  const plan = state.plan;
  const usableRows = doc.entries.some((entry) => entry.included && rowState(entry, director) === 'ok');
  const planView = plan
    ? [
        el('section', { className: 'plan', ariaLabel: 'Export check' }, [
          el('div', {
            textContent: `${plan.frames} frames · ${seconds(plan.duration)} · ${specLabel({ ...plan, sample_rate: plan.audio ? plan.sample_rate : null })}`,
          }),
          el('div', { textContent: `To ${plan.destination} · ${plan.backend === 'pyav' ? 'PyAV fallback' : 'FFmpeg'}` }),
          el('div', {
            textContent: `Video: ${plan.video.operation === 'copy' ? 'copy' : `encode ${plan.video.codec}${plan.video.crf == null ? '' : ` CRF ${plan.video.crf}`}`} — ${plan.video.reason}`,
          }),
          el('div', { textContent: plan.audio ? `Audio: ${plan.audio.operation} — ${plan.audio.reason}` : 'Audio: no audio track' }),
          ...(plan.warnings ?? []).map((warning) => el('div', { className: 'warn', textContent: warning })),
          ...(plan.needs ?? []).map((need) => {
            const [text, action] = needText(need);
            return el('div', { className: 'need' }, [
              el('span', { textContent: text }),
              button(action, () => resolveNeed(node, need), action, 'tool'),
            ]);
          }),
          ...[...flagged.values()]
            .filter((entry) => entry.state !== 'ok')
            .map((entry) =>
              el('div', { className: 'flag' }, [
                el('span', { textContent: `${FLAGS[entry.state] ?? entry.state}: ${entry.message ?? 'this row cannot be exported'}` }),
                button('Go to Row', () => state.rows.get(entry.id)?.handle.focus(), 'Go to the affected row', 'tool'),
              ]),
            ),
        ]),
      ]
    : [];
  const last = flow.last;
  const receipt = el('output', {
    className: 'receipt',
    role: 'status',
    ariaLive: 'polite',
    textContent: state.progress || (flow.pending ? 'Export pending' : last ? `Exported ${last.path} · ${last.frames} frames` : ''),
    title: last?.path ?? '',
  });
  state.receipt = receipt;
  state.shownPending = Boolean(flow.pending);
  const refocus = retainFocus(state.body);
  state.body.replaceChildren(
    el('style', { textContent: STYLE }),
    el('div', { className: 'heading' }, [
      el('span', {
        className: 'label',
        textContent: project ? `Project ${project}` : 'Project resolves at run time',
        title: project ?? '',
      }),
      el('div', { className: 'icons' }, [
        button('↻', () => revalidate(node), 'Refresh file states'),
        button('↶', () => command('Comfy.Undo'), 'Undo'),
        button('↷', () => command('Comfy.Redo'), 'Redo'),
      ]),
    ]),
    el('div', { className: 'tools' }, [
      button('Add Project Takes', () => addTakes(node), 'Add published takes of the project', 'tool'),
      button('Import from Director', () => importDirector(node), 'Import Director takes in film order', 'tool'),
      button('Add Existing Video', () => addExisting(node), 'Add a video file by browsing', 'tool'),
      ...(doc.entries.some((entry) => entry.source === 'director')
        ? [button('Refresh from Director', () => refreshDirector(node), 'Follow the current Director takes', 'tool')]
        : []),
    ]),
    el('output', { className: 'status', ariaLive: 'polite', hidden: !status.length }, status),
    doc.entries.length
      ? el('div', { className: 'box' }, [el('div', { className: 'entries', role: 'list', onwheel: keepScrollWheel }, rows)])
      : el('div', { className: 'box empty' }, [
          el('div', { textContent: 'No Videos in This Edit' }),
          el('div', { textContent: 'Add takes, import a Director film, or browse for a video.' }),
        ]),
    el('div', { className: 'totals' }, [
      el('span', {
        className: 'sum',
        textContent:
          `${sum.included} of ${sum.entries} · ${sum.frames} frames · ${seconds(sum.duration)}` +
          (sum.mixed ? ' · mixed frame rates, see the export check' : '') +
          (sum.pending ? ` · ${sum.pending} not measured` : ''),
      }),
      ...(doc.output ? [button('Clear Confirmed Output', () => clearOutput(node), specLabel(doc.output), 'tool')] : []),
      button(
        'Remove Selected',
        () => mutate(node, (next) => removeEntries(next, new Set(state.selection))),
        'Remove the selected rows from the edit; no file is touched',
        'tool',
        { disabled: !selected.length },
      ),
      button('Delete Files…', () => deleteFiles(node), 'Delete the selected video files from disk', 'danger', {
        disabled: !selected.some(bound),
      }),
    ]),
    ...planView,
    el('div', { className: 'export' }, [
      button('Check Export', () => checkExport(node), 'Check what the export will do', 'tool', { disabled: working || !usableRows }),
      button('Export', () => exportFilm(node), 'Export the film as a new version', 'primary', {
        disabled: working || !usableRows || Boolean(flow.pending) || (plan ? !plan.ready : false),
      }),
      ...(flow.pending ? [button('Stop', () => stop(node), 'Stop this export', 'tool')] : []),
      receipt,
    ]),
  );
  if (state.focus) {
    state.rows.get(state.focus)?.handle.focus();
    state.focus = null;
  } else refocus();
  ensureDescribed(node, doc);
}

/** Keep the two state widgets out of sight and socketless, and let the codec own the CRF range. */
function prepare(node) {
  for (const name of [EDIT, REQUEST]) {
    const control = widget(node, name);
    if (!control) continue;
    control.options ??= {};
    control.options.socketless = true;
    hideWidget(node, control);
  }
  const request = widget(node, REQUEST);
  if (request) {
    // The one-shot ID is written only into a submitted copy of the prompt, never into the workflow.
    request.value = '';
    request.serializeValue = () => '';
  }
  installCodecCrf(node);
  const encoding = widget(node, 'encoding');
  const follow = () => {
    for (const name of ['codec', 'crf']) if (widget(node, name)) widget(node, name).disabled = encoding?.value === 'inherit';
  };
  if (encoding && !encoding.arisuAssembly) {
    const callback = encoding.callback;
    encoding.callback = function (...args) {
      const result = callback?.apply(this, args);
      follow();
      return result;
    };
    encoding.arisuAssembly = true;
  }
  follow();
}

/**
 * ComfyUI hears its history keys before the panel does, so Ctrl/Cmd+Z works from a focused row or button
 * without help. It skips every INPUT, though: a focused row checkbox is the one place that forwards them.
 */
function historyKeys(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  if (event.target?.tagName !== 'INPUT' || event.target.type !== 'checkbox') return;
  const key = String(event.key).toLowerCase();
  const id = key === 'z' ? (event.shiftKey ? 'Comfy.Redo' : 'Comfy.Undo') : key === 'y' ? 'Comfy.Redo' : null;
  if (!id) return;
  event.preventDefault();
  app.extensionManager?.command?.execute?.(id);
}

registerSelectionOwner(TYPE, {
  properties: ['arisuAssembly'],
  fields: [
    [EDIT, 5, unbindLocations],
    [REQUEST, 6, ''],
  ],
  invalidate,
});

app.registerExtension({
  name: 'Arisu.Common.AssembleVideo',
  init: installSelectionGuards,
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== TYPE) return;
    const chain = (name, fn) => {
      const original = nodeType.prototype[name];
      nodeType.prototype[name] = function (...args) {
        const result = original?.apply(this, args);
        fn.apply(this, args);
        return result;
      };
    };
    chain('onNodeCreated', function () {
      const body = el('div', { className: 'arisu-assembly' });
      nodes.set(this, { body, generation: 0, controller: null, selection: new Set(), posters: new Map(), rows: new Map(), plan: null });
      body.addEventListener('keydown', historyKeys);
      forwardToCanvas(body);
      prepare(this);
      const dom = this.addDOMWidget('assembly', 'arisu-assembly', body, { serialize: false, hideOnZoom: false, getMinHeight: () => 460 });
      dom.serialize = false;
      this.setSize([560, 720]);
      render(this);
    });
    chain('onResize', (size) => {
      size[0] = Math.max(480, size[0]);
    });
    chain('onConfigure', function () {
      const state = nodes.get(this);
      if (!state) return;
      invalidate(this);
      const wired = (input) => [EDIT, REQUEST].includes(input.widget?.name ?? input.name);
      const linked = this.inputs?.some((input) => wired(input) && input.link != null);
      for (let i = (this.inputs?.length ?? 0) - 1; i >= 0; i--) if (wired(this.inputs[i])) this.removeInput(i);
      if (linked) toast('Edit list wires were removed; the edit is not a connectable value.');
      prepare(this);
      Object.assign(state, { plan: null, message: '', choices: null, project: null });
      state.selection.clear();
      const control = widget(this, EDIT);
      if (linked || !preservingSelections() || !app.configuringGraph) {
        // Imported, pasted or duplicated: the order stays, every location and receipt goes.
        if (control) control.value = linked ? EMPTY : unbindLocations(control.value);
        if (this.properties) delete this.properties.arisuAssembly;
        render(this);
        return;
      }
      // Marks every row as asked before the panel draws, so each file is described once.
      void revalidate(this);
      render(this);
      if (exportState(this).pending) void follow(this, (progress) => recoverExport(this, progress));
    });
    chain('onExecuted', function (message) {
      const state = nodes.get(this);
      const project = message?.arisu_project?.[0];
      if (!state || typeof project !== 'string') return;
      state.executed = project;
      state.project = joinPath([project]) || DEFAULT_PROJECT;
      render(this);
    });
    chain('onRemoved', function () {
      const state = nodes.get(this);
      invalidate(this);
      state?.body.remove();
      nodes.delete(this);
    });
  },
});
