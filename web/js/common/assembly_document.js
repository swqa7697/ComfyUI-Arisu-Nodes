// The edit list of Assemble Video: document rules only, no DOM and no network.
//
// An entry names a video by root and relative path; the server validates its location
// again before it reads a file. `join` is the join before its entry, and it lives only while the two
// neighbouring takes and the cut between them stay the same.
import { moveItem, resourceId } from './shared.js';

export const EMPTY = '{"version":1,"output":null,"entries":[]}';
export const MAX_ENTRIES = 512;
export const MAX_INCLUDED = 100;
const SOURCES = ['take', 'director', 'file'];
const AUDIO = ['auto', 'embedded', 'none'];
const text = (value) => (typeof value === 'string' ? value : '');

export function freshJoin() {
  return { correction: null, fade: 0 };
}

function readRange(value) {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [start, end] = value;
  return Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start ? [start, end] : null;
}

export const sourceKey = (entry) => `${entry.root}:${entry.path}`;

function readJoin(value, previous, entry) {
  const fade = Number.isInteger(value?.fade) && value.fade >= 0 && value.fade <= 50 ? value.fade : 0;
  let correction = value?.correction && typeof value.correction === 'object' ? value.correction : null;
  const basis = correction?.basis;
  if (basis && Object.hasOwn(basis, 'prev_revision') && Object.hasOwn(basis, 'revision')) {
    // Resolve old corrections against the saved edit as it was approved.
    correction = {
      ...correction,
      basis: {
        prev_source: previous && previous.revision === basis.prev_revision ? sourceKey(previous) : '',
        prev_end: basis.prev_end,
        source: entry.revision === basis.revision ? sourceKey(entry) : '',
        start: basis.start,
      },
    };
  }
  return { correction, fade };
}

/** Parse the widget text into the canonical document; anything that is not a version 1 edit is refused. */
export function readEdit(source) {
  const data = JSON.parse(source || EMPTY);
  if (data?.version !== 1 || !Array.isArray(data.entries)) throw new Error('Unsupported edit list');
  let previous;
  return {
    version: 1,
    output: data.output && typeof data.output === 'object' ? data.output : null,
    entries: data.entries
      .filter((entry) => entry && typeof entry === 'object' && text(entry.id))
      .map((entry) => {
        const join = readJoin(entry.join, previous, entry);
        if (entry.included !== false) previous = entry;
        return {
          id: entry.id,
          source: SOURCES.includes(entry.source) ? entry.source : 'file',
          take: text(entry.take),
          predecessor: text(entry.predecessor) || undefined,
          segment: text(entry.segment),
          segment_uid: text(entry.segment_uid) || undefined,
          root: text(entry.root) || 'output',
          path: text(entry.path),
          included: entry.included !== false,
          range: readRange(entry.range),
          audio: AUDIO.includes(entry.audio) ? entry.audio : 'auto',
          join,
        };
      }),
  };
}

/** True while an entry still names a file; an imported or duplicated entry does not until it is rebound. */
export function bound(entry) {
  return entry.path !== '';
}

/**
 * The replacement for an edit that arrives without restoration permission (import, paste, duplication).
 *
 * Order, identity and creative choices stay, so each row can be rebound; every location and
 * join is dropped, and a head trim survives only where a take ID can identify the same footage again.
 */
export function unbindLocations(previous) {
  let doc;
  try {
    doc = readEdit(previous);
  } catch {
    return EMPTY;
  }
  return JSON.stringify({
    version: 1,
    output: doc.output,
    entries: doc.entries.map((entry) => ({
      ...entry,
      root: 'output',
      path: '',
      range: entry.source === 'file' ? null : entry.range,
      join: freshJoin(),
    })),
  });
}

/** An entry for a described file. A file with a take record is a take, whichever dialog found it. */
export function entryFrom(description, source = 'file', segment = '') {
  const take = description.take?.take ?? '';
  return {
    id: resourceId(),
    source: source === 'file' && take ? 'take' : source,
    take,
    segment: segment || description.take?.segment || '',
    segment_uid: description.take?.identity?.uid,
    predecessor: description.take?.predecessor ?? undefined,
    root: description.root,
    path: description.path,
    included: true,
    range: null,
    audio: 'auto',
    join: freshJoin(),
  };
}

/** Insert after `index` (at the end when it is negative). Entries past either limit are dropped or excluded; the counts say which. */
export function insertEntries(doc, entries, index = -1) {
  const room = Math.max(0, MAX_ENTRIES - doc.entries.length);
  const added = entries.slice(0, room);
  let included = doc.entries.filter((entry) => entry.included).length;
  let excluded = 0;
  for (const entry of added) {
    if (!entry.included) continue;
    if (included >= MAX_INCLUDED) {
      entry.included = false;
      excluded++;
    } else included++;
  }
  doc.entries.splice(index < 0 ? doc.entries.length : index + 1, 0, ...added);
  return { dropped: entries.length - added.length, excluded };
}

/** Point an entry at another file, keeping its place and identity; a different file is never trimmed like the old one. */
export function rebindEntry(doc, id, description, source) {
  const entry = doc.entries.find((item) => item.id === id);
  if (!entry) return;
  const same = entry.root === description.root && entry.path === description.path;
  Object.assign(entry, {
    source: source ?? (description.take ? (entry.source === 'director' ? 'director' : 'take') : 'file'),
    take: description.take?.take ?? '',
    predecessor: description.take?.predecessor ?? undefined,
    segment: description.take?.segment || (same ? entry.segment : ''),
    segment_uid: description.take?.identity?.uid ?? (same ? entry.segment_uid : undefined),
    root: description.root,
    path: description.path,
    range: same ? entry.range : null,
  });
}

export function moveEntry(doc, id, offset) {
  const index = doc.entries.findIndex((entry) => entry.id === id);
  moveItem(doc.entries, index, Math.max(-index, Math.min(doc.entries.length - 1 - index, offset)));
}

export function removeEntries(doc, ids) {
  doc.entries = doc.entries.filter((entry) => !ids.has(entry.id));
}

/** Including past the limit is refused; the caller reports it. */
export function setIncluded(doc, id, included) {
  const entry = doc.entries.find((item) => item.id === id);
  if (!entry || entry.included === included) return true;
  if (included && doc.entries.filter((item) => item.included).length >= MAX_INCLUDED) return false;
  entry.included = included;
  return true;
}

/** The included entry before `index`, or null at the head of the film. */
export function previousIncluded(doc, index) {
  for (let i = index - 1; i >= 0; i--) if (doc.entries[i].included) return doc.entries[i];
  return null;
}

// What a join depends on: both neighbouring files and the two frames that meet.
function joinKeys(doc) {
  const keys = new Map();
  doc.entries.forEach((entry, index) => {
    const before = entry.included && bound(entry) ? previousIncluded(doc, index) : null;
    keys.set(
      entry.id,
      before && bound(before)
        ? JSON.stringify([before.id, sourceKey(before), before.range?.[1] ?? null, sourceKey(entry), entry.range?.[0] ?? 0])
        : null,
    );
  });
  return keys;
}

/**
 * Reset every join in `after` whose neighbours or cut point differ from `before`.
 *
 * A replacement, omission, reorder or trim leaves an ordinary cut: the applied correction and fade
 * described a relationship that no longer exists.
 */
export function normalizeJoins(before, after) {
  const earlier = joinKeys(before);
  for (const [id, key] of joinKeys(after)) {
    if (key !== null && key === earlier.get(id)) continue;
    after.entries.find((entry) => entry.id === id).join = freshJoin();
  }
}

/** The frames an entry contributes, once its file is described. */
export function entryFrames(entry, info) {
  if (entry.range) return entry.range[1] - entry.range[0];
  return info?.frames ?? null;
}

/**
 * Whether the incoming entry at `index` continues the take before it, which the experimental colour match requires.
 *
 * `info(entry)` is the file's description and `predecessors` maps a take ID to the predecessor a
 * Director receipt records. Both rows must be current, adjacent in the film and meet at their
 * delivered last and first frames.
 */
export function verifiedJoin(doc, index, info, predecessors = new Map()) {
  const incoming = doc.entries[index];
  const outgoing = incoming?.included ? previousIncluded(doc, index) : null;
  if (!outgoing || !incoming.take || !outgoing.take) return false;
  const [from, to] = [info(outgoing), info(incoming)];
  if (from?.state !== 'ok' || to?.state !== 'ok' || from.take?.take !== outgoing.take || to.take?.take !== incoming.take) return false;
  if ((incoming.range?.[0] ?? 0) !== 0 || (outgoing.range && outgoing.range[1] !== from.frames)) return false;
  return (to.take?.predecessor ?? incoming.predecessor ?? predecessors.get(incoming.take) ?? null) === outgoing.take;
}

/** Running totals of the included rows; `pending` counts rows whose length is not known yet. */
export function totals(doc, info) {
  const result = { entries: doc.entries.length, included: 0, frames: 0, duration: 0, pending: 0, mixed: false };
  let rate = null;
  for (const entry of doc.entries) {
    if (!entry.included) continue;
    result.included++;
    const description = bound(entry) ? info(entry) : null;
    const frames = entryFrames(entry, description);
    const fps = description?.fps ? description.fps[0] / description.fps[1] : null;
    if (!frames || !fps) {
      result.pending++;
      continue;
    }
    result.frames += frames;
    result.duration += frames / fps;
    if (rate !== null && Math.abs(rate - fps) > 1e-9) result.mixed = true;
    rate = fps;
  }
  return result;
}
