import { app } from '../../../../scripts/app.js';

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
        ['model_hires', 'conditioning'],
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
  },
});
