import { api } from '../../../../scripts/api.js';
import { cropImage } from '../common/cropper.js';
import { viewUrl } from '../common/resource_browser.js';
import { editClip } from './clip_editor.js';

export function resourceId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // randomUUID requires a secure context; getRandomValues also works over HTTP.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export function cropFor(info, label) {
  const [w, h] = label.split(' ')[0].split(':').map(Number);
  const width = Math.max(1, Math.min(info.width, Math.floor((info.height * w) / h)));
  const height = Math.max(1, Math.min(info.height, Math.floor((info.width * h) / w)));
  return { left: Math.floor((info.width - width) / 2), top: Math.floor((info.height - height) / 2), width, height };
}
export async function probe(item, signal) {
  const response = await api.fetchApi(`/arisu/resources/metadata?${new URLSearchParams({ root: item.root, path: item.path })}`, { signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Cannot inspect resource');
  return data;
}
async function imageAt(item, signal) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('Cannot decode image'));
    signal.addEventListener(
      'abort',
      () => {
        image.src = '';
        reject(new Error('Editor closed'));
      },
      { once: true },
    );
    image.src = viewUrl(item.path, undefined, true, '', item.root);
  });
}

/** Open the shared crop or clip editor and confirm source identity before accepting the selection. */
export async function editMediaSelection(item, task, { keyframe = false, ratio, preset = '' } = {}) {
  const info = await probe(item, task.signal);
  if (!task.current()) return;
  if (item.revision && item.revision !== info.revision) throw new Error('Source changed; reselect it.');
  if (keyframe && info.kind !== 'image') throw new Error('Keyframes require an image');
  const draft = { ...item, kind: info.kind };
  let appliedRatio;
  if (info.kind === 'image') {
    const image = await imageAt(item, task.signal);
    if (!task.current()) return;
    const current = ratio;
    const box = draft.crop;
    const result = await cropImage(
      image,
      {
        rect: box ? { x: box.left, y: box.top, w: box.width, h: box.height } : null,
        ratio: preset,
      },
      { aspectRatio: keyframe ? current : undefined, signal: task.signal },
    );
    if (!task.current() || !result.rect) return;
    appliedRatio = result.ratio;
    const { x, y, w, h } = result.rect;
    draft.crop = x === 0 && y === 0 && w === info.width && h === info.height ? null : { left: x, top: y, width: w, height: h };
    if (keyframe) draft.crop_basis_ratio = current ?? draft.crop_basis_ratio ?? null;
  } else {
    const result = await editClip(draft, info, { signal: task.signal });
    if (!task.current() || !result) return;
    Object.assign(draft, result);
  }
  const latest = await probe(item, task.signal);
  if (!task.current()) return;
  if (latest.revision !== info.revision) throw new Error('Source changed while editing; reselect it.');
  return { draft, info, appliedRatio };
}
