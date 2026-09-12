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
  ArisuMiniMaxH3HybridToVideo: ['width', 'height', 'length'],
  ArisuMiniMaxH3HybridToVideoAdvanced: ['width', 'height', 'length', 'target_width', 'target_height'],
};
const RESOURCE_NAMES = ['first_frame', 'last_frame', 'ref_images', 'ref_videos', 'ref_video_audios', 'ref_audios'];
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
function on(node) {
  return widget(node, 'advertise')?.value === true;
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
    widget(node, 'advertise').value = false;
    node.setDirtyCanvas(true, true);
  }
  if (demoted.length) toast('warn', 'Only one source in each category advertises; the latest switch wins.');
}
function handedKeys(node) {
  if (node.graph !== rootGraph()) return [];
  const settings = source('settings');
  if (!settings) return [];
  return node.type === STUDIO ? ['aspect_ratio'] : SETTINGS_KEYS[settings.type].filter((key) => HYBRID_WIDGETS[node.type]?.includes(key));
}
function resourceOwned(node) {
  return !!(
    node.type in HYBRID_WIDGETS &&
    ((node.graph === rootGraph() && source('resources')) || node.inputs?.find((input) => input.name === 'resources')?.link != null)
  );
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
  if (state.owned === owned && !state.transition) return;
  if (state.owned === owned && state.transition) return;
  state.owned = owned;
  state.generation++;
  const generation = state.generation;
  if (!owned) {
    for (const seed of state.seeds) {
      if (!node.inputs?.some((input) => group(input.name) === group(seed.name)))
        node.addInput(seed.name, seed.type, { ...seed, link: null });
    }
    node.setDirtyCanvas(true, true);
    return;
  }
  for (let i = (node.inputs?.length ?? 0) - 1; i >= 0; i--)
    if (individual(node.inputs[i]) && node.inputs[i].link != null) node.disconnectInput(i);
  const tick = () =>
    new Promise((resolve) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(resolve) : setTimeout(resolve, 0)));
  const graph = node.graph;
  graph?.beforeChange?.();
  const task = (async () => {
    await tick();
    await tick();
    if (states.get(node) !== state || generation !== state.generation || !state.owned) return;
    for (let i = node.inputs.length - 1; i >= 0; i--) if (individual(node.inputs[i])) node.removeInput(i);
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
function refreshNode(node) {
  const keys = handedKeys(node);
  const controlled = node.type === STUDIO ? ['aspect_ratio'] : (HYBRID_WIDGETS[node.type] ?? []);
  let dropped = false;
  for (const control of node.widgets ?? []) if (controlled.includes(control.name)) control.disabled = keys.includes(control.name);
  for (let i = 0; i < (node.inputs?.length ?? 0); i++)
    if (keys.includes(node.inputs[i].name) && node.inputs[i].link != null) {
      node.disconnectInput(i);
      dropped = true;
    }
  if (dropped) toast('info', 'Links into advertised controls were removed.');
  if (node.type === STUDIO) {
    const settings = node.graph === rootGraph() ? source('settings') : null;
    node.arisuAspectSource = settings ? `#${settings.id}` : null;
    // A linked settings ratio is not the source node's stale local widget.
    node.arisuEffectiveAspect = settings
      ? settings.inputs?.some((input) => input.name === 'aspect_ratio' && input.link != null)
        ? null
        : widget(settings, 'aspect_ratio')?.value
      : undefined;
    node.arisuRefreshAspect?.();
  }
  if (node.type in HYBRID_WIDGETS) {
    const advertised = node.graph === rootGraph() && source('resources');
    const socket = node.inputs?.find((input) => input.name === 'resources');
    if (socket) {
      socket.disabled = !!advertised;
      socket.color_on = advertised ? '#777' : undefined;
      socket.color_off = advertised ? '#777' : undefined;
      if (advertised && socket.link != null) node.disconnectInput(node.inputs.indexOf(socket));
    }
    scheduleSockets(node, resourceOwned(node));
  }
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
  if (!app.configuringGraph && on(node)) {
    widget(node, 'advertise').value = false;
    toast('info', 'Advertising is off on pasted or duplicated nodes.');
  }
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
function linkSource(node, input) {
  if (input?.link == null) return null;
  const links = node.graph?.links;
  const link = links?.get?.(input.link) ?? links?.[input.link];
  return link ? String(link.origin_id) : null;
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
function inject(output) {
  for (const { node, id: executionId, dto } of executionNodes()) {
    if (!active(node)) continue;
    const entry = output[executionId];
    if (!entry) continue;
    const settings = node.graph === rootGraph() ? source('settings') : null;
    const keys = handedKeys(node);
    if (keys.length) {
      if (!output[String(settings.id)]) throw new Error('The active settings source is absent from this prompt.');
      for (const key of keys) {
        const slot = settings.outputs.findIndex((out) => out.name === key);
        if (slot < 0) throw new Error(`Settings output ${key} is unavailable.`);
        entry.inputs[key] = [String(settings.id), slot];
      }
    }
    if (!(node.type in HYBRID_WIDGETS)) continue;
    const advertiser = node.graph === rootGraph() ? source('resources') : null;
    const explicit = node.inputs?.find((input) => input.name === 'resources');
    const explicitId = dto ? entry.inputs.resources?.[0] : linkSource(node, explicit);
    const directId = linkSource(node, explicit);
    const directNode = (node.graph?.nodes ?? node.graph?._nodes ?? []).find((source) => String(source.id) === directId);
    if (advertiser) {
      const id = String(advertiser.id);
      if (!output[id]) throw new Error('The active resource source is absent from this prompt.');
      const slot = advertiser.outputs.findIndex((out) => out.name === 'resources');
      if (slot < 0) throw new Error('Resource output is unavailable.');
      entry.inputs.resources = [id, slot];
    } else if (explicit?.link != null) {
      if ((directNode && !active(directNode)) || !explicitId || !output[explicitId] || !entry.inputs.resources)
        throw new Error('The explicitly connected resource source is muted, bypassed, or absent.');
    }
    if (advertiser || explicit?.link != null) for (const name of Object.keys(entry.inputs)) if (group(name)) delete entry.inputs[name];
  }
  checkCycles(output);
}
for (const [type, position] of [
  ['ArisuMiniMaxH3VideoSettings', 3],
  ['ArisuMiniMaxH3VideoSettingsUpscale', 4],
])
  registerSelectionOwner(type, { fields: [['advertise', position, false]] });
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
        const control = widget(this, 'advertise');
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
        (input?.name === 'resources' && this.graph === rootGraph() && source('resources'))
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
  afterConfigureGraph() {
    for (const kind of ['settings', 'resources']) {
      const first = (rootGraph()?.nodes ?? []).find((node) => category(node) === kind && on(node));
      if (first) exclusive(first);
    }
    refresh(true);
  },
});
