import { app } from '../../../../scripts/app.js';

const PROPERTY = 'arisu_h3_hybrid';
const FIELDS = ['overlay_model', 'block_start', 'block_end', 'include_final_adaln'];

function selections(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result = {};
  if (typeof value.overlay_model === 'string') result.overlay_model = value.overlay_model;
  for (const name of ['block_start', 'block_end']) {
    if (Number.isInteger(value[name]) && value[name] >= 0 && value[name] <= 49) result[name] = value[name];
  }
  if (typeof value.include_final_adaln === 'boolean') result.include_final_adaln = value.include_final_adaln;
  return result;
}

function remember(node) {
  const current = {};
  for (const name of FIELDS) {
    const widget = node.widgets?.find((item) => item.name === `mode.${name}`);
    if (widget) current[name] = widget.value;
  }
  node.properties ??= {};
  node.properties[PROPERTY] = { ...selections(node.properties[PROPERTY]), ...selections(current) };
}

function restore(node) {
  const saved = selections(node.properties?.[PROPERTY]);
  for (const [name, value] of Object.entries(saved)) {
    const widget = node.widgets?.find((item) => item.name === `mode.${name}`);
    if (widget) widget.value = value;
  }
}

function updateControls(node, mode) {
  const inactive = mode.value !== 'hybrid';
  for (const name of FIELDS) {
    const widget = node.widgets?.find((item) => item.name === `mode.${name}`);
    if (!widget) continue;
    widget.disabled = inactive;
    // Keep workflow values, but omit inactive controls from API prompts.
    widget.options.serialize = !inactive;
  }
  const base = node.widgets.find((widget) => widget.name === 'base_model');
  if (base) {
    node.widgets.splice(node.widgets.indexOf(base), 1);
    node.widgets.splice(node.widgets.indexOf(mode) + 1, 0, base);
  }
  node.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: 'Arisu.MiniMaxH3.ModelLoader',
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== 'ArisuMiniMaxH3ModelLoader') return;
    // Render both branches with native widgets. The server's native branch
    // remains empty, so inactive overlay settings never become dependencies.
    const options = nodeData.input.required.mode[1].options;
    options.find((option) => option.key === 'native').inputs = structuredClone(options.find((option) => option.key === 'hybrid').inputs);
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      const mode = this.widgets?.find((widget) => widget.name === 'mode');
      if (!mode) throw new Error('MiniMax H3 Model Loader requires native V3 DynamicCombo support.');
      const callback = mode.callback;
      let configuring = false;
      let sizeBeforeRebuild = null;
      const value = Object.getOwnPropertyDescriptor(mode, 'value');
      if (!value?.get || !value?.set) {
        throw new Error('MiniMax H3 Model Loader requires a compatible native DynamicCombo value accessor.');
      }
      const tracked = new WeakSet();
      const update = () => {
        updateControls(this, mode);
        if (value.configurable) return;
        // Older frontends lock the native accessor. Capture each outgoing
        // widget and size before DynamicCombo disposes it and shrinks the node,
        // then restore on its callback.
        for (const name of FIELDS) {
          const widget = this.widgets.find((item) => item.name === `mode.${name}`);
          if (!widget || tracked.has(widget)) continue;
          tracked.add(widget);
          const removed = widget.onRemove;
          widget.onRemove = (...args) => {
            if (!configuring) {
              sizeBeforeRebuild ??= [...this.size];
              this.properties ??= {};
              this.properties[PROPERTY] = { ...selections(this.properties[PROPERTY]), ...selections({ [name]: widget.value }) };
            }
            return removed?.apply(widget, args);
          };
        }
      };
      if (value.configurable) {
        Object.defineProperty(mode, 'value', {
          ...value,
          set: (next) => {
            const size = [...this.size];
            if (!configuring) remember(this);
            value.set.call(mode, next);
            this.setSize(size);
            if (!configuring) restore(this);
            update();
          },
        });
      }
      mode.callback = (...args) => {
        // Older frontends shrink in the locked setter; newer ones shrink in
        // this callback. Both modes have the same controls and need no resize.
        const size = sizeBeforeRebuild ?? [...this.size];
        sizeBeforeRebuild = null;
        const output = callback?.apply(mode, args);
        this.setSize(size);
        if (!configuring) restore(this);
        update();
        return output;
      };
      const configure = this.configure;
      this.configure = function (info) {
        sizeBeforeRebuild = null;
        configuring = true;
        try {
          // The locked setter rebuilds children ahead of base_model during
          // positional restoration. Reapply by the saved display order after
          // native configure finishes, without changing the workflow object.
          const saved = !value.configurable
            ? (info.widgets_values_named ??
              Object.fromEntries(
                this.widgets
                  .filter((widget) => widget.serialize !== false)
                  .flatMap((widget, index) =>
                    index < (info.widgets_values?.length ?? 0) ? [[widget.name, info.widgets_values[index]]] : [],
                  ),
              ))
            : null;
          const output = configure.apply(this, arguments);
          if (saved) {
            for (const widget of this.widgets) {
              if (widget !== mode && Object.hasOwn(saved, widget.name)) widget.value = saved[widget.name];
            }
          }
          // Serialized widgets take precedence in both modes.
          remember(this);
          return output;
        } finally {
          configuring = false;
          update();
        }
      };
      update();
      return result;
    };
    const serialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (info) {
      const result = serialize?.apply(this, arguments);
      remember(this);
      info.properties = { ...info.properties, [PROPERTY]: { ...this.properties[PROPERTY] } };
      return result;
    };
  },
});
