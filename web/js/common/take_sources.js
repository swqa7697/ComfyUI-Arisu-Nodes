// Panels that render takes publish them here, so a common panel can list them without importing a node family.
import { allNodes } from './shared.js';

const readers = new Map();

/** `read(node)` returns `{ label, segments: [{ segment, label, transition, status, take }] }` in film order, or null. */
export function registerTakeSource(type, read) {
  readers.set(type, read);
}

/** Every registered source in the open workflow; a node whose document cannot be read is left out. */
export function takeSources() {
  return allNodes().flatMap((node) => {
    try {
      const source = readers.get(node.type)?.(node);
      return source ? [{ node, ...source }] : [];
    } catch {
      return [];
    }
  });
}

/** Match saved takes to the open film by persistent segment identity or an exact legacy receipt. */
export function takeCatalog(descriptions = []) {
  const byUid = new Map();
  const byFile = new Map();
  const films = new Map();
  const snapshots = new Map();
  for (const item of descriptions) {
    const record = item.take;
    const film = record?.identity?.film;
    if (film && (!snapshots.has(film) || record.created > snapshots.get(film).created)) snapshots.set(film, record);
  }
  for (const source of takeSources()) {
    if (source.film) films.set(source.film, source);
    for (const segment of source.segments) {
      if (segment.uid) byUid.set(segment.uid, segment);
      if (segment.take) byFile.set(segment.take.path, segment);
    }
  }
  return (item) => {
    const record = item.take;
    if (record?.origin !== 'director') return null;
    const saved = record.identity;
    const live = byFile.get(item.path) ?? byUid.get(saved?.uid);
    const display = live ?? saved ?? record.recorded_segment;
    const latest = snapshots.get(saved?.film)?.identity.sequence;
    const position = latest?.indexOf(saved?.uid);
    const removed = !live && !!saved?.film && (films.has(saved.film) || position === -1);
    const order = live?.order ?? (position >= 0 ? position + 1 : display?.order);
    const segment = removed
      ? 'Removed segment'
      : order
        ? `Segment ${String(order).padStart(2, '0')}`
        : record.segment
          ? `Segment ${record.segment}`
          : 'Director take';
    return {
      name: segment,
      searchTitles: [live?.title, saved?.title || record.recorded_segment?.title].filter(Boolean).join(' '),
      order: removed ? Infinity : (order ?? Infinity),
      group: saved?.uid || live?.uid || record.segment || record.take,
      current: live?.take?.path === item.path,
      short: record.take.slice(0, 8),
    };
  };
}
