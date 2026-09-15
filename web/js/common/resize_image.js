// Resize Image: a "settings…" button that opens the node's resize options in a dialog.
//
// Only `width` and `height` matter at a glance; the other five inputs (the resampling
// method, how proportions are kept, the pad colour, the crop position, the pixel grid)
// change rarely, so settings_button.js hides them and edits them in its dialog.
//
// The preview needs no code: the node returns its result as a ui preview, which the
// frontend draws on the node in both renderers.

import { app } from '../../../../scripts/app.js';
import { installSettingsButton } from './settings_button.js';

const NODE_TYPE = 'ArisuResizeImage';

app.registerExtension({
  name: 'Arisu.Common.ResizeImage',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;
    installSettingsButton(nodeType, nodeData, {
      label: 'settings…',
      title: 'Resize Image settings',
      widgets: ['resize_method', 'mode', 'pad_color', 'crop_position', 'divisible_by'],
      colorWidgets: ['pad_color'],
    });
  },
});
