// Film document helpers for editing and review. Execution validates the same contract on the host.
const DEFAULT_FILM = {
  brief: '',
  requirements: [],
  triggers: '',
  continuity: '',
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

export function readDocument(text) {
  const doc = text ? JSON.parse(text) : { version: 1 };
  if (doc?.version !== 1) throw new Error('Unsupported Director film document.');
  const result = {
    outline: '',
    continuity: '',
    coverage: {},
    assets: [],
    segments: [],
    selected: '',
    ...doc,
    film: { ...DEFAULT_FILM, ...doc.film },
  };
  if (
    !Array.isArray(result.film.requirements) ||
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
  return result;
}

export function clearLocations(text) {
  try {
    const doc = readDocument(text);
    doc.assets = [];
    // Overrides are tied to the selected source. Require a fresh crop or clip after reselection.
    for (const segment of doc.segments) {
      segment.bindings = segment.bindings.map(({ asset_id, role }) => ({ asset_id, role }));
    }
    return JSON.stringify(doc);
  } catch {
    return JSON.stringify(readDocument());
  }
}

export function timing(film, seconds) {
  const low = Math.max(0, Math.ceil((film.min_seconds * 24 - 5) / 17));
  const high = Math.floor((film.max_seconds * 24 - 5) / 17);

  if (
    !Number.isFinite(low) ||
    !Number.isFinite(high) ||
    high < low ||
    !Number.isFinite(seconds) ||
    film.min_seconds < 0.2 ||
    film.max_seconds > 150 ||
    film.max_seconds < film.min_seconds
  )
    return null;
  return 5 + 17 * Math.max(low, Math.min(high, Math.round((seconds * 24 - 5) / 17)));
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

export function orderedTags(doc, segment) {
  const byRole = (role) =>
    segment.bindings.filter((b) => b.role === role && doc.assets.some((asset) => asset.id === b.asset_id && !asset.muted));
  const keys = [...byRole('first'), ...byRole('last')];
  const refs = byRole('image');
  const videos = byRole('video');
  const sound = videos.filter((b) => b.include_audio ?? doc.assets.find((asset) => asset.id === b.asset_id)?.include_audio);
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
  return prompt.replace(/<(Picture|Video|Audio) (\d+)>/g, (tag, kind, n) => {
    const binding = ordered[kind][Number(n) - 1];
    return binding ? '<' + kind + ':' + binding.asset_id + '>' : tag;
  });
}

export function secondsLabel(frames) {
  return Number((frames / 24).toFixed(2)) + ' s';
}
