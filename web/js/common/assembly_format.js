// Text for lengths, sizes and rates on the Assemble Video panel and its dialogs.

export function fileName(path) {
  return String(path ?? '')
    .split('/')
    .at(-1);
}

export function seconds(value) {
  return `${value.toFixed(2)} s`;
}

export function bytes(count) {
  if (count < 1024) return `${count} B`;
  if (count < 1024 ** 2) return `${Math.round(count / 1024)} KB`;
  const [unit, scale] = count < 1024 ** 3 ? ['MB', 1024 ** 2] : ['GB', 1024 ** 3];
  return `${(count / scale).toFixed(1)} ${unit}`;
}

export function kilohertz(rate) {
  const value = rate / 1000;
  return `${Number.isInteger(value) ? value : value.toFixed(1)} kHz`;
}

/** A frame rate pair as a short number: 24, 23.976. */
export function frameRate(fps) {
  const value = fps[0] / fps[1];
  return `${Number.isInteger(value) ? value : value.toFixed(3)} fps`;
}

/** The sound a description carries: its source and rate, or silence. */
export function audioLabel(audio) {
  if (!audio) return 'Silent';
  return `${audio.source === 'pcm' ? 'PCM' : 'Embedded'} ${kilohertz(audio.rate)}`;
}

/** A confirmed or suggested output specification on one line. */
export function specLabel(spec) {
  const sound = spec.sample_rate
    ? ` · ${kilohertz(spec.sample_rate)} ${spec.channels === 1 ? 'mono' : spec.channels === 2 ? 'stereo' : `${spec.channels} ch`}`
    : '';
  return `${spec.width}×${spec.height} · ${frameRate(spec.fps)}${sound}`;
}
