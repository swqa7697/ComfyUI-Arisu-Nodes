// The CRF scale belongs to the encoder: the range and the suggested preset follow the selected codec.
import { setWidget } from './widgets.js';

export const CRF = { h264: { max: 51, preset: 18 }, h265: { max: 51, preset: 20 }, av1: { max: 63, preset: 24 } };
// The codec each node last showed, so a change knows which preset the user may still be on.
const shown = new WeakMap();

const widget = (node, name) => node.widgets?.find((item) => item.name === name);

function showRange(node) {
  const codec = widget(node, 'codec');
  const crf = widget(node, 'crf');
  const limits = CRF[codec?.value];
  if (!crf || !limits) return;
  crf.options ??= {};
  crf.options.max = limits.max;
  crf.label = `crf (0–${limits.max})`;
  shown.set(node, codec.value);
}

/**
 * Show the selected codec's CRF range on `node`; call it on creation and after every configure.
 *
 * Only a codec change made by the user moves the value: an untouched preset becomes the
 * new codec's preset, and any other value is kept, lowered into the new range if needed.
 * Loading a workflow never rewrites a saved CRF; the server refuses a value outside the range.
 */
export function installCodecCrf(node) {
  const codec = widget(node, 'codec');
  const crf = widget(node, 'crf');
  if (!codec || !crf) return;
  if (!shown.has(node)) {
    const callback = codec.callback;
    codec.callback = function (value, ...rest) {
      const result = callback?.call(this, value, ...rest);
      const before = CRF[shown.get(node)];
      const after = CRF[value];
      if (after) {
        const next = before && crf.value === before.preset ? after.preset : Math.min(crf.value, after.max);
        showRange(node);
        if (next !== crf.value) setWidget(node, crf, next);
      }
      return result;
    };
  }
  showRange(node);
}
