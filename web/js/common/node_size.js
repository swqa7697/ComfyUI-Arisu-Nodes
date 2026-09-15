// Restore workflow dimensions after the frontend's automatic load-time expansion.
import { app } from '../../../../scripts/app.js';

const pendingSizes = new WeakMap();

app.registerExtension({
  name: 'Arisu.Common.NodeSize',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!nodeData.name.startsWith('Arisu')) return;

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      pendingSizes.delete(this);
      const size = info?.size;
      if (Array.isArray(size) && size.length === 2 && size.every((value) => Number.isFinite(value) && value > 0)) {
        pendingSizes.set(this, [...size]);
      }
      return onConfigure?.apply(this, arguments);
    };
  },
  loadedGraphNode(node) {
    const size = pendingSizes.get(node);
    pendingSizes.delete(node);
    if (size) node.setSize(size);
  },
});
