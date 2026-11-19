import { app } from '../../../../scripts/app.js';

const legacyWidgets = [
  'seed',
  'control_after_generate',
  'cfg',
  'transition_step',
  'lowres_scale',
  'rho',
  'w_min',
  'w_max',
  'upscaler_model',
  'highres_tiling',
  'upscaler_unload',
];

app.registerExtension({
  name: 'Arisu.MiniMaxH3.SelfLift',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== 'ArisuMiniMaxH3SelfLiftProgressiveSampler') return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      // ComfyUI constructs required sockets first. Move the optional sockets
      // beside their related inputs before the graph can attach any wires.
      for (const [name, before] of [
        ['model_hires', 'positive'],
        ['context_latent', 'sampler'],
        ['trim_frames', 'sampler'],
      ]) {
        const slot = this.inputs.findIndex((input) => input.name === name);
        const [input] = this.inputs.splice(slot, 1);
        this.inputs.splice(
          this.inputs.findIndex((item) => item.name === before),
          0,
          input,
        );
      }
      return result;
    };

    const configure = nodeType.prototype.configure;
    nodeType.prototype.configure = function (info) {
      // The old layout always had positive as its second socket. Old workflow
      // files can store only positional widget values, including the seed control.
      if (info.inputs?.[1]?.name === 'positive' && Array.isArray(info.widgets_values)) {
        const saved = Object.fromEntries(info.widgets_values.map((value, index) => [legacyWidgets[index], value]));
        Object.assign(saved, info.widgets_values_named);
        const values = this.widgets
          .filter((widget) => widget.serialize !== false)
          .map((widget) => (Object.hasOwn(saved, widget.name) ? saved[widget.name] : widget.value));
        return configure.call(this, { ...info, widgets_values: values });
      }
      return configure.apply(this, arguments);
    };
  },
});
