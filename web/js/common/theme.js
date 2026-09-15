// Native node presets and quiet, theme-aware styling shared by every custom panel.
import { app } from '../../../../scripts/app.js';

const NODE_COLORS = {
  ArisuLoadImage: 'red',
  ArisuMiniMaxH3ResourceStudio: 'red',
  ArisuPreviewSaveImage: 'yellow',
  ArisuPreviewSaveImageUpscale: 'yellow',
  ArisuMiniMaxH3PromptWorkbench: 'pale_blue',
};
const PANELS =
  ':is(.arisu-studio,.arisu-workbench,.arisu-browser,.arisu-cropper,.arisu-clip,.arisu-settings,.arisu-agents,.arisu-activity-modal,.arisu-settings-entry)';
const DIALOGS = ':is(.arisu-browser,.arisu-cropper,.arisu-clip,.arisu-settings,.arisu-agents,.arisu-activity-modal)';
const ACTIONS = 'button:is(.arisu-action,.primary,.danger)';
const CONFIRM = 'button:is(.review,.apply,.arisu-cropper-apply,.arisu-clip-apply,.arisu-settings-apply)';
const STYLE = `
${PANELS}{
 --arisu-red:color-mix(in srgb,var(--arisu-palette-red),var(--fg-color,#ddd) 25%);
 --arisu-blue:color-mix(in srgb,var(--arisu-palette-pale_blue),var(--fg-color,#ddd) 35%);
 --arisu-image:var(--arisu-blue);
 --arisu-video:color-mix(in srgb,var(--arisu-palette-yellow),var(--fg-color,#ddd) 25%);
 --arisu-audio:color-mix(in srgb,var(--arisu-palette-purple),var(--fg-color,#ddd) 40%);
 --arisu-accent:var(--arisu-red);
 --arisu-action:color-mix(in srgb,var(--arisu-palette-cyan),var(--fg-color,#ddd) 15%);
 --arisu-on-action:var(--comfy-menu-bg,#171717);
 --arisu-hover:color-mix(in srgb,var(--comfy-input-bg,#222),var(--fg-color,#ddd) 8%);
 scrollbar-width:thin;scrollbar-color:var(--border-color,#444) transparent;
}
:is(.arisu-workbench,.arisu-agents,.arisu-activity-modal,.arisu-settings-entry){--arisu-accent:var(--arisu-blue);}
:is(.arisu-workbench,.arisu-agents,.arisu-activity-modal,.arisu-settings-entry){--arisu-action:var(--arisu-video);}
.arisu-settings{--arisu-accent:var(--p-primary-color,var(--fg-color,#ddd));}
dialog${DIALOGS}[open]{border-radius:8px;box-shadow:0 12px 40px #0006;animation:none;}
dialog${DIALOGS}[open]::backdrop{background:#0008;backdrop-filter:none;animation:none;}
${PANELS} :is(button,input,select,textarea){transition:background-color 120ms ease,border-color 120ms ease;}
${DIALOGS} :is(button,input,select,textarea){border-radius:4px;}
${PANELS} button:enabled:hover{background-color:var(--arisu-hover);border-color:var(--arisu-accent);}
${PANELS} button:enabled:active{background-color:color-mix(in srgb,var(--comfy-input-bg,#222),var(--arisu-accent) 16%);transform:none;}
${PANELS} :focus-visible{outline:2px solid var(--arisu-accent);outline-offset:2px;}
${PANELS} :is(input,select,textarea):focus-visible{outline:0;border-color:var(--arisu-accent);box-shadow:inset 0 0 0 1px var(--arisu-accent);}
${PANELS} button:disabled{cursor:default;opacity:.45;transform:none;}
${PANELS} :is(input,select,textarea):enabled:hover{border-color:var(--descrip-text,#999);}
${PANELS} :is(input,select,textarea):focus-visible:hover{border-color:var(--arisu-accent);}
${PANELS} ${CONFIRM}{
 background:var(--arisu-blue);border-color:var(--arisu-blue);color:var(--arisu-on-action);font-weight:600;
}
${PANELS} ${CONFIRM}:enabled:hover{
 background:color-mix(in srgb,var(--arisu-blue),var(--fg-color,#ddd) 18%);border-color:var(--fg-color,#ddd);color:var(--arisu-on-action);
}
${PANELS} ${CONFIRM}:enabled:active{background:color-mix(in srgb,var(--arisu-blue),var(--arisu-on-action) 12%);transform:none;}
${PANELS} ${ACTIONS}{
 background:var(--arisu-action);border-color:var(--arisu-action);color:var(--arisu-on-action);font-weight:600;
}
${PANELS} ${ACTIONS}:enabled:hover{
 background:color-mix(in srgb,var(--arisu-action),var(--fg-color,#ddd) 18%);border-color:var(--fg-color,#ddd);color:var(--arisu-on-action);
}
${PANELS} ${ACTIONS}:enabled:active{background:color-mix(in srgb,var(--arisu-action),var(--arisu-on-action) 12%);transform:none;}
${PANELS} button.danger{--arisu-action:var(--arisu-red);}
.arisu-studio .box,.arisu-studio .reference,.arisu-studio .thumb{border-radius:4px;}
.arisu-studio .reference.muted{opacity:.65;}
.arisu-studio .picture:enabled:hover{border-color:var(--arisu-accent);}
.arisu-studio .edit:enabled:hover{background:transparent;}
.arisu-studio :focus-visible{outline-offset:-2px;}
.arisu-browser .arisu-browser-file:hover{transform:none;box-shadow:none;}
.arisu-browser .arisu-browser-file[data-kind=image] .arisu-browser-tile{outline:1px solid var(--arisu-image);outline-offset:-1px;}
.arisu-browser .arisu-browser-file[data-kind=video] .arisu-browser-tile{outline:1px solid var(--arisu-video);outline-offset:-1px;}
.arisu-browser .arisu-browser-file[data-kind=audio] .arisu-browser-tile{outline:1px solid var(--arisu-audio);outline-offset:-1px;}
.arisu-clip .arisu-clip-badge,.arisu-clip .arisu-clip-chip[aria-pressed=true]{
 color:var(--input-text,#ddd);background:color-mix(in srgb,var(--kind) 18%,var(--comfy-input-bg,#222));border:1px solid var(--kind);
}
.arisu-agents .tabs button[aria-selected=true],.arisu-activity-modal [role=tab][aria-selected=true]{
 color:var(--input-text,#ddd);border-color:var(--arisu-accent);background:color-mix(in srgb,var(--arisu-accent) 14%,var(--comfy-input-bg,#222));
}

.arisu-settings-entry button{font:inherit;padding:6px 12px;min-height:32px;border:1px solid var(--border-color,#444);border-radius:4px;
 background:var(--comfy-input-bg,#222);color:var(--input-text,#ddd);cursor:pointer;}
.arisu-agents-shortcut:enabled:hover{background:color-mix(in srgb,var(--comfy-input-bg,#222),var(--fg-color,#ddd) 8%);}
.arisu-agents-shortcut:enabled:active{background:color-mix(in srgb,var(--comfy-input-bg,#222),var(--fg-color,#ddd) 16%);}
@media(prefers-reduced-motion:reduce){${PANELS} *{transition:none!important;}}
`;

app.registerExtension({
  name: 'Arisu.Common.Theme',
  setup() {
    const style = document.createElement('style');
    // Resolve the same palette used by ComfyUI's Colors menu; surfaces and text
    // remain live CSS variables so changing the official theme needs no reload.
    const palette = app.canvas.constructor.node_colors;
    const colors = ['red', 'pale_blue', 'yellow', 'purple', 'cyan']
      .map((name) => `--arisu-palette-${name}:${palette[name].groupcolor};`)
      .join('');
    style.textContent = `:root{${colors}}\n${STYLE}`;
    document.head.append(style);
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    const name = NODE_COLORS[nodeData.name];
    if (!name) return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      const preset = app.canvas.constructor.node_colors[name];
      this.color = preset.color;
      this.bgcolor = preset.bgcolor;
      return result;
    };
    // Workflow configuration runs after creation and retains saved user colors.
  },
});
