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
