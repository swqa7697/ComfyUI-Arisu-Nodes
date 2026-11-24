// Small helpers shared by both node families. No extension is registered here.
import { app } from '../../../../scripts/app.js';

export function resourceId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // randomUUID requires a secure context; getRandomValues also works over HTTP.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function moveItem(list, index, offset) {
  const target = index + offset;
  if (index >= 0 && target >= 0 && target < list.length) list.splice(target, 0, ...list.splice(index, 1));
}

/** Every node of the open workflow, subgraph definitions included, each graph visited once. */
export function allNodes(graph = app.rootGraph ?? app.graph, visited = new Set()) {
  if (!graph || visited.has(graph)) return [];
  visited.add(graph);
  return [...(graph.nodes ?? graph._nodes ?? []), ...[...(graph.subgraphs?.values() ?? [])].flatMap((child) => allNodes(child, visited))];
}
