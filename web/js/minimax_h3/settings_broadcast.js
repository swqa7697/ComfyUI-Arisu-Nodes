// MiniMax H3 Video Settings: drive the hybrid nodes' size and length widgets without a link.
//
// A hybrid node takes its width, height and length (and target size, on the
// Advanced node) from a settings node in two ways: by wiring the settings
// node's outputs into those widget inputs (works in any graph, subgraphs
// included), or from an advertising settings node in the root graph.
// Advertising is resolved here: the handed-over widgets are greyed out, links
// into them are refused and existing ones removed, and at queue time the
// prompt sent to the server gets one link per widget injected, from the
// settings node's output of the same name. The saved workflow is never touched.
//
// The greying is recomputed when a node joins or leaves the root graph, when
// the advertise switch is flipped, and after a workflow loads. Hooks go on
// `onAdded`, not `onNodeCreated`: LiteGraph runs the latter inside
// createNode(), before the node has a graph or is listed in it, so a scan from
// there sees nothing. Muting or bypassing a settings node has no callback; its
// widgets update on the next such event, and the run is unaffected because a
// muted node is not in the prompt.
//
// Only one settings node per graph advertises at a time, muted or not. Flipping
// a second switch on hands it the slot and switches the previous one off (later
// change wins); a pasted node that arrives switched on is switched off; a loaded
// workflow with several keeps the first in node order.

import { api } from "../../../../scripts/api.js";
import { app } from "../../../../scripts/app.js";

const ADVERTISE_WIDGET = "advertise";
// LiteGraph node mode 0: runs normally (not muted, not bypassed).
const MODE_ALWAYS = 0;

// Widgets a hybrid node can hand over, and the outputs each settings variant carries, by shared name.
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

/** A node that arrives in the root graph already switched on, by paste or duplicate, is switched off. */
function switchOffOnArrival(node) {
  // a workflow load restores widget values too; afterConfigureGraph applies the load rule instead
  if (app.configuringGraph || node.graph !== rootGraph() || !advertiseOn(node)) return;
  advertiseWidget(node).value = false;
  node.setDirtyCanvas(true, true);
  toast("info", `MiniMax H3 Video Settings node #${node.id} was pasted with advertise on; switched off.`);
}

/** Widget names a hybrid node hands over to the root graph's advertiser: the outputs both carry. */
function handedOverKeys(node) {
  if (node.graph !== rootGraph()) return [];
  const source = soleAdvertiser();
  if (!source) return [];
  return SETTINGS_KEYS[source.type].filter((key) => HYBRID_WIDGETS[node.type].includes(key));
}

/** Remove the links into a hybrid node's handed-over widgets; returns the names that had one. */
function unlinkHandedOver(node, keys) {
  const removed = [];
  for (const [index, input] of (node.inputs ?? []).entries()) {
    if (keys.has(input.name) && input.link != null) {
      node.disconnectInput(index);
      removed.push(input.name);
    }
  }
  return removed;
}

function refreshHybrid(node) {
  const keys = new Set(handedOverKeys(node));
  for (const widget of node.widgets ?? []) {
    if (HYBRID_WIDGETS[node.type].includes(widget.name)) widget.disabled = keys.has(widget.name);
  }
  const removed = unlinkHandedOver(node, keys);
  if (removed.length) {
    toast(
      "info",
      `Hybrid node #${node.id}: ${removed.join(", ")} come from the advertising settings node; the link(s) into them were removed.`,
    );
  }
  node.setDirtyCanvas(true, true);
}

function refreshRoot() {
  for (const node of rootGraph().nodes) {
    if (node.type in HYBRID_WIDGETS) refreshHybrid(node);
  }
}

/** LiteGraph's onConnectInput contract: `false` refuses the connection. */
function refuseHandedOverLink(node, inputIndex) {
  const name = node.inputs?.[inputIndex]?.name;
  if (!handedOverKeys(node).includes(name)) return true;
  toast("warn", `${name} of hybrid node #${node.id} comes from the advertising settings node; switch advertise off to wire it.`);
  return false;
}

/** Point every handed-over widget of the root-graph hybrid nodes in the prompt at the advertiser's outputs. */
function injectAdvertisedValues(output) {
  const source = soleAdvertiser();
  if (!source) return;
  const sourceId = String(source.id);
  const skipped = [];
  for (const node of rootGraph().nodes) {
    if (!(node.type in HYBRID_WIDGETS) || !isActive(node)) continue;
    const entry = output[String(node.id)];
    if (!entry) continue;
    if (!output[sourceId]) {
      skipped.push(node.id);
      continue;
    }
    for (const key of handedOverKeys(node)) {
      const slot = source.outputs.findIndex((out) => out.name === key);
      if (slot >= 0) entry.inputs[key] = [sourceId, slot];
    }
  }
  if (skipped.length) {
    toast("warn", `Settings node #${sourceId} is not part of this run; hybrid node(s) ${skipped.join(", ")} use their own widgets.`);
  }
}

/** Run `extra` after the prototype's `name` hook; a `false` from either side is returned, as LiteGraph's veto hooks expect. */
function chain(prototype, name, extra) {
  const original = prototype[name];
  prototype[name] = function () {
    const result = original?.apply(this, arguments);
    if (result === false) return false;
    return extra.apply(this, arguments) === false ? false : result;
  };
}

app.registerExtension({
  name: "Arisu.MiniMaxH3.SettingsBroadcast",
  setup() {
    const queuePrompt = api.queuePrompt;
    api.queuePrompt = async function (index, prompt, ...rest) {
      if (prompt?.output) injectAdvertisedValues(prompt.output);
      return queuePrompt.call(this, index, prompt, ...rest);
    };
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name in HYBRID_WIDGETS) {
      chain(nodeType.prototype, "onAdded", function () {
        refreshHybrid(this);
      });
      chain(nodeType.prototype, "onConnectInput", function (inputIndex) {
        return refuseHandedOverLink(this, inputIndex);
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
        // a duplicate restores its widgets before it is added, so its switch is visible here
        switchOffOnArrival(node);
        refreshRoot();
      });
      // a paste adds the node first and restores its widgets afterwards, so the switch is only visible here
      chain(nodeType.prototype, "onConfigure", function () {
        switchOffOnArrival(this);
      });
      // onRemoved fires while the node is still listed; refresh once it is gone
      chain(nodeType.prototype, "onRemoved", () => setTimeout(refreshRoot, 0));
    }
  },
  afterConfigureGraph() {
    // widget values and links are restored after onAdded ran, so the rule is applied here for a load
    const first = rootGraph().nodes.find(advertiseOn);
    if (first) enforceSingleAdvertiser(first);
    refreshRoot();
  },
});
