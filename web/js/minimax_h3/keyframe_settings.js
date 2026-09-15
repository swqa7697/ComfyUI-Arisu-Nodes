// MiniMax H3 Hybrid to Video: a "keyframes…" button that opens the keyframe fit settings in a dialog.
//
// Each keyframe carries Resize Image's settings (the resampler, crop / pad / stretch, the pad
// colour, the crop position) as four ordinary inputs, eight in all, which would double the
// node's height. settings_button.js hides them and edits them in one dialog, the first
// frame's rows above the last frame's under a heading each, the `first_frame_` / `last_frame_`
// prefix dropped from the labels. The pixel grid is the model's 32 and has no setting.

import { app } from '../../../../scripts/app.js';
import { installSettingsButton } from '../common/settings_button.js';

const NODE_TYPES = new Set(['ArisuMiniMaxH3HybridToVideo', 'ArisuMiniMaxH3HybridToVideoAdvanced']);
const KEYFRAMES = ['first_frame', 'last_frame'];
const SETTINGS = ['resize_method', 'mode', 'pad_color', 'crop_position'];

app.registerExtension({
  name: 'Arisu.MiniMaxH3.KeyframeSettings',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!NODE_TYPES.has(nodeData.name)) return;
    installSettingsButton(nodeType, nodeData, {
      label: 'keyframes…',
      title: 'Keyframe settings',
      widgets: KEYFRAMES.flatMap((frame) => SETTINGS.map((setting) => `${frame}_${setting}`)),
      colorWidgets: KEYFRAMES.map((frame) => `${frame}_pad_color`),
      sections: KEYFRAMES.map((frame) => ({ title: frame.replace('_', ' '), prefix: `${frame}_` })),
    });
  },
});
