// Fake of the frontend's `api` (scripts/api.js re-exports window.comfyAPI.api.api).
// `fetchApi` records each call and answers from `responses`, in order; an entry may
// be a Response double, an Error (the request itself fails), or a function of
// (route, init) returning either, for a test that needs to look at state in flight.
export const api = {
  calls: [],
  responses: [],
  queued: [],
  apiURL(route) {
    return `/api${route}`;
  },
  async fetchApi(route, init) {
    this.calls.push({ route, init });
    const next = this.responses.shift();
    if (next === undefined) throw new Error(`fetchApi(${route}): no response queued`);
    const response = typeof next === 'function' ? next(route, init) : next;
    if (response instanceof Error) throw response;
    return response;
  },
  async queuePrompt(index, prompt, ...rest) {
    this.queued.push({ index, prompt, rest });
    return 'queued';
  },
};

/** A Response double carrying the JSON `body`; `ok` follows the status the way fetch's does. */
export function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, statusText: `status ${status}`, json: async () => body };
}

export function resetApi() {
  api.calls.length = 0;
  api.responses.length = 0;
  api.queued.length = 0;
}
