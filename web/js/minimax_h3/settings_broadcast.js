// One coordinator for native settings and resource ownership, including API exports.
import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { installSelectionGuards, registerSelectionOwner } from '../common/selection_context.js';

const STUDIO = 'ArisuMiniMaxH3ResourceStudio';
const SETTINGS_KEYS = {
  ArisuMiniMaxH3VideoSettings: ['width', 'height', 'length'],
  ArisuMiniMaxH3VideoSettingsUpscale: ['width', 'height', 'length', 'target_width', 'target_height'],
};
const HYBRID_WIDGETS = {
  ArisuMiniMaxH3PromptWorkbench: [],
  ArisuMiniMaxH3HybridToVideo: ['width', 'height', 'length'],
  ArisuMiniMaxH3HybridToVideoAdvanced: ['width', 'height', 'length', 'target_width', 'target_height'],
};
const RESOURCE_NAMES = ['first_frame', 'last_frame', 'ref_images', 'ref_videos', 'ref_video_audios', 'ref_audios'];
const ADVERTISE = { settings: 'advertise_settings', resources: 'advertise_resources' };
// The hybrid sockets each category fills: the advertiser's output at queue time, or an explicit wire.
const BUNDLE = { settings: 'video_settings', resources: 'resources' };
const states = new WeakMap();
const pending = new Set();
const promptOwnership = new WeakMap();
let refreshing = false;
let epoch = 0;
function rootGraph() {
  return app.rootGraph ?? app.graph;
}
function allNodes(graph = rootGraph(), visited = new Set()) {
  if (!graph || visited.has(graph)) return [];
  visited.add(graph);
  return [...(graph.nodes ?? graph._nodes ?? []), ...[...(graph.subgraphs?.values() ?? [])].flatMap((child) => allNodes(child, visited))];
}
function toast(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: 'MiniMax H3', detail, life: 8000 });
}
function category(node) {
  return node.type === STUDIO ? 'resources' : node.type in SETTINGS_KEYS ? 'settings' : null;
}
function widget(node, name) {
  return node.widgets?.find((value) => value.name === name);
}
function switchOf(node) {
  return widget(node, ADVERTISE[category(node)]);
}
function on(node) {
  return switchOf(node)?.value === true;
}
function active(node) {
  return node.mode === 0;
}
function source(kind) {
  return (rootGraph()?.nodes ?? rootGraph()?._nodes ?? []).find((node) => category(node) === kind && on(node) && active(node));
}
function group(name) {
  return RESOURCE_NAMES.find((key) => name === key || name.startsWith(`${key}.`));
}
function individual(input) {
  return !!group(input.name);
}
function chain(prototype, name, extra) {
  const original = prototype[name];
  prototype[name] = function () {
    const result = original?.apply(this, arguments);
    if (result === false) return false;
    return extra.apply(this, arguments) === false ? false : result;
  };
}
function transaction(node, action) {
  const graph = node.graph;
  graph?.beforeChange?.();
  try {
    return action();
  } finally {
    if (pending.size) Promise.allSettled([...pending]).then(() => graph?.afterChange?.());
    else graph?.afterChange?.();
  }
}
function exclusive(keep) {
  if (keep.graph !== rootGraph()) return;
  const demoted = (rootGraph()?.nodes ?? []).filter((node) => node !== keep && category(node) === category(keep) && on(node));
  for (const node of demoted) {
    switchOf(node).value = false;
    node.setDirtyCanvas(true, true);
  }
  if (demoted.length) toast('warn', 'Only one source in each category advertises; the latest switch wins.');
}
function inputOf(node, name) {
  return node.inputs?.find((input) => input.name === name);
}
function slotOf(node, name) {
  return node.outputs.findIndex((out) => out.name === name);
}
function advertiserFor(node, kind) {
  return node.graph === rootGraph() ? source(kind) : null;
}
function linkSource(node, input) {
  if (input?.link == null) return null;
  const links = node.graph?.links;
  const link = links?.get?.(input.link) ?? links?.[input.link];
  return link ? String(link.origin_id) : null;
}
function linkOrigin(node, input) {
  const id = linkSource(node, input);
  return id == null ? null : ((node.graph?.nodes ?? node.graph?._nodes ?? []).find((origin) => String(origin.id) === id) ?? null);
}
// The node a consumer takes its settings from: the root-graph advertiser, else the origin of its
// video_settings wire. `undefined` is none; `null` is a wire from a node this graph cannot see.
function settingsSource(node) {
  const advertiser = advertiserFor(node, 'settings');
  if (advertiser || node.type === STUDIO) return advertiser ?? undefined;
  const input = inputOf(node, BUNDLE.settings);
  return input?.link == null ? undefined : linkOrigin(node, input);
}
// The widgets the settings source owns: the keys its bundle carries that the node has; an unseen source owns them all.
function handedKeys(node) {
  const settings = settingsSource(node);
  if (settings === undefined) return [];
  if (node.type === STUDIO) return ['aspect_ratio'];
  const controlled = HYBRID_WIDGETS[node.type] ?? [];
  const carried = settings ? SETTINGS_KEYS[settings.type] : null;
  return carried ? carried.filter((key) => controlled.includes(key)) : controlled;
}
function resourceOwned(node) {
  return !!(node.type in HYBRID_WIDGETS && (advertiserFor(node, 'resources') || inputOf(node, BUNDLE.resources)?.link != null));
}
function schemaSeeds(nodeData) {
  const seeds = [];
  for (const [name, spec] of Object.entries({ ...nodeData.input?.required, ...nodeData.input?.optional })) {
    if (!group(name)) continue;
    const [type, options = {}] = spec;
    if (!name.startsWith('ref_')) {
      seeds.push({ name, type, link: null, ...options });
      continue;
    }
    const template = options.template;
    const source = { ...template?.input?.required, ...template?.input?.optional };
    for (const [key, value] of Object.entries(source)) {
      const slot = `${name}.${template.names?.[0] ?? `${template.prefix ?? key}0`}`;
      seeds.push({ name: slot, type: value[0], link: null, ...value[1] });
    }
  }
  return seeds;
}
function seedSlots(node) {
  const result = [];
  const seen = new Set();
  for (const input of node.inputs ?? []) {
    const key = group(input.name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const slot = { ...input, link: null };
    if (key.startsWith('ref_'))
      slot.name = `${key}.${{ ref_images: 'ref_image', ref_videos: 'ref_video', ref_video_audios: 'ref_video_audio', ref_audios: 'ref_audio' }[key]}_0`;
    result.push(slot);
  }
  return result;
}
function scheduleSockets(node, owned) {
  const state = states.get(node);
  if (!state) return;
  if (state.owned === owned) return;
  state.owned = owned;
  state.generation++;
  const generation = state.generation;
  if (!owned) {
    for (const seed of state.seeds) {
      if (!node.inputs?.some((input) => group(input.name) === group(seed.name)))
        node.addInput(seed.name, seed.type, { ...seed, link: null });
    }
    node.setSize([node.size[0], node.computeSize()[1]]);
    node.setDirtyCanvas(true, true);
    return;
  }
  for (let i = (node.inputs?.length ?? 0) - 1; i >= 0; i--)
    if (individual(node.inputs[i]) && node.inputs[i].link != null) node.disconnectInput(i);
  const tick = () =>
    new Promise((resolve) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(resolve) : setTimeout(resolve, 0)));
  const graph = node.graph;
  const root = rootGraph();
  graph?.beforeChange?.();
  const task = (async () => {
    await tick();
    await tick();
    if (rootGraph() !== root || node.graph !== graph || states.get(node) !== state || generation !== state.generation || !state.owned)
      return;
    for (let i = node.inputs.length - 1; i >= 0; i--) if (individual(node.inputs[i])) node.removeInput(i);
    node.setSize([node.size[0], node.computeSize()[1]]);
    node.setDirtyCanvas(true, true);
  })();
  state.transition = task;
  pending.add(task);
  task.finally(() => {
    graph?.afterChange?.();
    pending.delete(task);
    if (state.transition === task) state.transition = null;
  });
}
// An advertiser owns the socket: greyed, and unwired. Reports whether a wire was dropped.
function ownSocket(node, name, advertiser) {
  const socket = inputOf(node, name);
  if (!socket) return false;
  socket.disabled = !!advertiser;
  socket.color_on = advertiser ? '#777' : undefined;
  socket.color_off = advertiser ? '#777' : undefined;
  if (!advertiser || socket.link == null) return false;
  node.disconnectInput(node.inputs.indexOf(socket));
  return true;
}
function refreshNode(node) {
  // decide before mutating: a disconnect re-enters refresh, which the guard turns away
  const keys = handedKeys(node);
  const controlled = node.type === STUDIO ? ['aspect_ratio'] : (HYBRID_WIDGETS[node.type] ?? []);
  let dropped = false;
  for (const control of node.widgets ?? []) if (controlled.includes(control.name)) control.disabled = keys.includes(control.name);
  for (let i = 0; i < (node.inputs?.length ?? 0); i++)
    if (keys.includes(node.inputs[i].name) && node.inputs[i].link != null) {
      node.disconnectInput(i);
      dropped = true;
    }
  if (node.type === STUDIO) {
    const settings = advertiserFor(node, 'settings');
    // A linked settings ratio is not the source node's stale local widget.
    node.arisuEffectiveAspect = settings
      ? settings.inputs?.some((input) => input.name === 'aspect_ratio' && input.link != null)
        ? null
        : widget(settings, 'aspect_ratio')?.value
      : undefined;
    node.arisuRefreshAspect?.();
  }
  if (node.type in HYBRID_WIDGETS) {
    dropped = ownSocket(node, BUNDLE.resources, advertiserFor(node, 'resources')) || dropped;
    dropped = ownSocket(node, BUNDLE.settings, advertiserFor(node, 'settings')) || dropped;
    scheduleSockets(node, resourceOwned(node));
  }
  if (dropped) toast('info', 'Links into advertised controls were removed.');
  node.arisuRefreshSources?.();
  node.setDirtyCanvas(true, true);
}
function refresh(force) {
  if (refreshing || (app.configuringGraph && force !== true)) return;
  refreshing = true;
  try {
    epoch++;
    for (const node of allNodes()) if (node.type === STUDIO || node.type in HYBRID_WIDGETS) refreshNode(node);
  } finally {
    refreshing = false;
  }
}
function arrive(node) {
  if (!app.configuringGraph && on(node)) exclusive(node);
}
function watchMode(node) {
  const descriptor = Object.getOwnPropertyDescriptor(node, 'mode');
  if (descriptor && !descriptor.configurable) return;
  let value = node.mode;
  Object.defineProperty(node, 'mode', {
    configurable: true,
    enumerable: true,
    get() {
      return descriptor?.get ? descriptor.get.call(this) : value;
    },
    set(next) {
      const previous = this.mode;
      if (descriptor?.set) descriptor.set.call(this, next);
      else value = next;
      if (previous !== next) refresh();
    },
  });
}
async function reconcile() {
  refresh();
  while (pending.size) await Promise.all([...pending]);
}
function ownership() {
  return JSON.stringify(
    allNodes()
      .filter((node) => category(node) || node.type in HYBRID_WIDGETS)
      .map((node) => [
        node.id,
        node.mode,
        on(node),
        node.inputs?.map((input) => [input.name, input.link]),
        node.type === STUDIO ? widget(node, 'aspect_ratio')?.value : undefined,
      ]),
  );
}
function checkCycles(output) {
  const visiting = new Set(),
    done = new Set();
  function visit(id) {
    if (visiting.has(id)) throw new Error('Advertising creates a dependency cycle.');
    if (done.has(id) || !output[id]) return;
    visiting.add(id);
    for (const value of Object.values(output[id].inputs ?? {}))
      if (Array.isArray(value) && value.length === 2 && Number.isInteger(value[1])) visit(String(value[0]));
    visiting.delete(id);
    done.add(id);
  }
  for (const id of Object.keys(output)) visit(id);
}
function executionNodes() {
  const result = [];
  for (const node of rootGraph()?.nodes ?? rootGraph()?._nodes ?? []) {
    if (node.getInnerNodes) {
      for (const dto of node.getInnerNodes(new Map())) result.push({ node: dto.node ?? dto, id: String(dto.id), dto });
    } else result.push({ node, id: String(node.id), dto: null });
  }
  return result;
}
// Point the prompt entry's input at the advertiser's output of the same name.
function bindAdvertised(entry, output, advertiser, name, label) {
  const id = String(advertiser.id);
  if (!output[id]) throw new Error(`The active ${label} source is absent from this prompt.`);
  const slot = slotOf(advertiser, name);
  if (slot < 0) throw new Error(`The ${label} output ${name} is unavailable.`);
  entry.inputs[name] = [id, slot];
}
// An explicit wire must reach a live source in the prompt; the serializer pruning it is an error, not a fallback.
function checkExplicit(node, entry, dto, output, name, label) {
  const explicit = inputOf(node, name);
  if (explicit?.link == null) return false;
  const explicitId = dto ? entry.inputs[name]?.[0] : linkSource(node, explicit);
  const origin = linkOrigin(node, explicit);
  if ((origin && !active(origin)) || !explicitId || !output[explicitId] || !entry.inputs[name])
    throw new Error(`The explicitly connected ${label} source is muted, bypassed, or absent.`);
  return true;
}
// A hybrid's bundle socket in the prompt: the advertiser's output, else its own wire. Reports whether it is fed.
function bindBundle(node, entry, dto, output, name, advertiser, label) {
  if (!advertiser) return checkExplicit(node, entry, dto, output, name, label);
  bindAdvertised(entry, output, advertiser, name, label);
  return true;
}
function inject(output) {
  for (const { node, id: executionId, dto } of executionNodes()) {
    if (!active(node)) continue;
    const entry = output[executionId];
    if (!entry) continue;
    const settings = advertiserFor(node, 'settings');
    if (node.type === STUDIO) {
      // the Studio takes the advertised ratio on its own selector
      if (settings) bindAdvertised(entry, output, settings, 'aspect_ratio', 'settings');
      continue;
    }
    if (!(node.type in HYBRID_WIDGETS)) continue;
    if (bindBundle(node, entry, dto, output, BUNDLE.resources, advertiserFor(node, 'resources'), 'resource'))
      for (const name of Object.keys(entry.inputs)) if (group(name)) delete entry.inputs[name];
    // the individual size and length values stay in the prompt: required inputs the bundle overrides on the backend
    bindBundle(node, entry, dto, output, BUNDLE.settings, settings, 'settings');
  }
  checkCycles(output);
}
// Advertising booleans travel with workflows; keep the shared workflow guards installed.
for (const type of Object.keys(SETTINGS_KEYS)) registerSelectionOwner(type, { fields: [] });
app.registerExtension({
  name: 'Arisu.MiniMaxH3.SettingsBroadcast',
  init: installSelectionGuards,
  setup() {
    const graphToPrompt = app.graphToPrompt;
    if (graphToPrompt)
      app.graphToPrompt = async function (...args) {
        await reconcile();
        const captured = epoch;
        const result = await graphToPrompt.apply(this, args);
        if (captured !== epoch) throw new Error('Resource ownership changed during prompt creation; queue again.');
        inject(result.output);
        promptOwnership.set(result, ownership());
        return result;
      };
    const queuePrompt = api.queuePrompt;
    api.queuePrompt = async function (index, prompt, ...rest) {
      if (prompt?.output) {
        await reconcile();
        if (promptOwnership.has(prompt) && promptOwnership.get(prompt) !== ownership())
          throw new Error('Resource ownership changed; create the prompt again.');
        inject(prompt.output);
      }
      return queuePrompt.call(this, index, prompt, ...rest);
    };
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!(nodeData.name in HYBRID_WIDGETS) && !(nodeData.name in SETTINGS_KEYS) && nodeData.name !== STUDIO) return;
    const canonicalSeeds = schemaSeeds(nodeData);
    chain(nodeType.prototype, 'onAdded', function () {
      if (!states.has(this)) {
        states.set(this, { seeds: canonicalSeeds.length ? canonicalSeeds : seedSlots(this), generation: 0, owned: false });
        watchMode(this);
      }
      if (category(this)) {
        const control = switchOf(this);
        if (control && !control.arisuWrapped) {
          control.arisuWrapped = true;
          const original = control.callback;
          control.callback = (...args) =>
            transaction(this, () => {
              const result = original?.apply(control, args);
              if (control.value) exclusive(this);
              refresh();
              return result;
            });
        }
        if (this.type in SETTINGS_KEYS) {
          const aspect = widget(this, 'aspect_ratio');
          if (aspect && !aspect.arisuWrapped) {
            aspect.arisuWrapped = true;
            const callback = aspect.callback;
            aspect.callback = (...args) => {
              const result = callback?.apply(aspect, args);
              refresh();
              return result;
            };
          }
        }
        arrive(this);
      }
      refresh();
    });
    chain(nodeType.prototype, 'onConfigure', function () {
      const state = states.get(this);
      if (state) {
        state.generation++;
        state.owned = false;
        const seeds = seedSlots(this);
        if (!canonicalSeeds.length && seeds.length) state.seeds = seeds;
      }
      if (category(this) && !app.configuringGraph) arrive(this);
      refresh();
    });
    chain(nodeType.prototype, 'onConnectionsChange', refresh);
    chain(nodeType.prototype, 'onConnectInput', function (index) {
      const input = this.inputs?.[index];
      const owned = this.type in HYBRID_WIDGETS && resourceOwned(this);
      if (
        handedKeys(this).includes(input?.name) ||
        (owned && individual(input)) ||
        (input?.name === BUNDLE.resources && advertiserFor(this, 'resources')) ||
        (input?.name === BUNDLE.settings && advertiserFor(this, 'settings'))
      ) {
        toast('warn', 'This input is owned by the active resource or settings source.');
        return false;
      }
      return true;
    });
    chain(nodeType.prototype, 'onRemoved', function () {
      const state = states.get(this);
      if (state) state.generation++;
      states.delete(this);
      setTimeout(refresh, 0);
    });
  },
  async afterConfigureGraph() {
    const root = rootGraph();
    // loadedGraphNode has restored saved sizes, but canvas draws can expand them
    // while the resource sockets are still waiting for their two-frame cleanup.
    const sizes = allNodes(root)
      .filter((node) => node.type in HYBRID_WIDGETS)
      .map((node) => ({ node, graph: node.graph, size: [...node.size] }));
    for (const kind of ['settings', 'resources']) {
      const first = (rootGraph()?.nodes ?? []).find((node) => category(node) === kind && on(node));
      if (first) exclusive(first);
    }
    refresh(true);
    await Promise.all(
      sizes.map(async ({ node, graph, size }) => {
        const state = states.get(node);
        if (!state?.owned || !state.transition) return;
        const generation = state.generation;
        await state.transition;
        if (rootGraph() !== root || node.graph !== graph || states.get(node) !== state || state.generation !== generation || !state.owned)
          return;
        node.setSize(size);
        node.setDirtyCanvas(true, true);
      }),
    );
  },
});

/** Effective bundle owners for the Workbench's descriptive UI; server validation remains authoritative. */
/** Resolve the same execution instance used by the advertising-aware serializer. */
export function executionTarget(node) {
  const matches = executionNodes().filter((entry) => entry.node === node);
  if (matches.length > 1)
    throw new Error('This Workbench is shared by multiple subgraph instances; use a separate Workbench for each context.');
  return matches[0];
}

/** Capture the preparation graph without awaiting widget serializers or rereading live ownership. */
export function captureWorkbenchPrompt(node) {
  const entries = executionNodes();
  const targets = entries.filter((entry) => entry.node === node);
  if (targets.length !== 1) throw new Error('Use a separate Workbench for each execution context.');
  const output = {};
  for (const { node: source, id, dto } of entries) {
    if (!active(source) || source.isVirtualNode) continue;
    const inputs = {};
    for (const [index, input] of (source.inputs ?? []).entries()) {
      if (input.link == null) continue;
      const links = source.graph?.links;
      const resolved = dto?.resolveInput ? dto.resolveInput(index) : (links?.get?.(input.link) ?? links?.[input.link]);
      if (!resolved) continue;
      if (resolved.widgetInfo) inputs[input.name] = structuredClone(resolved.widgetInfo.value);
      else {
        const origin = entries.find((entry) => entry.id === String(resolved.origin_id))?.node;
        if (origin?.isVirtualNode) inputs[input.name] = structuredClone(origin.widgets?.[0]?.value);
        else inputs[input.name] = [String(resolved.origin_id), Number(resolved.origin_slot)];
      }
    }
    output[id] = { class_type: source.comfyClass ?? source.type, inputs };
  }
  inject(output);
  const captured = {};
  function visit(id) {
    if (captured[id] || !output[id]) return;
    const entry = output[id];
    captured[id] = entry;
    const source = entries.find((item) => item.id === id).node;
    for (const control of source.widgets ?? []) {
      if (!control.name || control.options?.serialize === false || control.serialize === false || control.name in entry.inputs) continue;
      const stored = control.value;
      if (stored === undefined || typeof stored === 'function') continue;
      entry.inputs[control.name] = Array.isArray(stored) ? { __value__: structuredClone(stored) } : structuredClone(stored);
    }
    for (const value of Object.values(entry.inputs)) {
      if (Array.isArray(value) && value.length === 2 && Number.isInteger(value[1])) visit(value[0]);
    }
  }
  visit(targets[0].id);
  return { output: captured, nodeId: targets[0].id };
}

/** Follow explicit bundle ports across reroutes and subgraph boundaries for UI metadata. */
export function effectiveBundles(node) {
  function explicit(name) {
    const input = inputOf(node, name);
    if (input?.link == null) return null;
    const parents = [];
    let graph = rootGraph();
    try {
      for (const id of executionTarget(node)?.dto?.subgraphNodePath ?? []) {
        const parent = (graph?.nodes ?? graph?._nodes ?? []).find((item) => String(item.id) === String(id));
        if (!parent?.subgraph) return null;
        parents.push(parent);
        graph = parent.subgraph;
      }
    } catch {
      return null;
    }
    const seen = new Set();
    function output(origin, slot, scopes) {
      if (!origin || !active(origin) || seen.has(origin)) return null;
      seen.add(origin);
      if (origin.resolveSubgraphOutputLink && origin.subgraph) {
        const resolved = origin.resolveSubgraphOutputLink(slot);
        return resolved ? output(resolved.outputNode, resolved.link.origin_slot, [...scopes, origin]) : null;
      }
      if (origin.type === 'Reroute') return follow(origin, origin.inputs?.[0], scopes);
      return origin;
    }
    function follow(consumer, socket, scopes) {
      if (socket?.link == null) return null;
      const links = consumer.graph?.links;
      const link = links?.get?.(socket.link) ?? links?.[socket.link];
      if (!link) return null;
      if (link.originIsIoNode && scopes.length) {
        const parent = scopes.at(-1);
        return follow(parent, parent.inputs?.[link.origin_slot], scopes.slice(0, -1));
      }
      return output(linkOrigin(consumer, socket), link.origin_slot, scopes);
    }
    try {
      return follow(node, input, parents);
    } catch {
      // The serializer reports broken links; a stale source never receives notes.
      return null;
    }
  }
  return {
    settings: advertiserFor(node, 'settings') ?? explicit('video_settings'),
    resources: advertiserFor(node, 'resources') ?? explicit('resources'),
    motion: explicit('context_latent'),
    vae: explicit('vae'),
  };
}
