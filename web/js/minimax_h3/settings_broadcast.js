// MiniMax H3 Video Settings: hand the bundle to the hybrid nodes without a link.
//
// A hybrid node takes its size and length from a settings node in two ways: an
// explicit link into its `settings` input (works in any graph, subgraphs
// included), or an advertising settings node in the root graph. Advertising
// is resolved here: the affected widgets are greyed out, and at queue time the
// prompt sent to the server gets the missing `settings` link injected. The
// saved workflow is never touched.
//
// The greying is recomputed when a node joins or leaves the root graph, when
// the advertise switch is flipped, when a `settings` link changes, and after
// a workflow loads. Hooks go on `onAdded`, not `onNodeCreated`: LiteGraph runs
// the latter inside createNode(), before the node has a graph or is listed in
// it, so a scan from there sees nothing. Muting or bypassing a settings node
// has no callback; its widgets update on the next such event, and the run is
// unaffected because a muted node is not in the prompt.
//
// Only one settings node per graph advertises at a time, muted or not. Flipping
// a second switch on hands it the slot and switches the previous one off (later
// change wins); a pasted node that arrives switched on is switched off; a loaded
// workflow with several keeps the first in node order.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const BUNDLE_TYPE = "ARISU_MINIMAX_H3_SETTINGS";
const SETTINGS_INPUT = "settings";
const ADVERTISE_WIDGET = "advertise";
// LiteGraph node mode 0: runs normally (not muted, not bypassed).
const MODE_ALWAYS = 0;

// Widgets a hybrid node can hand over, and the keys each settings variant carries.
const HYBRID_WIDGETS = {
  ArisuMiniMaxH3HybridToVideo: ["width", "height", "length"],
  ArisuMiniMaxH3HybridToVideoAdvanced: ["width", "height", "length", "target_width", "target_height"],
};
const SETTINGS_KEYS = {
  ArisuMiniMaxH3VideoSettings: ["width", "height", "length"],
  ArisuMiniMaxH3VideoSettingsUpscale: ["width", "height", "length", "target_width", "target_height"],
};

function rootGraph() {
  return app.rootGraph ?? app.graph;
}

function toast(severity, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary: "MiniMax H3 Video Settings", detail, life: 8000 });
}

function isActive(node) {
  return node.mode === MODE_ALWAYS;
}

function advertiseWidget(node) {
  return node.widgets?.find((widget) => widget.name === ADVERTISE_WIDGET);
}

/** The switch is on, muted or not: what the one-advertiser rule counts. */
function advertiseOn(node) {
  return node.type in SETTINGS_KEYS && advertiseWidget(node)?.value === true;
}

/** The switch is on and the node runs: what greying and injection use. */
function advertises(node) {
  return advertiseOn(node) && isActive(node);
}

/** The advertising settings node of the root graph, if any; the rule below keeps it unique. */
function soleAdvertiser() {
  return rootGraph().nodes.find(advertises) ?? null;
}

/** Switch advertise off on every root-graph settings node other than `keep`. */
function enforceSingleAdvertiser(keep) {
  const demoted = rootGraph().nodes.filter((node) => node !== keep && advertiseOn(node));
  for (const node of demoted) {
    // assigning the value does not run the widget callback, so this cannot recurse
    advertiseWidget(node).value = false;
    node.setDirtyCanvas(true, true);
  }
  if (demoted.length) {
    const ids = demoted.map((node) => `#${node.id}`).join(", ");
    toast("warn", `Only one MiniMax H3 Video Settings node advertises at a time: #${keep.id} advertises now, ${ids} switched off.`);
  }
}

function settingsInputIndex(node) {
  return node.inputs?.findIndex((input) => input.name === SETTINGS_INPUT) ?? -1;
}

function linkedSource(node) {
  const index = settingsInputIndex(node);
  if (index < 0 || node.inputs[index].link == null) return null;
  return node.getInputNode(index);
}

/** Keys a hybrid node currently hands over: from its link, else from the root graph's advertiser. */
function handedOverKeys(node) {
  const linked = linkedSource(node);
  if (linked) {
    // a link through a subgraph boundary hides the origin type: assume the full set
    return SETTINGS_KEYS[linked.type] ?? HYBRID_WIDGETS[node.type];
  }
  if (node.graph !== rootGraph()) return [];
  const source = soleAdvertiser();
  return source ? SETTINGS_KEYS[source.type] : [];
}

function refreshHybrid(node) {
  const keys = new Set(handedOverKeys(node));
  for (const widget of node.widgets ?? []) {
    if (HYBRID_WIDGETS[node.type].includes(widget.name)) widget.disabled = keys.has(widget.name);
  }
  node.setDirtyCanvas(true, true);
}

function refreshRoot() {
  for (const node of rootGraph().nodes) {
    if (node.type in HYBRID_WIDGETS) refreshHybrid(node);
  }
}

/** Add the advertised settings link to every root-graph hybrid node the prompt runs without one. */
function injectSettingsLinks(output) {
  const source = soleAdvertiser();
  if (!source) return;
  const sourceId = String(source.id);
  const slot = source.outputs.findIndex((out) => out.type === BUNDLE_TYPE);
  if (slot < 0) return;
  const skipped = [];
  for (const node of rootGraph().nodes) {
    if (!(node.type in HYBRID_WIDGETS) || !isActive(node)) continue;
    const entry = output[String(node.id)];
    if (!entry || entry.inputs[SETTINGS_INPUT] !== undefined) continue;
    if (!output[sourceId]) {
      skipped.push(node.id);
      continue;
    }
    entry.inputs[SETTINGS_INPUT] = [sourceId, slot];
  }
  if (skipped.length) {
    toast("warn", `Settings node #${sourceId} is not part of this run; hybrid node(s) ${skipped.join(", ")} use their own widgets.`);
  }
}

function chain(prototype, name, extra) {
  const original = prototype[name];
  prototype[name] = function () {
    const result = original?.apply(this, arguments);
    extra.apply(this, arguments);
    return result;
  };
}

app.registerExtension({
  name: "Arisu.MiniMaxH3.SettingsBroadcast",
  setup() {
    const queuePrompt = api.queuePrompt;
    api.queuePrompt = async function (index, prompt, ...rest) {
      if (prompt?.output) injectSettingsLinks(prompt.output);
      return queuePrompt.call(this, index, prompt, ...rest);
    };
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name in HYBRID_WIDGETS) {
      chain(nodeType.prototype, "onAdded", function () {
        refreshHybrid(this);
      });
      chain(nodeType.prototype, "onConnectionsChange", function () {
        refreshHybrid(this);
      });
    }
    if (nodeData.name in SETTINGS_KEYS) {
      chain(nodeType.prototype, "onAdded", function () {
        const node = this;
        const widget = advertiseWidget(node);
        if (widget && !widget.arisuWrapped) {
          widget.arisuWrapped = true;
          const callback = widget.callback;
          widget.callback = function () {
            const result = callback?.apply(this, arguments);
            // later change wins: the node just switched on takes the slot
            if (widget.value === true) enforceSingleAdvertiser(node);
            refreshRoot();
            return result;
          };
        }
        // a pasted or duplicated node arriving switched on yields to the existing advertiser
        if (node.graph === rootGraph() && advertiseOn(node)) {
          const existing = rootGraph().nodes.find((other) => other !== node && advertiseOn(other));
          if (existing) enforceSingleAdvertiser(existing);
        }
        refreshRoot();
      });
      // onRemoved fires while the node is still listed; refresh once it is gone
      chain(nodeType.prototype, "onRemoved", function () {
        setTimeout(refreshRoot, 0);
      });
    }
  },
  afterConfigureGraph() {
    // widget values are restored after onAdded ran, so the rule is applied here for a load
    const first = rootGraph().nodes.find(advertiseOn);
    if (first) enforceSingleAdvertiser(first);
    refreshRoot();
  },
});
