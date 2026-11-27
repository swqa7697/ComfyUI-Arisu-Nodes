import { resourceId } from '../common/shared.js';

// Film document helpers for editing and review. Execution validates the same contract on the host.
const DEFAULT_FILM = {
  brief: '',
  aspect_ratio: '16:9 (Widescreen)',
  megapixels: 1,
  min_seconds: 5,
  max_seconds: 15,
  target_runtime: '',
  writing_skill: '',
  frame_picture_tags: 'after_refs',
};
export const ASPECTS = [
  '1:1 (Square)',
  '2:3 (Portrait Photo)',
  '3:2 (Photo)',
  '3:4 (Portrait Standard)',
  '4:3 (Standard)',
  '9:16 (Portrait Widescreen)',
  '16:9 (Widescreen)',
  '21:9 (Ultrawide)',
];

export function emptyPlan() {
  return { outline: '', continuity: '', coverage: {}, segments: [], selected: '' };
}

export function readDocument(text) {
  const doc = text ? JSON.parse(text) : { version: 1 };
  if (doc?.version !== 1) throw new Error('Unsupported Director film document.');
  const result = {
    ...emptyPlan(),
    assets: [],
    ...doc,
    film: { ...DEFAULT_FILM, ...doc.film },
  };
  const { requirements = [], triggers = '', continuity = '', ...film } = result.film;
  if (
    typeof film.brief !== 'string' ||
    typeof triggers !== 'string' ||
    typeof continuity !== 'string' ||
    !Array.isArray(requirements) ||
    requirements.some((item) => typeof item !== 'string') ||
    !Array.isArray(result.assets) ||
    result.assets.some((asset) => typeof asset?.path !== 'string' || typeof asset.id !== 'string') ||
    !Array.isArray(result.segments) ||
    result.segments.some(
      (segment) =>
        typeof segment?.id !== 'string' ||
        !Array.isArray(segment.bindings) ||
        segment.bindings.some((binding) => typeof binding?.asset_id !== 'string'),
    ) ||
    !result.coverage ||
    typeof result.coverage !== 'object' ||
    Object.values(result.coverage).some((ids) => !Array.isArray(ids))
  )
    throw new Error('Invalid Director film document.');
  // Match the host default in saved films that predate the soundtrack switch.
  for (const asset of result.assets) if (asset.kind === 'video' && !Object.hasOwn(asset, 'include_audio')) asset.include_audio = true;
  // Match the host migration. Keep the original text and strip legacy keys so subsequent reads are idempotent.
  film.brief = [
    film.brief,
    requirements.length && 'Required story elements:\n' + requirements.join('\n'),
    triggers && 'Trigger words:\n' + triggers,
    continuity && 'Continuity:\n' + continuity,
  ]
    .filter(Boolean)
    .join('\n\n');
  result.film = film;
  // Saved films from before a full reset can still carry the old plan beside an empty sequence.
  return result.segments.length ? result : Object.assign(result, emptyPlan());
}

export function clearLocations(text) {
  try {
    const doc = readDocument(text);
    doc.uid = resourceId();
    doc.assets = [];
    // Overrides are tied to the selected source. Require a fresh crop or clip after reselection.
    for (const segment of doc.segments) {
      segment.uid = resourceId();
      segment.bindings = segment.bindings.map(({ asset_id, role }) => ({ asset_id, role }));
    }
    return JSON.stringify(doc);
  } catch {
    return JSON.stringify(readDocument());
  }
}

export function timing(film, seconds) {
  const { min_seconds: min, max_seconds: max } = film;
  if (!Number.isFinite(min) || !Number.isFinite(max) || !Number.isFinite(seconds) || min < 0.2 || max > 150 || max < min) return null;

  // Preview the host's frames_for_duration: round to the nearest frame (ties to even), then snap upward on the H3 grid.
  const requested = Math.max(min, Math.min(max, seconds)) * 24;
  const lower = Math.floor(requested);
  const frames = requested - lower === 0.5 && lower % 2 === 0 ? lower : Math.round(requested);
  return 5 + 17 * Math.max(0, Math.ceil((frames - 5) / 17));
}

export function timeline(doc) {
  let end = 0;
  return doc.segments.map((segment, index) => {
    const frames = timing(doc.film, segment.seconds);
    const overlap = index && segment.transition === 'continuation' ? segment.overlap_frames : 0;
    const start = end;
    end += (frames ?? 0) - overlap;
    return { frames, start, end, outside: segment.seconds < doc.film.min_seconds || segment.seconds > doc.film.max_seconds || !frames };
  });
}

export const bindingKind = (role) => (role === 'first' || role === 'last' ? 'image' : role);

export function orderedTags(doc, segment, assets = new Map(doc.assets.map((asset) => [asset.id, asset]))) {
  const active = segment.bindings.filter((binding) => {
    const asset = assets.get(binding.asset_id);
    return asset && !asset.muted;
  });
  const byRole = (role) => active.filter((binding) => binding.role === role);
  const keys = [...byRole('first'), ...byRole('last')];
  const refs = byRole('image');
  const videos = byRole('video');
  const sound = videos.filter((b) => b.include_audio ?? assets.get(b.asset_id).include_audio);
  return {
    Picture:
      doc.film.frame_picture_tags === 'after_refs'
        ? [...refs, ...keys]
        : doc.film.frame_picture_tags === 'before_refs'
          ? [...keys, ...refs]
          : refs,
    Video: videos,
    Audio: [...sound, ...byRole('audio')],
  };
}

export function stableTags(doc, segment, prompt) {
  const ordered = orderedTags(doc, segment);
  return prompt.replace(/<(Picture|Video|Audio)\s+(\d+)>/g, (tag, kind, n) => {
    const binding = ordered[kind][Number(n) - 1];
    return binding ? '<' + kind + ':' + binding.asset_id + '>' : tag;
  });
}

export function secondsLabel(frames) {
  return Number((frames / 24).toFixed(2)) + ' s';
}
