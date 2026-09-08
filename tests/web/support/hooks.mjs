// The web lane's conftest: module-resolution wiring only, no fakes.
//
// The pack's scripts import the frontend core as "../../../../scripts/app.js"
// and ".../api.js". Those are served URLs, resolved by the browser against
// /extensions/<pack dir>/js/<family>/ (tests/comfyui/test_pack.py checks them);
// on disk they point above the repo. Loaded with `node --import`, this hook
// short-circuits exactly those two specifiers to the fakes beside it and lets
// every other import (./widgets.js, node:test) resolve as usual.
import { registerHooks } from "node:module";

const FRONTEND_CORE = /^(\.\.\/){4}scripts\/(app|api)\.js$/;

registerHooks({
  resolve(specifier, context, nextResolve) {
    const match = FRONTEND_CORE.exec(specifier);
    if (!match) return nextResolve(specifier, context);
    return { url: new URL(`./${match[2]}.mjs`, import.meta.url).href, shortCircuit: true };
  },
});
