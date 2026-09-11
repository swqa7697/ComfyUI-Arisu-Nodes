// Fake of the frontend's `app` (scripts/app.js re-exports window.comfyAPI.app.app):
// the surface the pack's scripts touch, a toast sink, a settings store holding whatever
// a script sets (a test seeds `settings` directly), and a per-test reset.
export const toasts = [];
export const settings = {};

export const app = {
  extensions: [],
  graph: null,
  rootGraph: null,
  nodeOutputs: {},
  configuringGraph: false,
  extensionManager: {
    workflow: { activeWorkflow: null },
    toast: {
      add(message) {
        toasts.push(message);
      },
    },
    setting: {
      get(id) {
        return settings[id];
      },
      async set(id, value) {
        settings[id] = value;
      },
    },
  },
  registerExtension(extension) {
    this.extensions.push(extension);
  },
};

/** The extension a script registered under `name`. */
export function extensionNamed(name) {
  const extension = app.extensions.find((candidate) => candidate.name === name);
  if (!extension) throw new Error(`no extension named ${name}`);
  return extension;
}

/** Point `app` at a fresh root graph and drop the state the previous test left behind. */
export function resetApp(graph) {
  app.graph = graph;
  app.rootGraph = graph;
  app.nodeOutputs = {};
  app.configuringGraph = false;
  app.extensionManager.workflow.activeWorkflow = null;
  toasts.length = 0;
  for (const id of Object.keys(settings)) delete settings[id];
}

/** The severities shown so far: the one part of a toast a test asserts, never the wording. */
export function toastSeverities() {
  return toasts.map((message) => message.severity);
}
