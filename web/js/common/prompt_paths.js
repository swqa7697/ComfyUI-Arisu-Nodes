// Read a text input from an API prompt without running it. The server resolves the same input again at execution.

const TRIM = /^[ \t\n\r\v\f/]+|[ \t\n\r\v\f/]+$/g;
const PATH_BUILDER = 'ArisuPathBuilder';
const PRIMITIVES = ['PrimitiveString', 'PrimitiveStringMultiline'];
const UNRESOLVED = Object.freeze({ unresolved: true });

/** Path Builder's join: trimmed pieces, blanks skipped, always '/'. */
export function joinPath(segments) {
  return segments
    .map((segment) => String(segment ?? '').replace(TRIM, ''))
    .filter(Boolean)
    .join('/');
}

/**
 * Follow `value` through Path Builder, string primitives and String Concatenate.
 *
 * Returns `{ value }` for text known before execution and `{ unresolved: true }` for
 * anything computed by another node.
 */
export function resolveString(output, value, seen = new Set()) {
  if (value == null) return { value: '' };
  if (typeof value === 'string') return { value };
  if (!Array.isArray(value)) return UNRESOLVED;
  const id = String(value[0]);
  const node = output?.[id];
  if (!node || seen.has(id)) return UNRESOLVED;
  const inputs = node.inputs ?? {};
  const read = (name) => resolveString(output, inputs[name], new Set(seen).add(id));
  const all = (names) => {
    const parts = names.map(read);
    return parts.some((part) => part.unresolved) ? null : parts.map((part) => part.value);
  };
  if (node.class_type === PATH_BUILDER) {
    const index = (name) => Number(name.slice('segment_'.length));
    const names = Object.keys(inputs)
      .filter((name) => /^segment_\d+$/.test(name))
      .sort((a, b) => index(a) - index(b));
    const parts = all(names);
    return parts ? { value: joinPath(parts) } : UNRESOLVED;
  }
  if (PRIMITIVES.includes(node.class_type)) return read('value');
  if (node.class_type === 'StringConcatenate') {
    const parts = all(['string_a', 'string_b', 'delimiter']);
    return parts ? { value: [parts[0], parts[1]].join(parts[2]) } : UNRESOLVED;
  }
  return UNRESOLVED;
}

/** The prompt id of `node`: its own id at the root, or the one subgraph instance that ends in it. */
export function promptNodeId(output, node, type) {
  const own = String(node.id);
  const matches = Object.keys(output ?? {}).filter((id) => output[id]?.class_type === type && (id === own || id.endsWith(`:${own}`)));
  if (matches.length !== 1)
    throw new Error(matches.length ? `${type} is shared by several subgraph instances.` : `${type} is absent from this workflow.`);
  return matches[0];
}
