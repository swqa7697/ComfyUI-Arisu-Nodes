// The /arisu/video routes behind Assemble Video. The server checks every location; these wrappers only shape requests.
import { api } from '../../../../scripts/api.js';

const ROUTE = '/arisu/video';
const DESCRIBE_BATCH = 64;
const CACHE_LIMIT = 2048;
// Descriptions of files as they are on disk, by location. Undo rebuilds node objects, so this cannot live on a node.
const described = new Map();
const key = (root, path) => `${root}|${path}`;

async function request(path, init = {}) {
  const response = await api.fetchApi(`${ROUTE}${path}`, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof data.error === 'string' ? data.error : `Video request failed (HTTP ${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function post(path, value, signal) {
  return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value), signal });
}

function remember(description) {
  described.delete(key(description.root, description.path));
  described.set(key(description.root, description.path), description);
  for (const stale of described.keys()) {
    if (described.size <= CACHE_LIMIT) break;
    described.delete(stale);
  }
}

/** The cached description of a location, or undefined before it was described. */
export function known(root, path) {
  return described.get(key(root, path));
}

export function forget(root, path) {
  described.delete(key(root, path));
}

/** Published takes of a project; each one is cached as the current description of its file. */
export async function listTakes(project, legacy = false, signal) {
  const query = new URLSearchParams({ project });
  if (legacy) query.set('legacy', '1');
  const data = await request(`/takes?${query}`, { signal });
  for (const take of data.takes) remember(take);
  return data;
}

/** Describe files as they are now, in request order. Revisions are compared by the caller, entry by entry. */
export async function describe(locations, signal) {
  const results = [];
  for (let start = 0; start < locations.length; start += DESCRIBE_BATCH) {
    const entries = locations.slice(start, start + DESCRIBE_BATCH).map(({ root, path }) => ({ root, path }));
    const data = await post('/describe', { entries }, signal);
    data.entries.forEach((description, index) => {
      // A file the route cannot describe still answers for its own location.
      const item = { ...entries[index], ...description };
      remember(item);
      results.push(item);
    });
  }
  return results;
}

export function preflight(body, signal) {
  return post('/preflight', body, signal);
}

/** Request a file list for review, or confirm with the revisions returned by that review. */
export function deletePlan(entries, confirm, signal) {
  return post('/delete', { entries: entries.map(({ root, path, revision }) => ({ root, path, revision })), confirm }, signal);
}

export const joinPreview = {
  create: (body, signal) => post('/join-preview', body, signal),
  status: (id, signal) => request(`/join-preview/${encodeURIComponent(id)}`, { signal }),
  viewUrl: (id, variant) => api.apiURL(`${ROUTE}/join-preview/${encodeURIComponent(id)}/view?${new URLSearchParams({ variant })}`),
  remove: (id) => request(`/join-preview/${encodeURIComponent(id)}`, { method: 'DELETE', keepalive: true }),
};

/** The original file, streamed by the shared media route. */
export function mediaUrl(root, path) {
  return api.apiURL(`/arisu/resources/view?${new URLSearchParams({ root, path })}`);
}
