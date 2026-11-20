import { el } from '../common/dom.js';
import { browseResources, posterUrl, viewUrl } from '../common/resource_browser.js';
import { cropFor, editMediaSelection, probe, resourceId } from './media_selection.js';

const roles = { first: 'First frame', last: 'Last frame', image: 'Image reference', video: 'Video reference', audio: 'Audio reference' };

export function moveItem(list, index, offset) {
  const target = index + offset;
  if (index >= 0 && target >= 0 && target < list.length) list.splice(target, 0, ...list.splice(index, 1));
}

const filename = (asset) => asset.path.split(/[\\/]/).at(-1);
function preview(asset) {
  if (asset.kind === 'audio') return el('span', { className: 'asset-thumb audio', textContent: 'Audio' });
  const crop = asset.crop && ['left', 'top', 'width', 'height'].map((k) => asset.crop[k]).join(',');
  return el('img', {
    className: 'asset-thumb',
    alt: '',
    loading: 'lazy',
    src:
      asset.kind === 'video'
        ? posterUrl(asset.root, asset.path, asset.clip?.start ?? 0, 128)
        : viewUrl(asset.path, crop ? undefined : 128, false, crop || '', asset.root),
  });
}

function task(ui) {
  ui.state.media?.abort();
  const controller = new AbortController();
  ui.state.media = controller;
  return { signal: controller.signal, current: () => !controller.signal.aborted };
}

async function browse(ui, id) {
  const work = task(ui);
  const doc = ui.read(),
    old = doc.assets.find((a) => a.id === id),
    last = old ?? doc.assets.at(-1);
  await browseResources(
    {
      widgets: [
        { name: 'root', value: last?.root ?? 'input' },
        { name: 'path', value: last?.path ?? '' },
      ],
    },
    {
      mixed: true,
      signal: work.signal,
      isCurrent: work.current,
      selected: (root, path) => doc.assets.some((a) => a.root === root && a.path === path),
      onPick: async (path, root) => {
        try {
          const item = { id: id ?? resourceId(), path, root, muted: false, note: old?.note ?? '' };
          const info = await probe(item, work.signal);
          if (!work.current()) return;
          item.kind = info.kind;
          item.revision = info.revision;
          if (item.kind === 'image') item.crop = null;
          else {
            if (item.kind === 'video') item.include_audio = info.has_audio;
            const result = await editMediaSelection(item, work);
            if (!result || !work.current()) return;
            Object.assign(item, result.draft);
          }
          ui.change((next) => {
            const position = next.assets.findIndex((a) => a.id === item.id);
            if (position < 0) next.assets.push(item);
            else next.assets[position] = item;
            if (id)
              for (const segment of next.segments)
                for (const binding of segment.bindings) {
                  if (binding.asset_id === id) for (const key of ['crop', 'crop_basis_ratio', 'clip', 'include_audio']) delete binding[key];
                }
          });
        } catch (error) {
          if (work.current()) ui.error(error.message);
        }
      },
    },
  );
}

async function edit(ui, asset, binding, segmentId) {
  const work = task(ui);
  const ratio = ui.read().film.aspect_ratio;
  const keyframe = binding && ['first', 'last'].includes(binding.role);
  const item = { ...asset, ...binding };
  if (keyframe && item.crop_basis_ratio !== ratio) {
    const info = await probe(item, work.signal);
    if (!work.current()) return;
    item.crop = cropFor(info, ratio);
  }
  const result = await editMediaSelection(item, work, { keyframe, ratio });
  if (!result || !work.current()) return;
  ui.change((next) => {
    const dest = segmentId
      ? next.segments.find((s) => s.id === segmentId)?.bindings.find((b) => b.asset_id === asset.id && b.role === binding.role)
      : next.assets.find((a) => a.id === asset.id);
    if (!dest) return;
    if (asset.kind === 'image') {
      dest.crop = result.draft.crop;
      dest.crop_basis_ratio = ratio;
    } else {
      dest.clip = result.draft.clip;
      if (asset.kind === 'video') dest.include_audio = result.draft.include_audio;
    }
    if (!segmentId) dest.revision = result.info.revision;
  });
}

export function libraryView(ui, doc) {
  const rows = doc.assets.map((asset, i) => {
    const uses = doc.segments.flatMap((s, index) => (s.bindings.some((b) => b.asset_id === asset.id) ? [String(index + 1)] : []));
    const update = (key, value) =>
      ui.change((next) => {
        next.assets.find((a) => a.id === asset.id)[key] = value;
      }, false);
    const card = el('article', { className: 'card' }, [
      el('div', { className: 'asset-title' }, [
        preview(asset),
        el('strong', { textContent: filename(asset), title: asset.path }),
        el('small', { textContent: asset.kind }),
      ]),
      el('small', { textContent: uses.length ? 'Used by segments ' + uses.join(', ') : 'Available to the director · unbound' }),
      ui.field('Asset notes', asset.note, (value) => update('note', value)),
      el('div', { className: 'actions' }, [
        ui.button(asset.kind === 'image' ? 'Edit crop' : 'Edit clip', () => edit(ui, asset)),
        ui.button('Reselect', () => browse(ui, asset.id)),
        ui.check('Mute', asset.muted, (v) =>
          ui.change((next) => {
            next.assets[i].muted = v;
          }),
        ),
        ...(asset.kind === 'video'
          ? [
              ui.check('Soundtrack', asset.include_audio, (v) =>
                ui.change((next) => {
                  next.assets[i].include_audio = v;
                }),
              ),
            ]
          : []),
        ...ui.moves(doc.assets, i, (delta) => ui.change((next) => moveItem(next.assets, i, delta))),
        ui.button('Remove', () => ui.change((next) => next.assets.splice(i, 1))),
      ]),
    ]);
    card.dataset.asset = asset.id;
    return card;
  });
  // A retained binding can recover its stable ID after an import or an accidental library deletion.
  const missing = new Set(
    doc.segments.flatMap((s) => s.bindings.map((b) => b.asset_id)).filter((id) => !doc.assets.some((a) => a.id === id)),
  );
  return [
    el('div', { className: 'actions' }, [ui.button('Browse assets', () => browse(ui), doc.assets.length >= 256)]),
    ...(rows.length
      ? [el('div', { className: 'library' }, rows)]
      : [el('p', { className: 'meta', textContent: 'Add images, video or audio for planning and segment bindings.' })]),
    ...[...missing].map((id) => ui.button('Reselect missing asset ' + id, () => browse(ui, id))),
  ];
}

export function bindingView(ui, doc, segment) {
  const locate = (next) => next.segments.find((s) => s.id === segment.id).bindings;
  const rows = segment.bindings.map((b, i) => {
    const asset = doc.assets.find((a) => a.id === b.asset_id);
    const opts = asset?.kind === 'image' ? ['first', 'last', 'image'] : [asset?.kind ?? b.role];
    const override = ['clip', 'crop', 'include_audio'].some((k) => Object.hasOwn(b, k));
    const card = el('div', { className: 'binding card' }, [
      el('strong', { textContent: asset ? filename(asset) + (asset.muted ? ' · muted' : '') : 'Missing asset ' + b.asset_id }),
      ui.select(
        'Role',
        b.role,
        opts.map((v) => [v, roles[v]]),
        (v) =>
          ui.change((next) => {
            locate(next)[i] = { asset_id: b.asset_id, role: v };
          }),
      ),
      el('div', { className: 'actions' }, [
        ...(asset
          ? [ui.button(asset.kind === 'image' ? 'Edit segment crop' : 'Edit segment clip', () => edit(ui, asset, b, segment.id))]
          : []),
        ...(asset?.kind === 'video'
          ? [
              ui.check('Segment soundtrack', b.include_audio ?? asset.include_audio, (v) =>
                ui.change((next) => {
                  locate(next)[i].include_audio = v;
                }),
              ),
            ]
          : []),
        ...(override
          ? [
              ui.button('Use library defaults', () =>
                ui.change((next) => {
                  locate(next)[i] = { asset_id: b.asset_id, role: b.role };
                }),
              ),
            ]
          : []),
        ...ui.moves(segment.bindings, i, (d) => ui.change((next) => moveItem(locate(next), i, d))),
        ui.button('Unbind', () => ui.change((next) => locate(next).splice(i, 1))),
      ]),
    ]);
    card.dataset.asset = b.asset_id;
    return card;
  });
  const choices = doc.assets.filter((a) => !a.muted && !segment.bindings.some((b) => b.asset_id === a.id));
  return el('div', { className: 'stack' }, [
    ...(rows.length ? [] : [el('p', { className: 'meta', textContent: 'No assets bound to this segment.' })]),
    ...rows,
    ...(choices.length
      ? [
          ui.select('Bind an asset', '', [['', 'Choose an asset…'], ...choices.map((a) => [a.id, filename(a)])], (id) => {
            const asset = choices.find((a) => a.id === id);
            if (!asset) return;
            ui.change((next) => locate(next).push({ asset_id: id, role: asset.kind }));
            ui.state.dialog?.querySelector(`.binding[data-asset="${CSS.escape(id)}"] select`)?.focus();
          }),
        ]
      : []),
    ui.button('Add to library…', () => browse(ui), doc.assets.length >= 256),
  ]);
}
