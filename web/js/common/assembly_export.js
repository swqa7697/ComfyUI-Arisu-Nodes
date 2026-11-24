// Export for Assemble Video: one job on ComfyUI's queue, holding only the assembly node and what feeds it.
//
// The one-shot request ID exists only in the submitted copy of the prompt, so an ordinary Run and a
// saved workflow never write a film. The pending receipt stays with the workflow until the job is
// seen to end, which lets a reload recognise the same export instead of starting another.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { promptNodeId } from './prompt_paths.js';
import { resourceId } from './shared.js';

const TYPE = 'ArisuAssembleVideo';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const active = new WeakMap();
const delay = () => new Promise((resolve) => setTimeout(resolve, 1200));

function ledger(node) {
  node.properties ??= {};
  const records = node.properties.arisuAssembly;
  if (!records || typeof records !== 'object') node.properties.arisuAssembly = { pending: null, last: null };
  return node.properties.arisuAssembly;
}
function changed(node) {
  node.graph?.change?.();
  node.setDirtyCanvas?.(true, true);
}

/** The pending and last receipts of `node`, and whether this page is following a job now. */
export function exportState(node) {
  const records = node.properties?.arisuAssembly;
  return { pending: records?.pending ?? null, last: records?.last ?? null, running: active.has(node) };
}

async function request(path, init) {
  const response = await api.fetchApi(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const assembly = Object.values(body.node_errors ?? {}).find((entry) => entry.class_type === TYPE);
    const message = assembly?.errors?.[0]?.details ?? (typeof body.error === 'string' ? body.error : body.error?.message);
    throw Object.assign(new Error(message || `ComfyUI request failed (HTTP ${response.status}).`), { status: response.status });
  }
  return response.json();
}

// ComfyUI answers these two actions with an empty body.
async function act(path, value) {
  const response = await api.fetchApi(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(value),
  });
  if (!response.ok) throw new Error(`ComfyUI request failed (HTTP ${response.status}).`);
}

/** The assembly node and every node its inputs reach: samplers, decoders and other savers stay out of the job. */
function prune(output, target) {
  const kept = {};
  const visit = (id) => {
    if (kept[id] || !output[id]) return;
    kept[id] = structuredClone(output[id]);
    for (const value of Object.values(output[id].inputs ?? {})) if (Array.isArray(value) && value.length === 2) visit(String(value[0]));
  };
  visit(target);
  return kept;
}

async function history(id) {
  return (await request(`/history/${id}`))[id];
}

async function finish(pending, owner) {
  const job = pending.job ?? pending.id;
  if (!uuid.test(job) || !uuid.test(pending.id)) throw Object.assign(new Error('Invalid pending export ID.'), { terminal: true });
  for (;;) {
    if (owner.detached) return null;
    let entry = await history(job);
    if (!entry) {
      const queue = await request('/queue');
      if ([...queue.queue_running, ...queue.queue_pending].some((item) => item[1] === job)) {
        await delay();
        continue;
      }
      // It may have moved from the running queue to history during these requests.
      entry = await history(job);
    }
    if (entry?.status?.status_str !== 'success' || !entry.status?.completed) {
      const failure = entry?.status?.messages?.find(([event, detail]) => event === 'execution_error' && detail.node_type === TYPE);
      const reason = failure?.[1].exception_message?.split('\n')[0];
      const message =
        reason || (entry ? 'ComfyUI reported a failed or interrupted export.' : 'The export is absent from the queue and history.');
      throw Object.assign(new Error(message), { terminal: true, stopped: owner.stopped });
    }
    const output = entry.outputs?.[pending.node];
    const receipt = output?.arisu_export?.[0];
    // An ordinary Run of the same node answers without a request; only this job's own film counts.
    if (receipt?.request !== pending.id) throw Object.assign(new Error('The run finished without this export.'), { terminal: true });
    const { request: id, path, name, counter, frames, samples, duration } = receipt;
    return { request: id, path, name, counter, frames, samples, duration };
  }
}

async function settle(node, owner, onProgress) {
  const records = ledger(node);
  const job = records.pending.job ?? records.pending.id;
  const progress = ({ detail }) => {
    if (detail?.prompt_id === job && detail.max > 0) onProgress(`Exporting ${Math.round((100 * detail.value) / detail.max)}%`);
  };
  api.addEventListener('progress', progress);
  try {
    const receipt = await finish(records.pending, owner);
    if (!receipt || owner.detached) return null;
    Object.assign(ledger(node), { pending: null, last: receipt });
    changed(node);
    return receipt;
  } catch (error) {
    if (error.terminal && !owner.detached) {
      ledger(node).pending = null;
      changed(node);
    }
    throw error;
  } finally {
    api.removeEventListener('progress', progress);
  }
}

async function follow(node, onProgress, submit) {
  if (active.has(node)) throw new Error('An export is already running.');
  const owner = { stopped: false, detached: false };
  active.set(node, owner);
  try {
    await submit?.(owner);
    return await settle(node, owner, onProgress);
  } finally {
    if (active.get(node) === owner) active.delete(node);
  }
}

/** Submit the export and follow it to its receipt `{ request, path, name, counter, frames, samples, duration }`. */
export function runExport(node, onProgress = () => {}) {
  return follow(node, onProgress, async () => {
    const prompt = await app.graphToPrompt();
    const target = promptNodeId(prompt.output, node, TYPE);
    const graph = prune(prompt.output, target);
    const id = resourceId();
    graph[target].inputs.export_request = id;
    const records = ledger(node);
    records.pending = { id, node: target };
    changed(node);
    onProgress('Export queued');
    try {
      const response = await request('/prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: graph, prompt_id: id, client_id: api.clientId, partial_execution_targets: [target] }),
      });
      if (response.prompt_id && uuid.test(response.prompt_id) && response.prompt_id !== id) {
        // Older servers mint their own prompt IDs. The film still records our request.
        records.pending.job = response.prompt_id;
        changed(node);
      }
    } catch (error) {
      if (error.status >= 400 && error.status < 500) {
        records.pending = null;
        changed(node);
      }
      throw error;
    }
  });
}

/** Follow an export that was pending when the workflow was saved; null when there is none or it is already followed. */
export function recoverExport(node, onProgress = () => {}) {
  if (!node.properties?.arisuAssembly?.pending || active.has(node)) return Promise.resolve(null);
  return follow(node, onProgress);
}

/** Ask ComfyUI to drop the queued job or interrupt the running one; the follower then reports the stop. */
export async function stopExport(node) {
  const pending = node.properties?.arisuAssembly?.pending;
  if (!pending) return;
  const job = pending.job ?? pending.id;
  const owner = active.get(node);
  if (owner) owner.stopped = true;
  const queue = await request('/queue');
  if (queue.queue_pending.some((item) => item[1] === job)) await act('/queue', { delete: [job] });
  else if (queue.queue_running.some((item) => item[1] === job)) await act('/interrupt', { prompt_id: job });
}

/** Stop following without touching the job: the node was removed or its graph is being replaced. */
export function detachExport(node) {
  const owner = active.get(node);
  if (owner) owner.detached = true;
  active.delete(node);
}
