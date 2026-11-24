// Arisu Save Video Segment: the CRF range follows the codec, and the take context stays out of the workflow.
//
// `take_context` exists for Director, which writes it into the prompt it submits. The widget
// is hidden and socketless, and its own value is always empty: nothing typed, wired, pasted
// or imported can label a take.
//
// The preview needs no code: the node returns the stock saved-video result.

import { app } from '../../../../scripts/app.js';
import { installCodecCrf } from './video_encoding.js';
import { hideWidget } from './widgets.js';

const NODE_TYPE = 'ArisuSaveVideoSegment';
const CONTEXT = 'take_context';

function prepare(node) {
  const context = node.widgets?.find((widget) => widget.name === CONTEXT);
  if (context) {
    context.value = '';
    context.serializeValue = () => '';
    context.options ??= {};
    context.options.socketless = true;
    hideWidget(node, context);
  }
  installCodecCrf(node);
}

app.registerExtension({
  name: 'Arisu.Common.SaveVideoSegment',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;
    for (const hook of ['onNodeCreated', 'onConfigure']) {
      const previous = nodeType.prototype[hook];
      nodeType.prototype[hook] = function () {
        const result = previous?.apply(this, arguments);
        prepare(this);
        return result;
      };
    }
  },
});
