// Preview & Save Image's save button: what it posts to /arisu/save_image, the
// contract core.parse_save_request validates on the other side, and how it
// reports back through the button and the toasts.
import assert from "node:assert/strict";
import { test } from "node:test";

import { api, jsonResponse, resetApi } from "../support/api.mjs";
import { app, extensionNamed, resetApp, toastSeverities } from "../support/app.mjs";
import { makeGraph, makeNode } from "../support/litegraph.mjs";
import "../../../web/js/common/preview_save_image.js";

const extension = extensionNamed("Arisu.Common.PreviewSaveImage");
const PreviewSave = { prototype: {} };
const PreviewSaveUpscale = { prototype: {} };
extension.beforeRegisterNodeDef(PreviewSave, { name: "ArisuPreviewSaveImage" });
extension.beforeRegisterNodeDef(PreviewSaveUpscale, { name: "ArisuPreviewSaveImageUpscale" });

const IMAGES = [{ filename: "ComfyUI_temp_00001_.png", subfolder: "", type: "temp" }];

/** A node of `nodeType` after LiteGraph created it, so it carries the save button. */
function makeSaveNode(nodeType, options) {
  const node = makeNode({ type: "ArisuPreviewSaveImage", ...options });
  nodeType.prototype.onNodeCreated.call(node);
  return node;
}

function saveButton(node) {
  return node.widgets.find((widget) => widget.type === "button");
}

async function clickSave(node) {
  await saveButton(node).callback();
}

test("save posts the run's images with the recorded widgets, reading a linked widget from the run", async () => {
  resetApp(makeGraph());
  resetApi();
  const node = makeSaveNode(PreviewSave, {
    id: 7,
    graph: app.graph,
    widgets: [{ name: "path", value: "typed/by/hand" }],
    inputs: [{ name: "path", link: 3 }],
  });
  // nothing recorded for the node yet: a warning and no request
  await clickSave(node);
  assert.deepEqual(toastSeverities(), ["warn"]);
  assert.equal(api.calls.length, 0);
  // a run recorded the images and the linked path's value: the body carries both, not the typed text
  app.nodeOutputs["7"] = { images: IMAGES, path: ["from/the/run"] };
  api.responses.push(jsonResponse(200, { saved: [{ filename: "a_00001_.png", subfolder: "from/the/run" }] }));
  await clickSave(node);
  assert.equal(api.calls.length, 1);
  const { route, init } = api.calls[0];
  assert.equal(route, "/arisu/save_image");
  assert.equal(init.method, "POST");
  assert.deepEqual(JSON.parse(init.body), { images: IMAGES, path: "from/the/run" });
  assert.deepEqual(toastSeverities(), ["warn", "success"]);
  assert.equal(saveButton(node).disabled, false);
  // inside a subgraph the outputs are keyed "<subgraph id>:<node id>"; the Upscale variant adds its model
  const inner = makeSaveNode(PreviewSaveUpscale, {
    id: 9,
    graph: makeGraph("sub"),
    widgets: [
      { name: "path", value: "clips" },
      { name: "upscale_model", value: "4x.pth" },
    ],
    inputs: [{ name: "path" }],
  });
  app.nodeOutputs["sub:9"] = { images: IMAGES };
  api.responses.push(jsonResponse(200, { saved: [] }));
  await clickSave(inner);
  assert.deepEqual(JSON.parse(api.calls[1].init.body), { images: IMAGES, path: "clips", upscale_model: "4x.pth" });
});

test("a failed save reports an error and hands the button back", async () => {
  resetApp(makeGraph());
  resetApi();
  const node = makeSaveNode(PreviewSave, {
    id: 7,
    graph: app.graph,
    widgets: [{ name: "path", value: "clips" }],
    inputs: [{ name: "path" }],
  });
  app.nodeOutputs["7"] = { images: IMAGES };
  // the route refuses: the button is held while the request is in flight and released afterwards
  let disabledInFlight;
  api.responses.push(() => {
    disabledInFlight = saveButton(node).disabled;
    return jsonResponse(400, { error: "path escapes the output directory" });
  });
  await clickSave(node);
  assert.equal(disabledInFlight, true);
  assert.equal(saveButton(node).disabled, false);
  assert.deepEqual(toastSeverities(), ["error"]);
  // the request itself fails (server unreachable): same outcome
  api.responses.push(new Error("offline"));
  await clickSave(node);
  assert.deepEqual(toastSeverities(), ["error", "error"]);
  assert.equal(saveButton(node).disabled, false);
});
