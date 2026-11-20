// Each successful take has its own output directory. The next segment consumes that exact latent.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { readDocument, timing } from './director_document.js';
import { resourceId } from './media_selection.js';
import { executionTarget } from './settings_broadcast.js';

const DIRECTOR = 'ArisuMiniMaxH3DirectorWorkbench';
const active = new WeakMap();
const missingTakes = new WeakMap();
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const delay = () => new Promise((resolve) => setTimeout(resolve, 1200));

function ledger(node) {
  node.properties ??= {};
  node.properties.directorRenders ??= { takes: [], pending: null };
  return node.properties.directorRenders;
}
function changed(node) {
  node.graph?.change?.();
  node.setDirtyCanvas?.(true, true);
}
export function renderTake(node, segmentId) {
  return node.properties?.directorRenders?.takes?.find((take) => take.segment === segmentId);
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonical(value[key])]),
    );
  return value;
}

function revision(doc, segment) {
  const { aspect_ratio, megapixels, frame_picture_tags } = doc.film;
  const frames = timing(doc.film, segment.seconds);
  if (frames == null || segment.seconds < doc.film.min_seconds || segment.seconds > doc.film.max_seconds) return null;
  const sources = new Map(doc.assets.map((asset) => [asset.id, asset]));
  const bindings = segment.bindings.map((binding) => {
    const source = sources.get(binding.asset_id);
    if (!source) return [binding.asset_id, null];
    const { id, kind, root, path, revision, muted, crop, crop_basis_ratio, clip, include_audio } = { ...source, ...binding };
    return [binding.role, id, kind, root, path, revision, muted, crop, crop_basis_ratio, clip, include_audio];
  });
  return JSON.stringify(
    canonical([segment.prompt, frames, segment.transition, segment.overlap_frames, bindings, aspect_ratio, megapixels, frame_picture_tags]),
  );
}

function currentTake(node, doc, index) {
  if (index < 0 || index >= doc.segments.length) return null;
  let take = null;
  let first = index;
  while (first > 0 && doc.segments[first].transition === 'continuation') first--;
  for (let i = first; i <= index; i++) {
    const segment = doc.segments[i];
    const candidate = renderTake(node, segment.id);
    if (!candidate || candidate.revision !== revision(doc, segment) || candidate.predecessor !== (take?.id ?? null)) return null;
    take = candidate;
  }
  return take;
}

export function renderStatus(node, segmentId, doc) {
  if (node.properties?.directorRenders?.pending?.segment === segmentId) return 'Awaiting render result';
  const take = renderTake(node, segmentId);
  if (!take) return 'Pending';
  if (missingTakes.get(node)?.has(take.id)) return 'Output unavailable';
  if (
    doc &&
    !currentTake(
      node,
      doc,
      doc.segments.findIndex((segment) => segment.id === segmentId),
    )
  )
    return 'Needs rerender';
  return 'Rendered';
}

async function request(path, init) {
  const response = await api.fetchApi(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const director = Object.values(body.node_errors ?? {}).find((entry) => entry.class_type === DIRECTOR);
    const validation = director?.errors?.find((reason) => reason.type === 'custom_validation_failed');
    const message = validation?.details ?? (typeof body.error === 'string' ? body.error : body.error?.message);
    const error = new Error(message || `ComfyUI request failed (HTTP ${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function inspect(take) {
  if (!uuid.test(take.id) || !/^clip_\d{5,}_\.(mp4|mov|webm|mkv)$/.test(take.video?.filename)) throw new Error('Invalid saved take.');
  const dir = `arisu_director/${take.id}`;
  if (take.video.subfolder !== dir || take.latent?.subfolder !== dir || take.latent?.filename !== 'clip_00001.safetensors')
    throw new Error('Saved outputs do not belong to this take.');
  return request(`/arisu/resources/director-take?take=${take.id}&video=${take.video.filename}`);
}

async function available(take) {
  const result = await inspect(take);
  return Boolean(result.latent && result.video && result.latent === take.files?.latent && result.video === take.files?.video);
}

/** Probe saved receipts when a trusted workflow reopens; never infer completion from a filename. */
export async function refreshRenderTakes(node, doc, onChange = () => {}) {
  const missing = new Set();
  missingTakes.set(node, missing);
  for (const segment of doc.segments) {
    const take = renderTake(node, segment.id);
    if (take && !(await available(take))) missing.add(take.id);
    if (missingTakes.get(node) !== missing) return;
  }
  onChange();
}

export async function verifiedPredecessor(node, doc, segmentId) {
  const index = doc.segments.findIndex((segment) => segment.id === segmentId);
  if (index <= 0 || doc.segments[index].transition !== 'continuation') throw new Error('Select a continuation with a predecessor.');
  const previous = currentTake(node, doc, index - 1);
  if (!previous || !(await available(previous)))
    throw new Error(
      `Render predecessor “${doc.segments[index - 1].id}” before “${segmentId}”. Its current take is missing or has changed.`,
    );
  return `${previous.latent.subfolder}/${previous.latent.filename}`;
}

function chain(graph, director) {
  const unique = (type) => {
    const matches = Object.entries(graph).filter(([, item]) => item.class_type === type);
    if (matches.length !== 1) throw new Error(`Use the Director workflow with one ${type}.`);
    return matches[0][0];
  };
  const hybrid = unique('ArisuMiniMaxH3HybridToVideo');
  const motion = unique('MiniMaxH3MotionContext');
  const loader = unique('MiniMaxH3MotionContextLoadLatent');
  const saveLatent = unique('MiniMaxH3MotionContextSaveLatent');
  const trim = unique('MiniMaxH3MotionContextTrim');
  const saveVideo = unique('SaveVideo');
  function wire(target, input, source, slot) {
    const link = graph[target]?.inputs?.[input];
    if (!Array.isArray(link) || String(link[0]) !== source || link[1] !== slot)
      throw new Error(`Restore the Director workflow connection to ${graph[target]?.class_type}.${input}.`);
  }
  for (const [slot, name] of ['prompt', 'video_settings', 'resources'].entries()) wire(hybrid, name, director, slot);
  wire(motion, 'context_latent', loader, 0);
  wire(motion, 'conditioning', hybrid, 0);
  wire(motion, 'latent', hybrid, 1);
  wire(trim, 'trim_frames', motion, 1);
  const video = unique('CreateVideo');
  wire(saveVideo, 'video', video, 0);
  wire(video, 'images', trim, 0);
  wire(video, 'audio', trim, 1);
  const samples = graph[saveLatent].inputs.latent;
  if (!Array.isArray(samples)) throw new Error('Connect the sampled latent to Motion Context Save Latent.');
  const sampler = String(samples[0]);
  wire(sampler, 'positive', motion, 0);
  wire(sampler, 'latent_image', hybrid, 1);
  for (const [type, name] of [
    ['VAEDecode', 'images'],
    ['VAEDecodeAudio', 'audio'],
  ]) {
    const decode = unique(type);
    wire(trim, name, decode, 0);
    wire(decode, 'samples', sampler, samples[1]);
  }
  return { motion, loader, saveLatent, saveVideo };
}

function configureMotion(graph, ids, segment, previous) {
  Object.assign(graph[ids.loader].inputs, {
    latent_path: previous ?? 'arisu_director',
    clip_index: previous ? 1 : 0,
    folder: 'output',
    stock_format: false,
  });
  graph[ids.motion].inputs.context_length = String(segment.overlap_frames || 22);
}

/** Ordinary Run uses the same verified join as the Director buttons in the dedicated template. */
export function installDirectorQueue(views) {
  const queue = api.queuePrompt;
  api.queuePrompt = async function (index, prompt, ...rest) {
    for (const node of views) {
      if (!node.properties?.arisuDirectorTemplate || !prompt?.output) continue;
      const id = executionTarget(node)?.id;
      const input = prompt.output[id];
      if (input?.class_type !== DIRECTOR) continue;
      // A Director copied out of the template still works as an ordinary three-output node.
      const entries = Object.values(prompt.output);
      if (
        !entries.some((item) => item.class_type === 'MiniMaxH3MotionContext') ||
        !entries.some((item) => item.class_type === 'ArisuMiniMaxH3HybridToVideo' && String(item.inputs.video_settings?.[0]) === String(id))
      )
        continue;
      const doc = readDocument(input.inputs.film_json);
      const segment = doc.segments.find((item) => item.id === doc.selected);
      if (!segment) continue;
      const ids = chain(prompt.output, String(id));
      const previous = segment.transition === 'continuation' ? await verifiedPredecessor(node, doc, segment.id) : null;
      configureMotion(prompt.output, ids, segment, previous);
    }
    return queue.call(this, index, prompt, ...rest);
  };
}

async function history(id) {
  return (await request(`/history/${id}`))[id];
}

async function finish(pending, owner) {
  const job = pending.job ?? pending.id;
  if (!uuid.test(job) || !uuid.test(pending.id)) throw new Error('Invalid pending render ID.');
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
      const failure = entry?.status?.messages?.find(([event, detail]) => event === 'execution_error' && detail.node_type === DIRECTOR);
      const reason = failure?.[1].exception_message?.split('\n')[0];
      const message =
        reason || (entry ? 'ComfyUI reported a failed or interrupted render.' : 'The render is absent from the queue and history.');
      throw Object.assign(new Error(`${message} Retry segment “${pending.segment}”.`), { terminal: true });
    }
    const video = entry.outputs?.[pending.saveVideo]?.images?.[0];
    const latent = entry.outputs?.[pending.saveLatent]?.latents?.[0];
    if (video?.type !== 'output' || latent?.type !== 'output')
      throw Object.assign(new Error('The render finished without both saved outputs.'), { terminal: true });
    const take = { ...pending, video, latent };
    take.files = await inspect(take);
    if (!take.files.latent || !take.files.video)
      throw Object.assign(new Error('The completed take is missing files. Retry this segment.'), { terminal: true });
    return take;
  }
}

export function stopRender(node, detach = false) {
  const owner = active.get(node);
  if (owner) {
    owner.stopped = true;
    owner.detached = detach;
  }
}

export async function renderSegments(node, document, remaining, onProgress = () => {}) {
  if (active.has(node)) throw new Error('A render sequence is already running.');
  const owner = { stopped: false, detached: false };
  active.set(node, owner);
  const doc = structuredClone(document);
  const records = ledger(node);
  const start = doc.segments.findIndex((segment) => segment.id === doc.selected);
  const recover = async () => {
    let take;
    try {
      take = await finish(records.pending, owner);
    } catch (error) {
      if (error.terminal) {
        records.pending = null;
        changed(node);
      }
      throw error;
    }
    if (take && !owner.detached) {
      records.takes = records.takes.filter((prior) => prior.segment !== take.segment).concat(take);
      records.pending = null;
      changed(node);
      onProgress(`Rendered ${take.segment}`);
    }
    return take;
  };
  try {
    if (start < 0) throw new Error('Select an applied segment first.');
    let recovered = null;
    if (records.pending) {
      onProgress(`Checking pending render for ${records.pending.segment}`);
      recovered = await recover();
    }
    if (owner.stopped) return;
    const director = executionTarget(node)?.id;
    const prompt = await app.graphToPrompt();
    if (prompt.output[director]?.class_type !== DIRECTOR) throw new Error('The selected Director node is absent from this workflow.');
    const ids = chain(prompt.output, String(director));
    for (const [index, segment] of doc.segments.entries()) {
      if (index < start || (!remaining && index !== start)) continue;
      if (owner.stopped) break;
      const previous = segment.transition === 'continuation' ? await verifiedPredecessor(node, doc, segment.id) : null;
      const prior = currentTake(node, doc, index);
      if (prior && (remaining || prior.id === recovered?.id) && (await available(prior))) continue;
      const id = resourceId();
      const prefix = `arisu_director/${id}/clip`;
      const snapshotRevision = revision(doc, segment);
      if (snapshotRevision === null) throw new Error(`Segment ${segment.id} needs a generation length within the film limits.`);
      const graph = structuredClone(prompt.output);
      graph[director].inputs.film_json = JSON.stringify({ ...doc, selected: segment.id });
      configureMotion(graph, ids, segment, previous);
      graph[ids.saveVideo].inputs.filename_prefix = prefix;
      Object.assign(graph[ids.saveLatent].inputs, { filename_prefix: prefix, clip_index: 1 });
      if (owner.stopped) break;
      records.pending = {
        id,
        segment: segment.id,
        revision: snapshotRevision,
        predecessor: previous ? renderTake(node, doc.segments[index - 1].id).id : null,
        saveVideo: ids.saveVideo,
        saveLatent: ids.saveLatent,
      };
      changed(node);
      onProgress(`Rendering ${segment.id}`);
      try {
        const response = await request('/prompt', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: graph,
            prompt_id: id,
            client_id: api.clientId,
            partial_execution_targets: [ids.saveVideo, ids.saveLatent],
          }),
        });
        if (response.prompt_id && uuid.test(response.prompt_id) && response.prompt_id !== id) {
          // Older servers mint their own prompt IDs. The artifact directory still belongs to our take.
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
      await recover();
    }
    if (owner.stopped && !owner.detached) onProgress('Stopped after the current segment.');
  } finally {
    active.delete(node);
  }
}
