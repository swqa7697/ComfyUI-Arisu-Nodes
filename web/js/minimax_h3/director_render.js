// Each successful take has its own output directory. The next segment consumes that exact latent.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { joinPath, resolveString } from '../common/prompt_paths.js';
import { resourceId } from '../common/shared.js';
import { readDocument, timing } from './director_document.js';
import { executionNodes, executionTarget } from './settings_broadcast.js';

const DIRECTOR = 'ArisuMiniMaxH3DirectorWorkbench';
const ARISU_SAVER = 'ArisuSaveVideoSegment';
const SAVERS = ['SaveVideo', ARISU_SAVER];
const LEGACY = 'arisu_director';
const active = new WeakMap();
// Per node: take id -> the first artifact found missing ('video' or 'latent').
const missingTakes = new WeakMap();
const saverChoices = new WeakMap();
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
  const missing = missingTakes.get(node)?.get(take.id);
  if (missing === 'video') return 'Output unavailable';
  if (
    doc &&
    !currentTake(
      node,
      doc,
      doc.segments.findIndex((segment) => segment.id === segmentId),
    )
  )
    return 'Needs rerender';
  // The footage still plays and assembles; only the next continuation needs this latent.
  return missing === 'latent' ? 'Latent removed' : 'Rendered';
}

/** Savers wired to Create Video when Director needs a choice; empty when the saver is unambiguous. */
export function saverCandidates(node) {
  return saverChoices.get(node) ?? [];
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

/**
 * Where a receipt's files live: `arisu_director/<take>` or `<project>/director/<take>`.
 *
 * The directory comes from the saved outputs, never from a predicted prefix, so an
 * expanded placeholder or a later video counter still resolves. Returns null for a
 * receipt whose files do not belong to its take.
 */
export function takeLocation(take) {
  const video = take?.video;
  if (!uuid.test(take?.id ?? '') || video?.type !== 'output' || !/^clip_\d{5,}_\.(mp4|mov|webm|mkv)$/.test(video.filename ?? ''))
    return null;
  const dir = String(video.subfolder ?? '');
  const suffix = `/director/${take.id}`;
  let project;
  if (dir === `${LEGACY}/${take.id}`) project = '';
  else if (dir.endsWith(suffix) && dir.length > suffix.length) project = dir.slice(0, -suffix.length);
  else return null;
  if (take.latent && (take.latent.subfolder !== dir || take.latent.filename !== 'clip_00001.safetensors')) return null;
  return { project, dir };
}

async function inspect(take, location = takeLocation(take)) {
  if (!location) throw new Error('Saved outputs do not belong to this take.');
  const query = new URLSearchParams({ take: take.id, video: take.video.filename });
  if (location.project) query.set('project', location.project);
  return request(`/arisu/resources/director-take?${query}`);
}

/** The video alone makes a take usable for assembly; a continuation also needs its latent. */
async function availability(take) {
  const result = await inspect(take);
  const video = Boolean(result.video);
  return { video, latent: video && Boolean(take.latent && result.latent) };
}

async function available(take) {
  return (await availability(take)).latent;
}

/** Probe saved receipts when a trusted workflow reopens; never infer completion from a filename. */
export async function refreshRenderTakes(node, doc, onChange = () => {}) {
  const missing = new Map();
  missingTakes.set(node, missing);
  for (const segment of doc.segments) {
    const take = renderTake(node, segment.id);
    if (take) {
      const found = await availability(take);
      if (!found.latent) missing.set(take.id, found.video ? 'latent' : 'video');
    }
    if (missingTakes.get(node) !== missing) return;
  }
  onChange();
}

async function verifiedPredecessor(node, doc, segmentId) {
  const index = doc.segments.findIndex((segment) => segment.id === segmentId);
  if (index <= 0 || doc.segments[index].transition !== 'continuation') throw new Error('Select a continuation with a predecessor.');
  const previous = currentTake(node, doc, index - 1);
  if (!previous || !(await available(previous)))
    throw new Error(
      `Render predecessor “${doc.segments[index - 1].id}” before “${segmentId}”. Its current take or saved latent is unavailable.`,
    );
  return `${previous.latent.subfolder}/${previous.latent.filename}`;
}

/** A revision uses stills from the preceding delivered video, including after its latent has been removed. */
export async function revisionFootage(node, doc, index) {
  if (index <= 0 || doc.segments[index]?.transition !== 'continuation') return null;
  const previous = currentTake(node, doc, index - 1);
  const location = takeLocation(previous);
  if (!location) return null;
  const receipt = {
    project: location.project,
    take: previous.id,
    video: previous.video.filename,
    segment: previous.segment,
  };
  try {
    return (await inspect(previous, location)).video ? receipt : null;
  } catch {
    // Revision can still use the film plan when the saved video is unavailable.
    return null;
  }
}

function chain(graph, director, node) {
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
  const savers = Object.keys(graph).filter((id) => {
    const link = graph[id].inputs?.video;
    return SAVERS.includes(graph[id].class_type) && Array.isArray(link) && String(link[0]) === video && link[1] === 0;
  });
  saverChoices.set(node, savers.length > 1 ? savers.map((id) => ({ id, type: graph[id].class_type })) : []);
  if (!savers.length) throw new Error('Connect Create Video to Save Video or Save Video Segment.');
  const saveVideo = savers.length > 1 ? String(node.properties?.directorSaver ?? '') : savers[0];
  if (!savers.includes(saveVideo)) throw new Error('Several video savers follow Create Video. Choose the saver for Director renders.');
  wire(video, 'images', trim, 0);
  wire(video, 'audio', trim, 1);
  const samples = graph[saveLatent].inputs.latent;
  if (!Array.isArray(samples)) throw new Error('Connect the sampled latent to Motion Context Save Latent.');
  // Save and decode the same final latent, including any join correction that the switch selected.
  for (const [type, name] of [
    ['VAEDecode', 'images'],
    ['VAEDecodeAudio', 'audio'],
  ]) {
    const decode = unique(type);
    wire(trim, name, decode, 0);
    wire(decode, 'samples', String(samples[0]), samples[1]);
  }
  const checked = new Map();
  function checkSamplePath(link) {
    const id = Array.isArray(link) ? String(link[0]) : '';
    const item = graph[id];
    if (!item) throw new Error('Connect the sampled latent through every selected Director render branch.');
    const { class_type: type, inputs } = item;
    if (type !== 'ComfySwitchNode' && type !== 'MiniMaxH3JoinMatch') {
      if (type === 'ArisuMiniMaxH3SelfLiftProgressiveSampler') wire(id, 'conditioning', motion, 0);
      else if ('positive' in inputs || 'latent_image' in inputs) wire(id, 'positive', motion, 0);
      else throw new Error(`Cannot trace the Director render latent through ${type} (#${id}).`);
      wire(id, 'latent_image', hybrid, 1);
      return;
    }
    if (link[1] !== 0) throw new Error(`Use the latent output of ${type} (#${id}).`);
    if (checked.get(id) === false) throw new Error('The Director render latent contains a connection cycle.');
    if (checked.has(id)) return;
    checked.set(id, false);
    if (type === 'MiniMaxH3JoinMatch') checkSamplePath(inputs.samples);
    else if (typeof inputs.switch === 'boolean') checkSamplePath(inputs.switch ? inputs.on_true : inputs.on_false);
    else {
      // A linked switch is decided during execution. Either branch must produce a Director take.
      checkSamplePath(inputs.on_false);
      checkSamplePath(inputs.on_true);
    }
    checked.set(id, true);
  }
  checkSamplePath(samples);
  return { motion, loader, saveLatent, saveVideo, saver: graph[saveVideo].class_type };
}

/** The project of an Arisu saver, read before the run; the stock saver and a blank project keep the legacy layout. */
function projectOf(graph, ids) {
  if (ids.saver !== ARISU_SAVER) return '';
  const project = resolveString(graph, graph[ids.saveVideo].inputs.project_prefix);
  if (project.unresolved)
    throw new Error('Director cannot read the project of Save Video Segment before the run. Type it there or connect Path Builder.');
  return joinPath([project.value]);
}

function configureMotion(graph, ids, segment, previous, base = LEGACY) {
  Object.assign(graph[ids.loader].inputs, {
    latent_path: previous ?? base,
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
      const ids = chain(prompt.output, String(id), node);
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
    const files = await inspect(take);
    if (!files.latent || !files.video)
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

function workflowNode(workflow, executionId) {
  let nodes = workflow?.nodes;
  let found;
  for (const id of String(executionId).split(':')) {
    found = nodes?.find((node) => String(node.id) === id);
    nodes = workflow?.definitions?.subgraphs?.find((graph) => graph.id === found?.type)?.nodes;
  }
  return found;
}

function setWorkflowWidget(node, name, index, value) {
  const values = node?.widgets_values;
  if (Array.isArray(values)) values[index] = value;
  else if (values) values[name] = value;
  if (node?.widgets_values_named) node.widgets_values_named[name] = value;
}

// Director posts its own prompt ID for lost-response recovery. Run rgthree's seed queue handler
// on the captured controls so each submitted take gets its seed and the live Last Seed button.
function captureSeedHandlers({ output, workflow }) {
  const handlers = [];
  const shared = new Map();
  for (const { id, node } of executionNodes()) {
    const entry = output[id];
    if (entry?.class_type !== 'Seed (rgthree)' || typeof entry.inputs.seed !== 'number' || typeof node.handleApiHijacking !== 'function')
      continue;
    const metadata = workflowNode(workflow, id);
    const index = node.widgets.indexOf(node.seedWidget);
    if (!metadata?.widgets_values || index < 0) continue;
    // Instances of a subgraph can share one serialized seed widget. Draw once for that control.
    const first = shared.get(metadata);
    if (first?.mode === entry.inputs.seed) {
      handlers.push(() => {
        entry.inputs.seed = first.inputs.seed;
      });
      continue;
    }
    shared.set(metadata, { mode: entry.inputs.seed, inputs: entry.inputs });
    const seedWidget = { name: node.seedWidget.name, value: entry.inputs.seed, options: { ...node.seedWidget.options } };
    const captured = {
      __proto__: node,
      id,
      mode: node.mode,
      properties: { ...node.properties },
      widgets: node.widgets.map((widget, i) => (i === index ? seedWidget : widget)),
      seedWidget,
      lastSeed: node.lastSeed,
    };
    handlers.push(() => {
      captured.handleApiHijacking({ detail: { workflow, output } });
      setWorkflowWidget(metadata, 'seed', index, entry.inputs.seed);
      node.lastSeed = captured.lastSeed;
    });
  }
  return handlers;
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
    // Object-valued widgets can be reactive proxies. Snapshot both representations together.
    const serialized = await app.graphToPrompt();
    const prompt = JSON.parse(JSON.stringify({ output: serialized.output, workflow: serialized.workflow }));
    const { output: graph, workflow } = prompt;
    if (graph[director]?.class_type !== DIRECTOR) throw new Error('The selected Director node is absent from this workflow.');
    const directorMetadata = workflowNode(workflow, director);
    const seedHandlers = captureSeedHandlers(prompt);
    const ids = chain(graph, String(director), node);
    const project = projectOf(graph, ids);
    for (const [index, segment] of doc.segments.entries()) {
      if (index < start || (!remaining && index !== start)) continue;
      if (owner.stopped) break;
      const previous = segment.transition === 'continuation' ? await verifiedPredecessor(node, doc, segment.id) : null;
      const prior = currentTake(node, doc, index);
      if (prior && (remaining || prior.id === recovered?.id) && (await available(prior))) continue;
      const id = resourceId();
      const prefix = joinPath([project ? `${project}/director` : LEGACY, id, 'clip']);
      const predecessor = previous ? renderTake(node, doc.segments[index - 1].id).id : null;
      const snapshotRevision = revision(doc, segment);
      if (snapshotRevision === null) throw new Error(`Segment ${segment.id} needs a generation length within the film limits.`);
      graph[director].inputs.film_json = JSON.stringify({ ...doc, selected: segment.id });
      configureMotion(graph, ids, segment, previous, project ? `${project}/director` : LEGACY);
      if (ids.saver === ARISU_SAVER)
        graph[ids.saveVideo].inputs.take_context = JSON.stringify({
          take: id,
          segment: segment.id,
          predecessor,
          transition: segment.transition === 'continuation' ? 'continuation' : 'cut',
        });
      else graph[ids.saveVideo].inputs.filename_prefix = prefix;
      Object.assign(graph[ids.saveLatent].inputs, { filename_prefix: prefix, clip_index: 1 });
      if (owner.stopped) break;
      setWorkflowWidget(directorMetadata, 'film_json', 0, graph[director].inputs.film_json);
      for (const prepareSeed of seedHandlers) prepareSeed();
      records.pending = {
        id,
        segment: segment.id,
        revision: snapshotRevision,
        predecessor,
        saveVideo: ids.saveVideo,
        saveLatent: ids.saveLatent,
        saver: ids.saver,
        project,
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
            extra_data: { extra_pnginfo: { workflow } },
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
