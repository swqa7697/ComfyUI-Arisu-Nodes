// Transactional source-relative clip editor. Playback never changes the saved selection.
import { api } from '../../../../scripts/api.js';
import { closeOnBackdropClick, el } from '../common/dom.js';

const STYLE = `
.arisu-clip { width:min(860px,94vw); max-height:90vh; overflow:auto; border:1px solid var(--border-color,#555); border-radius:12px;
 background:var(--comfy-menu-bg,#222); color:var(--fg-color,#eee); padding:16px; font:14px system-ui; }
.arisu-clip::backdrop { background:#0009; }
.arisu-clip video { width:100%; max-height:45vh; object-fit:contain; background:#000; }
.arisu-clip audio { width:100%; }
.arisu-clip .controls {display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:12px 0;}
.arisu-clip label {display:flex;gap:6px;align-items:center;}
.arisu-clip input[type=number] {width:100px;}
.arisu-clip :where(button,input,select) {font:inherit;color:inherit;background:var(--comfy-input-bg,#333);border:1px solid var(--border-color,#555);border-radius:5px;padding:7px;}
.arisu-clip button {min-height:36px;cursor:pointer;} .arisu-clip :disabled {opacity:.45;}
.arisu-clip :focus-visible {outline:2px solid var(--p-primary-color,#7fd1c1);outline-offset:2px;}
.arisu-clip .timeline {padding:10px 0;} .arisu-clip input[type=range] {width:100%;box-sizing:border-box;accent-color:var(--p-primary-color,#7fd1c1);}
.arisu-clip output {display:block;font-variant-numeric:tabular-nums;} .arisu-clip .error {color:var(--error-text,#ff9999);}
@media(prefers-reduced-motion:no-preference){.arisu-clip[open]{animation:arisu-clip-enter 150ms ease-out;}@keyframes arisu-clip-enter{from{opacity:0;transform:translateY(6px);}}}
`;

export function editClip(item, info, options = {}) {
  let start = item.clip?.start ?? 0;
  let end = item.clip?.end ?? Math.min(5, info.duration);
  let committed = null;
  let proxy = null;
  let converting = false;
  let closed = false;
  let playbackOrigin = 0;
  const controller = new AbortController();
  const invoking = document.activeElement;
  const player = el(info.kind === 'video' ? 'video' : 'audio', { controls: true, preload: 'metadata' });
  player.onloadedmetadata = () => {
    playbackOrigin = proxy ? 0 : player.seekable?.length ? player.seekable.start(0) : 0;
  };
  const position = () => (player.currentTime || 0) - playbackOrigin;
  const seek = (time) => {
    player.currentTime = time + playbackOrigin;
  };
  const status = el('output', { ariaLive: 'polite' });
  const readout = el('output');
  const startField = el('input', {
    type: 'number',
    min: '0',
    max: String(info.duration),
    step: 'any',
    value: String(start),
    ariaLabel: 'Start seconds',
  });
  const endField = el('input', {
    type: 'number',
    min: '0',
    max: String(info.duration),
    step: 'any',
    value: String(end),
    ariaLabel: 'End seconds',
  });
  const fixed = el('input', { type: 'checkbox', ariaLabel: 'Fixed duration' });
  const duration = el('input', {
    type: 'number',
    min: '0.1',
    step: '0.1',
    value: String(Math.round((end - start) * 10) / 10),
    ariaLabel: 'Fixed duration seconds',
    disabled: true,
  });
  const snap = el(
    'select',
    { ariaLabel: 'Snapping' },
    [
      ['0.1', '0.1 second'],
      ['1', 'Second'],
      ['0', 'Free'],
    ].map(([value, textContent]) => el('option', { value, textContent })),
  );
  snap.value = '0.1';
  const selectedOnly = el('input', { type: 'checkbox', checked: true });
  const loop = el(
    'select',
    { ariaLabel: 'Selection end behavior' },
    ['stop', 'loop'].map((value) => el('option', { value, textContent: value })),
  );
  const include = el('input', { type: 'checkbox', checked: info.has_audio && item.include_audio !== false, disabled: !info.has_audio });
  const startHandle = el('input', { type: 'range', min: '0', max: String(info.duration), step: '0.001', ariaLabel: 'Selection start' });
  const endHandle = el('input', { type: 'range', min: '0', max: String(info.duration), step: '0.001', ariaLabel: 'Selection end' });
  const playhead = el('input', { type: 'range', min: '0', max: String(info.duration), step: '0.001', value: '0', ariaLabel: 'Playhead' });
  const apply = el('button', {
    textContent: 'Apply',
    onclick: () => {
      if (!valid()) return;
      committed = { clip: { start, end }, ...(info.kind === 'video' ? { include_audio: include.checked } : {}) };
      dialog.close();
    },
  });
  const retry = el('button', {
    textContent: 'Retry playback',
    hidden: true,
    onclick: () => {
      retry.hidden = true;
      void proxyPlayback();
    },
  });
  const label = (text, input) => el('label', {}, [el('span', { textContent: text }), input]);
  const dialog = el('dialog', { className: 'arisu-clip' }, [
    el('style', { textContent: STYLE }),
    el('h3', { textContent: item.path.split('/').at(-1) }),
    player,
    el('div', { className: 'timeline' }, [readout, playhead, startHandle, endHandle]),
    el('div', { className: 'controls' }, [label('Start', startField), label('End', endField), label('Snap', snap)]),
    el('div', { className: 'controls' }, [
      label('Fixed duration', fixed),
      duration,
      ...[5, 10, 15].map((seconds) =>
        el('button', {
          textContent: `${seconds}s`,
          disabled: seconds > info.duration,
          onclick: () => {
            fixed.checked = true;
            duration.disabled = false;
            duration.value = String(seconds);
            change('start', start);
          },
        }),
      ),
    ]),
    el('div', { className: 'controls' }, [
      label('Play selection', selectedOnly),
      loop,
      ...(info.kind === 'video' ? [label(info.has_audio ? 'Include Audio' : 'No soundtrack', include)] : []),
    ]),
    status,
    retry,
    el('div', { className: 'controls' }, [el('button', { textContent: 'Cancel', onclick: () => dialog.close() }), apply]),
  ]);
  closeOnBackdropClick(dialog);
  function valid() {
    const length = Number(duration.value);
    const fixedValid =
      !fixed.checked ||
      (Number.isFinite(length) &&
        length > 0 &&
        length <= info.duration &&
        Math.abs(length * 10 - Math.round(length * 10)) < 1e-8 &&
        Math.abs(end - start - length) < 1e-8);
    return fixedValid && Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start && end <= info.duration;
  }
  function show() {
    startField.value = String(start);
    endField.value = String(end);
    startHandle.value = String(start);
    endHandle.value = String(end);
    readout.textContent = `${position().toFixed(2)} / ${info.duration.toFixed(2)}s · selection ${start.toFixed(3)}–${end.toFixed(3)}s`;
    startHandle.style.background = `linear-gradient(to right, transparent ${(start / info.duration) * 100}%, var(--p-primary-color,#7fd1c1) ${(start / info.duration) * 100}%, var(--p-primary-color,#7fd1c1) ${(end / info.duration) * 100}%, transparent ${(end / info.duration) * 100}%)`;
    apply.disabled = !valid();
  }
  function change(which, value) {
    let next = Number(value);
    const grid = Number(snap.value);
    if (grid) next = Math.round(next / grid) * grid;
    if (fixed.checked) {
      const length = Number(duration.value);
      if (!Number.isFinite(length) || length <= 0 || length > info.duration || Math.abs(length * 10 - Math.round(length * 10)) > 1e-8) {
        status.textContent = 'Fixed duration must fit the source and use at most one decimal.';
        apply.disabled = true;
        return;
      }
      start = Math.max(0, Math.min(info.duration - length, which === 'end' ? next - length : next));
      end = start + length;
    } else if (which === 'start') {
      start = Math.max(0, Math.min(info.duration, next));
    } else {
      end = Math.max(0, Math.min(info.duration, next));
    }
    status.textContent = '';
    show();
  }
  startField.onchange = () => change('start', startField.value);
  endField.onchange = () => change('end', endField.value);
  startHandle.oninput = () => change('start', startHandle.value);
  endHandle.oninput = () => change('end', endHandle.value);
  fixed.onchange = () => {
    duration.disabled = !fixed.checked;
    if (fixed.checked) {
      const length = Math.round((end - start) * 10) / 10;
      if (length > 0 && length <= info.duration) duration.value = String(length);
      change('start', start);
    }
  };
  duration.onchange = () => change('start', start);
  snap.onchange = () => change('start', start);
  playhead.oninput = () => {
    seek(Number(playhead.value));
    show();
  };
  player.onplay = () => {
    if (selectedOnly.checked && (position() < start || position() >= end)) seek(start);
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
    playhead.value = String(position());
    show();
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
