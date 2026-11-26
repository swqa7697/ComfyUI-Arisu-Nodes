import { el } from '../common/dom.js';
import { AUDIO_ICON, browseResources, posterUrl, viewUrl } from '../common/resource_browser.js';
import { moveItem, resourceId } from '../common/shared.js';
import { bindingKind } from './director_document.js';
import { cropFor, editMediaSelection, probe } from './media_selection.js';

const roles = { first: 'First frame', last: 'Last frame', image: 'Image reference', video: 'Video reference', audio: 'Audio reference' };

const filename = (asset) => asset.path.split(/[\\/]/).at(-1);
function preview(asset) {
  if (asset.kind === 'audio') {
    const thumb = el('span', { className: 'asset-thumb audio', ariaHidden: 'true' });
    thumb.innerHTML = AUDIO_ICON;
    return thumb;
  }
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

function requiredKind(doc, id, submitted) {
  if (!id) return;
  const kinds = new Set(doc.segments.flatMap((s) => s.bindings.filter((b) => b.asset_id === id).map((b) => bindingKind(b.role))));
  if (kinds.size > 1) throw new Error('This asset has conflicting roles. Unbind the incompatible role before reselecting the source.');
  if (kinds.size) return kinds.values().next().value;
  if (!doc.assets.some((asset) => asset.id === id) && submitted?.boundAssets?.has(id)) return submitted.assets.get(id)?.kind;
}

export async function browseAssets(ui, id) {
  const work = task(ui);
  const doc = ui.read(),
    old = doc.assets.find((a) => a.id === id),
    last = old ?? doc.assets.at(-1);
  const expected = requiredKind(doc, id, ui.state.run?.directorSubmission);
  await browseResources(
    {
      widgets: [
        { name: 'root', value: last?.root ?? 'input' },
        { name: 'path', value: last?.path ?? '' },
      ],
    },
    {
      mixed: true,
      kinds: expected ? [expected] : undefined,
      signal: work.signal,
      isCurrent: work.current,
      selected: (root, path) => doc.assets.some((a) => a.root === root && a.path === path),
      onPick: async (path, root) => {
        try {
          const item = { id: id ?? resourceId(), path, root };
          const info = await probe(item, work.signal);
          if (!work.current()) return;
          if (expected && info.kind !== expected) throw new Error(`Choose a file of type ${expected} for this asset's bindings.`);
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
            if (position < 0 && old) throw new Error('This asset was removed while the picker was open.');
            if (position < 0 && next.assets.length >= 256)
              throw new Error('The library is full. Remove an unused asset before adding this one.');
            const required = requiredKind(next, id, ui.state.run?.directorSubmission);
            if (required && item.kind !== required) throw new Error(`Choose a file of type ${required} for this asset's bindings.`);
            item.muted = next.assets[position]?.muted ?? false;
            item.note = next.assets[position]?.note ?? '';
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

// Bindings can override the selected region and soundtrack of a library asset.
function boundMedia(asset, binding = {}) {
  const { crop = asset.crop, crop_basis_ratio = asset.crop_basis_ratio, clip = asset.clip, include_audio = asset.include_audio } = binding;
  return { ...asset, crop, crop_basis_ratio, clip, include_audio };
}

async function edit(ui, asset, binding, segmentId) {
  const work = task(ui);
  const ratio = ui.read().film.aspect_ratio;
  const keyframe = binding && ['first', 'last'].includes(binding.role);
  const item = boundMedia(asset, binding);
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

function mediaHeading(ui, asset, detail, binding, segmentId) {
  const command = asset.kind === 'image' ? 'Edit crop' : 'Edit clip';
  const editButton = ui.button('', () => edit(ui, asset, binding, segmentId));
  editButton.className = 'media-preview';
  editButton.title = editButton.ariaLabel = command + ' · ' + filename(asset);
  editButton.append(preview(boundMedia(asset, binding)), binding ? el('span', { textContent: command }) : glyph('pencil'));
  return el('div', { className: 'asset-title' }, [
    editButton,
    el('div', { className: 'asset-info' }, [
      el('small', { className: 'media-kind', textContent: asset.kind + (asset.muted ? ' · muted' : '') }),
      el('strong', { textContent: filename(asset), title: asset.path }),
      ...(detail ? [el('small', { textContent: detail })] : []),
    ]),
  ]);
}

const glyph = (name) => el('span', { className: 'pi pi-' + name, ariaHidden: 'true' });

export function assetButton(ui, name, icon, action) {
  const button = ui.button('', action);
  button.className = 'asset-action';
  button.title = button.ariaLabel = name;
  button.append(glyph(icon));
  return button;
}

// Track the dragged DOM row locally. External drops and cancelled drags never edit the film.
function sortableLibrary(ui, list) {
  let source, target;
  function clearTarget() {
    if (target) delete target.dataset.drop;
    target = null;
  }
  function end() {
    clearTarget();
    if (source) delete source.dataset.dragging;
    source = null;
  }
  const move = (id, delta) =>
    ui.change((next) =>
      moveItem(
        next.assets,
        next.assets.findIndex((asset) => asset.id === id),
        delta,
      ),
    );
  list.onkeydown = (event) => {
    if (!event.target.closest('.asset-handle') || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    move(event.target.closest('[data-asset]').dataset.asset, event.key === 'ArrowUp' ? -1 : 1);
  };
  list.ondragstart = (event) => {
    const handle = event.target.closest('.asset-handle');
    if (!handle) return;
    handle.focus({ preventScroll: true });
    source = handle.closest('[data-asset]');
    source.dataset.dragging = '';
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/x-arisu-asset', source.dataset.asset);
    event.dataTransfer.setDragImage(source, 12, source.offsetHeight / 2);
  };
  list.ondragover = (event) => {
    if (!source) return;
    event.preventDefault();
    const row = event.target.closest('[data-asset]');
    if (row !== target) clearTarget();
    if (!row || row === source) return;
    const rect = row.getBoundingClientRect();
    target = row;
    row.dataset.drop = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after';
  };
  list.ondragleave = (event) => {
    if (!list.contains(event.relatedTarget)) clearTarget();
  };
  list.ondragend = end;
  list.ondrop = (event) => {
    if (!source) return;
    event.preventDefault();
    const id = source.dataset.asset;
    const dest = target?.dataset.asset;
    const after = target?.dataset.drop === 'after';
    end();
    if (!dest) return;
    ui.change((next) => {
      const from = next.assets.findIndex((asset) => asset.id === id);
      const to = next.assets.findIndex((asset) => asset.id === dest);
      if (from >= 0 && to >= 0) moveItem(next.assets, from, to - from + Number(after) - Number(from < to));
    });
  };
}

export function libraryView(ui, doc) {
  const rows = doc.assets.map((asset) => {
    const uses = doc.segments.flatMap((s, index) => (s.bindings.some((b) => b.asset_id === asset.id) ? [String(index + 1)] : []));
    const update = (key, value, refresh = true) =>
      ui.change((next) => {
        next.assets.find((a) => a.id === asset.id)[key] = value;
      }, refresh);
    const handle = el('button', {
      type: 'button',
      className: 'asset-action asset-handle',
      textContent: '⠿',
      draggable: true,
      disabled: doc.assets.length < 2,
      ariaLabel: 'Reorder ' + filename(asset),
      title: 'Drag to reorder, or use the up and down arrow keys',
    });
    handle.setAttribute('aria-keyshortcuts', 'ArrowUp ArrowDown');
    const mute = assetButton(ui, 'Mute asset', asset.muted ? 'ban' : 'circle-fill', () => update('muted', !asset.muted));
    mute.ariaPressed = String(asset.muted);
    mute.title = asset.muted ? 'Unmute asset' : 'Mute asset';
    mute.classList.add('mute');
    const actions = [assetButton(ui, 'Reselect asset', 'folder-open', () => browseAssets(ui, asset.id)), mute];
    if (asset.kind === 'video') {
      const sound = assetButton(ui, 'Include soundtrack', asset.include_audio ? 'volume-up' : 'volume-off', () =>
        update('include_audio', !asset.include_audio),
      );
      sound.ariaPressed = String(!!asset.include_audio);
      sound.title = asset.include_audio ? 'Exclude soundtrack' : 'Include soundtrack';
      actions.push(sound);
    }
    actions.push(
      assetButton(ui, 'Remove asset', 'times', () =>
        ui.change((next) => {
          next.assets = next.assets.filter((item) => item.id !== asset.id);
        }),
      ),
    );
    const card = el('article', { className: asset.muted ? 'card muted' : 'card', ariaLabel: filename(asset) }, [
      handle,
      mediaHeading(ui, asset, uses.length ? 'Used by segments ' + uses.join(', ') : 'Unbound'),
      ui.field('Asset Notes', asset.note, (value) => update('note', value, false)),
      el('div', { className: 'card-tools' }, actions),
    ]);
    card.dataset.kind = asset.kind;
    card.dataset.asset = asset.id;
    return card;
  });
  const list = el('div', { className: 'library' }, rows);
  sortableLibrary(ui, list);
  // A reviewed draft can be the first place an asset is bound. Restore its ID only on an explicit pick.
  const submitted = ui.state.run?.directorSubmission;
  const missing = new Set(
    [...doc.segments.flatMap((s) => s.bindings.map((b) => b.asset_id)), ...(submitted?.boundAssets ?? [])].filter(
      (id) => !doc.assets.some((a) => a.id === id),
    ),
  );
  return [
    ...(rows.length
      ? [list]
      : [el('p', { className: 'empty-library meta', textContent: 'Browse images, video or audio to add your first asset.' })]),
    ...[...missing].map((id) => {
      const original = submitted?.assets.get(id);
      const name = original ? `${original.path} (${id})` : id;
      return ui.button('Reselect missing asset ' + name, () => browseAssets(ui, id));
    }),
  ];
}

export function bindingView(ui, doc, segment) {
  const locate = (next) => next.segments.find((s) => s.id === segment.id).bindings;
  const rows = segment.bindings.map((b, i) => {
    const asset = doc.assets.find((a) => a.id === b.asset_id);
    const opts = asset?.kind === 'image' ? ['first', 'last', 'image'] : [asset?.kind ?? b.role];
    const override = ['clip', 'crop', 'include_audio'].some((k) => Object.hasOwn(b, k));
    const card = el('div', { className: asset?.muted ? 'binding card muted' : 'binding card' }, [
      asset ? mediaHeading(ui, asset, '', b, segment.id) : el('strong', { textContent: 'Missing asset ' + b.asset_id }),
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
    card.dataset.kind = asset?.kind ?? '';
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
    ui.button('Add to library…', () => browseAssets(ui), doc.assets.length >= 256),
  ]);
}
