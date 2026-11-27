// Doubles shared by the Assemble Video scenarios: the node as LiteGraph builds it, a described take,
// a request router for the fake `api`, and the lookups both files use to read the panel.
import { api, resetApi } from './api.mjs';
import { app } from './app.mjs';
import { body, descendants } from './dom.mjs';
import { makeNode } from './litegraph.mjs';

export const TYPE = 'ArisuAssembleVideo';
const WIDGETS = {
  project_prefix: 'motion_context/fixed',
  export_name: 'main',
  encoding: 'inherit',
  codec: 'h264',
  crf: 18,
  edit_json: '',
  export_request: '',
};

/** A node with a widget and a socket per value input, created through the extension's own hook. */
export function makeAssembly(definition, { id = 7, graph = app.graph, values = {}, properties = {} } = {}) {
  const node = makeNode({
    id,
    type: TYPE,
    graph,
    widgets: Object.entries({ ...WIDGETS, ...values }).map(([name, value]) => ({ name, value, options: {} })),
    inputs: Object.keys(WIDGETS).map((name) => ({ name })),
    outputs: ['video', 'path', 'record'],
  });
  node.properties = structuredClone(properties);
  definition.prototype.onNodeCreated.call(node);
  return node;
}

/** What the server reports for one video: 24 fps, 1280 × 720, stereo PCM, and a take record unless `take` is null. */
export function described(path, { take = null, frames = 240, predecessor = null, revision = `rev:${path}`, origin = 'ordinary' } = {}) {
  return {
    root: 'output',
    path,
    state: 'ok',
    revision,
    frames,
    fps: [24, 1],
    duration: frames / 24,
    width: 1280,
    height: 720,
    codec: 'h264',
    vfr: false,
    audio: { rate: 32000, channels: 2, samples: Math.round((frames * 32000) / 24), source: take ? 'pcm' : 'embedded' },
    take: take ? { take, origin, segment: null, predecessor, transition: predecessor ? 'continuation' : null } : null,
  };
}

/** Answer every request from `handler(route, init)`; an unexpected route fails the test at the call. */
export function serve(handler) {
  resetApi();
  const answer = (route, init) => {
    const response = handler(route, init);
    if (response === undefined) throw new Error(`unexpected request ${init?.method ?? 'GET'} ${route}`);
    return response;
  };
  for (let i = 0; i < 256; i++) api.responses.push(answer);
}

export const widget = (node, name) => node.widgets.find((item) => item.name === name);
export const edit = (node) => JSON.parse(widget(node, 'edit_json').value);
export const panel = (node) => widget(node, 'assembly').element;
export const settle = () => new Promise((resolve) => setImmediate(resolve));
/** The open modal on top: the take picker, Browse, a join preview or a confirmation. */
export const dialog = () => body.children.findLast((element) => element.tagName === 'DIALOG' && element.open);
/** A button under `root` by its text or accessible name. */
export const button = (root, name) =>
  descendants(root).find((element) => element.tagName === 'BUTTON' && (element.textContent === name || element.ariaLabel === name));
/** The entry rows of the panel in film order. */
export const rows = (node) => descendants(panel(node)).filter((element) => element.dataset.entryId);
export const row = (node, id) => rows(node).find((element) => element.dataset.entryId === id);
