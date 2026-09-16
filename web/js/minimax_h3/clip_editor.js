// The clip editor of Resource Studio: a source-relative in/out selection on one timeline.
//
// `editClip(item, info, { signal })` opens a native <dialog> for the video or audio `item` described by the
// server's `info` (`duration`, `has_audio`, `revision`, ...) and resolves to `{ clip: { start, end } }`, plus
// `include_audio` for a video, or null when the dialog is cancelled. The selection is a draft until Apply, and
// playback never changes it. Every time sits on a tenth-of-a-second grid, the finest step the clip contract shows.
//
// The timeline is a ruler, the selected range between an in and an out bracket, and a playhead, laid out as
// percentages of the source length. Its pointer and key handlers only turn events into calls to the pure
// helpers below, so a drag can be replayed with plain objects. The media element has no native controls: the
// transport row, the timeline and its keys own playback, and an audio source shows no preview at all.
import { api } from '../../../../scripts/api.js';
import { closeOnBackdropClick, el } from '../common/dom.js';

const STYLE = `
.arisu-clip { --video: var(--arisu-video); --audio: var(--arisu-audio); --surface: var(--comfy-input-bg, #2a2a2a); --row: var(--comfy-menu-bg, #333);
  --line: var(--border-color, #444); --label: var(--descrip-text, #999); --text: var(--input-text, #ccc); --dim: var(--descrip-text, #999);
  --strong: var(--fg-color, #fff); --accent: var(--arisu-accent);
  width: min(880px, 94vw); max-height: 92vh; padding: 0; border: 1px solid var(--line); border-radius: 14px;
  background: var(--row); color: var(--text); font: 13px system-ui, sans-serif; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55);
  overflow: hidden; }
.arisu-clip.video { --kind: var(--video); }
.arisu-clip.audio { --kind: var(--audio); }
.arisu-clip[open] { display: flex; flex-direction: column; animation: arisu-clip-enter 160ms ease-out; }
.arisu-clip[open]::backdrop { background: rgba(0, 0, 0, 0.55); backdrop-filter: blur(3px); }
.arisu-clip :where(button, input, select) { font: inherit; color: inherit; border: 1px solid var(--line); border-radius: 8px;
  background: var(--surface); transition: background-color 150ms ease, border-color 150ms ease; }
.arisu-clip :where(button) { min-height: 34px; padding: 6px 12px; cursor: pointer; }
.arisu-clip :where(input, select) { padding: 6px 10px; }
.arisu-clip button:enabled:hover { border-color: var(--accent); }
.arisu-clip :disabled { opacity: 0.45; cursor: default; }
.arisu-clip :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.arisu-clip :where(input, select):focus-visible { outline: none; border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.arisu-clip-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
.arisu-clip-head h3 { margin: 0; min-width: 0; font-size: 14px; font-weight: 600; color: var(--strong); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.arisu-clip-badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.04em; color: #111; background: var(--kind); }
.arisu-clip-length { margin-left: auto; color: var(--label); font-variant-numeric: tabular-nums; white-space: nowrap; }
.arisu-clip-stage { background: #000; line-height: 0; }
.arisu-clip-stage video { display: block; width: 100%; max-height: 42vh; object-fit: contain; cursor: pointer; }
.arisu-clip audio[hidden] { display: none; }
.arisu-clip-transport { display: flex; align-items: center; gap: 6px; padding: 12px 16px 0; }
.arisu-clip-transport button { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 32px;
  padding: 0; }
.arisu-clip-transport svg { width: 16px; height: 16px; fill: currentColor; }
.arisu-clip-play { border-color: var(--accent); }
.arisu-clip-time { margin-left: auto; color: var(--label); font-variant-numeric: tabular-nums; white-space: nowrap; }
.arisu-clip-timeline { position: relative; margin: 10px 16px 0; border: 1px solid var(--line); border-radius: 8px;
  background: var(--surface); overflow: hidden; touch-action: none; user-select: none; cursor: crosshair; }
.arisu-clip-ruler { position: relative; height: 24px; border-bottom: 1px solid var(--line); }
.arisu-clip-tick { position: absolute; bottom: 0; width: 1px; height: 5px; background: var(--dim); }
.arisu-clip-tick.major { height: 10px; background: var(--label); }
.arisu-clip-tick-label { position: absolute; left: 4px; bottom: 9px; font-size: 10px; line-height: 1; color: var(--label);
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.arisu-clip-tick-label.last { left: auto; right: 4px; }
.arisu-clip-track { position: relative; height: 52px; background: color-mix(in srgb, var(--kind) 10%, transparent); }
.arisu-clip-range { position: absolute; top: 0; bottom: 0; box-sizing: border-box; border-top: 2px solid var(--kind);
  border-bottom: 2px solid var(--kind); background: color-mix(in srgb, var(--kind) 35%, transparent); cursor: grab; }
.arisu-clip-range:active { cursor: grabbing; }
.arisu-clip-bracket { position: absolute; top: 0; bottom: 0; width: 10px; box-sizing: border-box; border: 3px solid var(--strong);
  cursor: ew-resize; }
.arisu-clip-bracket.in { border-right: 0; border-radius: 3px 0 0 3px; }
.arisu-clip-bracket.out { border-left: 0; border-radius: 0 3px 3px 0; transform: translateX(-100%); }
.arisu-clip-playhead { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--accent);
  pointer-events: none; }
.arisu-clip-playhead::after { content: ''; position: absolute; top: 0; left: -7px; width: 14px; height: 12px;
  border-radius: 3px 3px 0 0; background: var(--accent); pointer-events: auto; cursor: ew-resize; }
.arisu-clip-playhead::before { content: ''; position: absolute; top: 12px; left: -7px; border: 7px solid transparent;
  border-top: 9px solid var(--accent); border-bottom: 0; pointer-events: auto; cursor: ew-resize; }
.arisu-clip-settings { display: flex; flex-direction: column; gap: 10px; padding: 12px 16px; }
.arisu-clip-fields, .arisu-clip-options { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; }
.arisu-clip label { display: inline-flex; align-items: center; gap: 6px; color: var(--label); }
.arisu-clip input[type=number] { width: 84px; font-variant-numeric: tabular-nums; }
.arisu-clip input[type=checkbox] { margin: 0; accent-color: var(--accent); }
.arisu-clip-presets { display: inline-flex; gap: 6px; }
.arisu-clip-chip { padding: 4px 12px; border-radius: 999px; }
.arisu-clip-chip[aria-pressed='true'] { background: var(--kind); border-color: var(--kind); color: #111; }
.arisu-clip-status { min-height: 1.2em; color: var(--label); }
.arisu-clip-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--line); }
.arisu-clip-apply { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 25%, var(--surface)); }
@keyframes arisu-clip-enter { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
@media (prefers-reduced-motion: reduce) {
  .arisu-clip, .arisu-clip::backdrop, .arisu-clip * { animation: none !important; transition: none !important; }
}
`;

/** Transport glyphs, constant markup like the browser's kind icons. */
const ICONS = {
  toIn: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3h2v10H3zM13 3v10L6 8z"/></svg>',
  play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z"/></svg>',
  pause: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 3h3v10H4zM9 3h3v10H9z"/></svg>',
  toOut: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11 3h2v10h-2zM3 3v10l7-5z"/></svg>',
  setIn: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3H5v10h5v-2H7V5h3z"/></svg>',
  setOut: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h5v10H6v-2h3V5H6z"/></svg>',
};
/** The grid every time sits on: a tenth of a second, the finest step the clip contract shows. */
const GRID = 0.1;
/** Candidate ruler steps; the finest one that keeps the labelled ticks readable is used. */
const TICK_STEPS = [0.1, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
const MAX_MAJORS = 12;
const MINORS_PER_MAJOR = 5;

const tenth = (value) => Math.round(value * 10) / 10;
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
/** `value` on the snapping `grid`, then on the tenth grid. */
const snapTime = (value, grid) => tenth(Math.round(value / grid) * grid);

/** The pointer's place in source seconds on the grid, held inside the timeline; a timeline without layout reads as its origin. */
function timeAt(event, rect, limit, grid) {
  if (!rect.width) return 0;
  return clamp(snapTime(((event.clientX - rect.left) / rect.width) * limit, grid), 0, limit);
}

/** `range` shifted by `delta` seconds on the grid, its length kept, held inside the source. */
function moveRange(range, delta, limit, grid) {
  const length = tenth(range.end - range.start);
  const start = clamp(snapTime(range.start + delta, grid), 0, tenth(limit - length));
  return { start, end: tenth(start + length) };
}

const tickStep = (limit) => TICK_STEPS.find((step) => limit / step <= MAX_MAJORS) ?? TICK_STEPS.at(-1);

/** Ruler ticks through `limit`: one every fifth of `step`, the ones on the step labelled. */
function ticks(limit, step) {
  const result = [];
  for (let index = 0; ; index += 1) {
    const time = Math.round((index * step * 1000) / MINORS_PER_MAJOR) / 1000;
    if (time > limit + 1e-9) break;
    result.push({ time, major: index % MINORS_PER_MAJOR === 0 });
  }
  return result;
}

/** `m:ss`, with the tenth when asked: `0:05`, `1:02.5`. */
function timecode(seconds, withTenth) {
  const value = tenth(seconds);
  const whole = Math.floor(value + 1e-9);
  const text = `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
  return withTenth ? `${text}.${Math.round((value - whole) * 10)}` : text;
}

/** A place on the timeline as a percentage of `limit`, to a thousandth. */
const pct = (time, limit) => `${limit ? Math.round((time / limit) * 100000) / 1000 : 0}%`;

export function editClip(item, info, options = {}) {
  const video = info.kind === 'video';
  const limit = Math.floor(info.duration * 10) / 10;
  let start = Math.min(tenth(item.clip?.start ?? 0), limit);
  let end = Math.min(tenth(item.clip?.end ?? 5), limit);
  let committed = null;
  let proxy = null;
  let converting = false;
  let closed = false;
  let playbackOrigin = 0;
  let drag = null;
  const controller = new AbortController();
  const invoking = document.activeElement;
  const player = el(video ? 'video' : 'audio', { preload: 'metadata', ...(video ? { onclick: togglePlay } : { hidden: true }) });
  player.onloadedmetadata = () => {
    playbackOrigin = proxy ? 0 : player.seekable?.length ? player.seekable.start(0) : 0;
  };
  const position = () => (player.currentTime || 0) - playbackOrigin;
  const seek = (time) => {
    player.currentTime = time + playbackOrigin;
  };
  const grid = () => Number(snap.value);
  const status = el('output', { className: 'arisu-clip-status', ariaLive: 'polite' });
  const readout = el('output', { className: 'arisu-clip-time' });
  const field = (ariaLabel, value, min = '0') =>
    el('input', { type: 'number', min, max: String(limit), step: '0.1', value: String(value), ariaLabel });
  const startField = field('Start Seconds', start);
  const endField = field('End Seconds', end);
  const duration = field('Duration Seconds', tenth(end - start), '0.1');
  const locked = el('input', { type: 'checkbox', ariaLabel: 'Lock Duration' });
  const snap = el(
    'select',
    { ariaLabel: 'Snapping' },
    [
      ['0.1', '0.1 s'],
      ['1', '1 s'],
    ].map(([value, textContent]) => el('option', { value, textContent })),
  );
  snap.value = '0.1';
  const loop = el(
    'select',
    { ariaLabel: 'Selection End Behavior' },
    [
      ['stop', 'Stop'],
      ['loop', 'Loop'],
    ].map(([value, textContent]) => el('option', { value, textContent })),
  );
  const selectedOnly = el('input', { type: 'checkbox', ariaLabel: 'Play Selection Only', checked: true });
  const include = el('input', {
    type: 'checkbox',
    ariaLabel: 'Include Audio',
    checked: video && info.has_audio && item.include_audio !== false,
    disabled: !info.has_audio,
  });
  const chips = [5, 10, 15].map((seconds) =>
    el('button', {
      className: 'arisu-clip-chip',
      textContent: `${seconds}s`,
      disabled: seconds > limit,
      onclick: () => {
        locked.checked = true;
        duration.value = String(seconds);
        change('start', start);
      },
    }),
  );
  const step = tickStep(limit);
  const ruler = el(
    'div',
    { className: 'arisu-clip-ruler' },
    ticks(limit, step).map(({ time, major }) => {
      const tick = el(
        'div',
        { className: `arisu-clip-tick${major ? ' major' : ''}` },
        major
          ? [
              el('span', {
                className: `arisu-clip-tick-label${time + step > limit + 1e-9 ? ' last' : ''}`,
                textContent: timecode(time, step < 1),
              }),
            ]
          : [],
      );
      tick.style.left = pct(time, limit);
      return tick;
    }),
  );
  const range = el('div', { className: 'arisu-clip-range', handle: 'range', title: 'Selection' });
  const inBracket = el('div', { className: 'arisu-clip-bracket in', handle: 'start', title: 'In' });
  const outBracket = el('div', { className: 'arisu-clip-bracket out', handle: 'end', title: 'Out' });
  const playhead = el('div', { className: 'arisu-clip-playhead', handle: 'playhead', title: 'Playhead' });
  const timeline = el(
    'div',
    {
      className: 'arisu-clip-timeline',
      tabIndex: 0,
      role: 'slider',
      ariaLabel: 'Timeline',
      autofocus: true,
      onpointerdown,
      onpointermove,
      onpointerup,
      onpointercancel: onpointerup,
      onkeydown,
    },
    [ruler, el('div', { className: 'arisu-clip-track' }, [range, inBracket, outBracket]), playhead],
  );
  const iconButton = (ariaLabel, icon, onclick, className = '') => {
    const button = el('button', { className, ariaLabel, title: ariaLabel, onclick });
    button.innerHTML = icon;
    return button;
  };
  const playButton = iconButton('Play or Pause', ICONS.play, togglePlay, 'arisu-clip-play');
  const apply = el('button', {
    className: 'arisu-clip-apply',
    textContent: 'Apply',
    onclick: () => {
      if (!valid()) return;
      committed = { clip: { start, end }, ...(video ? { include_audio: include.checked } : {}) };
      dialog.close();
    },
  });
  const retry = el('button', {
    textContent: 'Retry Playback',
    hidden: true,
    onclick: () => {
      retry.hidden = true;
      void proxyPlayback();
    },
  });
  const label = (text, input) => el('label', {}, [el('span', { textContent: text }), input]);
  const check = (input, text) => el('label', {}, [input, el('span', { textContent: text })]);
  const dialog = el('dialog', { className: `arisu-clip ${info.kind}` }, [
    el('style', { textContent: STYLE }),
    el('header', { className: 'arisu-clip-head' }, [
      el('h3', { textContent: item.path.split('/').at(-1), title: item.path }),
      el('span', { className: 'arisu-clip-badge', textContent: video ? 'Video' : 'Audio' }),
      el('span', { className: 'arisu-clip-length', textContent: timecode(limit, true), title: 'Source Length' }),
    ]),
    ...(video ? [el('div', { className: 'arisu-clip-stage' }, [player])] : [player]),
    el('div', { className: 'arisu-clip-transport' }, [
      iconButton('Go to In', ICONS.toIn, () => scrub(start)),
      playButton,
      iconButton('Go to Out', ICONS.toOut, () => scrub(end)),
      iconButton('Set In', ICONS.setIn, markIn),
      iconButton('Set Out', ICONS.setOut, markOut),
      readout,
    ]),
    timeline,
    el('section', { className: 'arisu-clip-settings' }, [
      el('div', { className: 'arisu-clip-fields' }, [
        label('In', startField),
        label('Out', endField),
        label('Duration', duration),
        check(locked, 'Lock Duration'),
        el('div', { className: 'arisu-clip-presets' }, chips),
      ]),
      el('div', { className: 'arisu-clip-options' }, [
        label('Snap', snap),
        label('At Out', loop),
        check(selectedOnly, 'Play Selection Only'),
        ...(video && info.has_audio ? [check(include, 'Include Audio')] : []),
      ]),
      status,
      retry,
    ]),
    el('footer', { className: 'arisu-clip-foot' }, [el('button', { textContent: 'Cancel', onclick: () => dialog.close() }), apply]),
  ]);
  closeOnBackdropClick(dialog);
  function valid() {
    const length = Number(duration.value);
    const lockedValid =
      !locked.checked ||
      (Number.isFinite(length) &&
        length > 0 &&
        length <= info.duration &&
        Math.abs(length * 10 - Math.round(length * 10)) < 1e-8 &&
        Math.abs(end - start - length) < 1e-8);
    return lockedValid && Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start && end <= info.duration;
  }
  /** The selection: fields, chips, the range and its brackets. */
  function showSelection() {
    startField.value = String(start);
    endField.value = String(end);
    if (!locked.checked) duration.value = String(tenth(end - start));
    for (const chip of chips) chip.ariaPressed = String(locked.checked && Number(duration.value) === Number.parseFloat(chip.textContent));
    range.style.left = pct(start, limit);
    range.style.width = pct(end - start, limit);
    inBracket.style.left = pct(start, limit);
    outBracket.style.left = pct(end, limit);
    apply.disabled = !valid();
  }
  /** The playhead and the readout, on every clock tick. */
  function showPlayhead() {
    const now = clamp(tenth(position()), 0, limit);
    playhead.style.left = pct(now, limit);
    timeline.ariaValueNow = String(now);
    timeline.ariaValueText = timecode(now, true);
    readout.textContent = `${timecode(now, true)} / ${timecode(limit, true)} · in ${timecode(start, true)} · out ${timecode(end, true)}`;
  }
  function show() {
    showSelection();
    showPlayhead();
  }
  /** Move one edge to `value` on the grid; a locked duration carries the other edge, an unlocked one never crosses it. */
  function change(which, value) {
    const next = snapTime(Number(value), grid());
    if (!Number.isFinite(next)) {
      show();
      return;
    }
    if (locked.checked) {
      const length = Number(duration.value);
      if (!Number.isFinite(length) || length <= 0 || length > limit || Math.abs(length * 10 - Math.round(length * 10)) > 1e-8) {
        status.textContent = 'A locked duration must fit the source and use at most one decimal.';
        apply.disabled = true;
        return;
      }
      start = tenth(clamp(which === 'end' ? next - length : next, 0, limit - length));
      end = tenth(start + length);
    } else if (which === 'start') {
      start = clamp(next, 0, tenth(end - GRID));
    } else {
      end = clamp(next, tenth(start + GRID), limit);
    }
    status.textContent = '';
    show();
  }
  function place(next) {
    start = next.start;
    end = next.end;
    status.textContent = '';
    show();
  }
  function scrub(time) {
    seek(clamp(tenth(time), 0, limit));
    showPlayhead();
  }
  function markIn() {
    change('start', position());
  }
  function markOut() {
    change('end', position());
  }
  function togglePlay() {
    if (player.paused) player.play().catch(() => {});
    else player.pause();
  }
  function applyDrag(time) {
    if (drag.handle === 'start' || drag.handle === 'end') change(drag.handle, time);
    else if (drag.handle === 'range') place(moveRange(drag.origin, time - drag.at, limit, grid()));
    else scrub(time);
  }
  function onpointerdown(event) {
    if (event.button) return; // the primary button only
    const time = timeAt(event, timeline.getBoundingClientRect(), limit, grid());
    drag = { handle: event.target?.handle ?? 'playhead', at: time, origin: { start, end } };
    timeline.setPointerCapture?.(event.pointerId);
    applyDrag(time);
  }
  function onpointermove(event) {
    if (drag) applyDrag(timeAt(event, timeline.getBoundingClientRect(), limit, grid()));
  }
  function onpointerup() {
    drag = null;
  }
  function onkeydown(event) {
    const nudge = event.shiftKey ? 1 : GRID;
    const actions = {
      ' ': togglePlay,
      i: markIn,
      I: markIn,
      o: markOut,
      O: markOut,
      ArrowLeft: () => scrub(position() - nudge),
      ArrowRight: () => scrub(position() + nudge),
      Home: () => scrub(0),
      End: () => scrub(limit),
    };
    const action = actions[event.key];
    if (!action) return;
    event.preventDefault?.();
    action();
  }
  startField.onchange = () => change('start', startField.value);
  endField.onchange = () => change('end', endField.value);
  duration.onchange = () => (locked.checked ? change('start', start) : change('end', start + Number(duration.value)));
  locked.onchange = () => {
    if (locked.checked) change('start', start);
    else show();
  };
  snap.onchange = () => change('start', start);
  const animate = () => {
    if (closed || player.paused) return;
    enforce();
    requestAnimationFrame(animate);
  };
  player.onplay = () => {
    playButton.innerHTML = ICONS.pause;
    if (selectedOnly.checked && (position() < start || position() >= end)) seek(start);
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(animate);
  };
  player.onpause = () => {
    playButton.innerHTML = ICONS.play;
  };
  const enforce = () => {
    if (closed) return;
    if (selectedOnly.checked && !player.paused && position() >= end) {
      if (loop.value === 'loop') {
        seek(start);
      } else {
        player.pause();
        seek(end);
      }
    }
    showPlayhead();
  };
  player.ontimeupdate = enforce;
  player.onseeked = enforce;
  player.onended = () => {
    if (selectedOnly.checked && loop.value === 'loop') {
      seek(start);
      player.play().catch(() => {});
    }
  };
  async function releaseProxy() {
    if (proxy) {
      const id = proxy;
      proxy = null;
      await api.fetchApi(`/arisu/resources/proxy/${id}`, { method: 'DELETE' }).catch(() => {});
    }
  }
  async function proxyPlayback() {
    if (converting || closed) return;
    converting = true;
    try {
      await releaseProxy();
      const check = await api.fetchApi(`/arisu/resources/metadata?${new URLSearchParams({ root: item.root, path: item.path })}`, {
        signal: controller.signal,
      });
      const current = await check.json();
      if (!check.ok) throw new Error(current.error || 'Source is unavailable');
      if (current.revision !== info.revision) throw new Error('Source changed; reselect it.');
      status.textContent = 'Preparing playback…';
      const response = await api.fetchApi('/arisu/resources/proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: item.root, path: item.path, revision: info.revision }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Playback conversion unavailable');
      proxy = data.id;
      if (closed) {
        await releaseProxy();
        return;
      }
      while (!closed) {
        const response = await api.fetchApi(`/arisu/resources/proxy/${proxy}`, { signal: controller.signal });
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || 'Playback unavailable');
        if (job.state === 'ready') {
          player.src = api.apiURL(job.url);
          player.load();
          status.textContent = '';
          break;
        }
        if (job.state !== 'running') throw new Error(job.error || 'Playback conversion failed');
        status.textContent = `Preparing playback ${job.progress}%`;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    } catch (error) {
      if (!closed) {
        status.textContent = error.message;
        retry.hidden = false;
      }
    } finally {
      converting = false;
    }
  }
  player.onerror = () => {
    // MEDIA_ERR_DECODE / SRC_NOT_SUPPORTED only; network failures never transcode.
    if (!proxy && [3, 4].includes(player.error?.code)) void proxyPlayback();
    else {
      status.textContent = 'Playback failed. Check that the source is available.';
      retry.hidden = false;
    }
  };
  player.src = api.apiURL(`/arisu/resources/view?${new URLSearchParams({ root: item.root, path: item.path })}`);
  return new Promise((resolve) => {
    dialog.onclose = () => {
      closed = true;
      controller.abort();
      player.pause();
      player.removeAttribute('src');
      player.load();
      void releaseProxy();
      dialog.remove();
      invoking?.focus?.();
      resolve(committed);
    };
    document.body.append(dialog);
    dialog.showModal();
    show();
    options.signal?.addEventListener('abort', () => dialog.close(), { once: true });
    if (options.signal?.aborted) dialog.close();
  });
}
