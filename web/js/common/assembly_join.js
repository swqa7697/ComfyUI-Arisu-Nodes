// The join preview of Assemble Video: the end of one take and the start of the next, looped with sound.
//
// A direct cut is the default. Colour signalling is checked first; the experimental match is offered
// only for a verified continuation with a stable step, and nothing is stored until the user applies it.
import { joinPreview } from './assembly_api.js';
import { openDialog } from './assembly_dialogs.js';
import { el } from './dom.js';

const FADES = [0, 5, 10, 20];
const SIGNALS = ['range', 'matrix', 'primaries', 'transfer'];
const POLL = 750;
const delay = () => new Promise((resolve) => setTimeout(resolve, POLL));
const shape = (correction) =>
  correction
    ? Object.fromEntries(['luma_gain', 'luma_offset', 'cb_offset', 'cr_offset', 'taper'].map((name) => [name, correction[name]]))
    : null;

/**
 * Audition one join. `outgoing` and `incoming` are `{ root, path, range }`, `join` the stored
 * `{ correction, fade }` and `verified` whether the incoming take continues the outgoing one.
 *
 * Resolves the approved `{ correction, fade }` (a direct cut is `{ null, 0 }`) or null when dismissed.
 */
export function previewJoin({ outgoing, incoming, join, verified, signal }) {
  return openDialog(
    'Preview Join',
    (finish, dialog, closing) => {
      const candidate = { correction: shape(join?.correction), fade: join?.fade ?? 0 };
      let job = null;
      let generation = 0;
      let variant = 'a';
      let variants = ['a'];
      let suggestion = null;
      let cut = 0;
      const status = el('output', { className: 'hint', ariaLive: 'polite' });
      const signalling = el('div', { className: 'signalling' });
      const player = el('video', { controls: true, loop: true, preload: 'auto' });
      const compare = el('button', {
        textContent: 'Show Direct Cut',
        ariaPressed: 'false',
        disabled: true,
        onclick: () => choose(variant === 'a' ? 'b' : 'a'),
      });
      const jump = el('button', {
        textContent: 'Jump to Cut',
        disabled: true,
        onclick: () => {
          player.currentTime = Math.max(0, cut - 1);
          void player.play()?.catch?.(() => {});
        },
      });
      const match = el('input', { type: 'checkbox', checked: Boolean(candidate.correction), disabled: true });
      const matchHint = el('div', { className: 'hint' });
      const fade = el(
        'select',
        { ariaLabel: 'Click fade' },
        [...new Set([...FADES, candidate.fade])]
          .sort((a, b) => a - b)
          .map((ms) => el('option', { value: String(ms), textContent: ms ? `${ms} ms` : 'Off' })),
      );
      fade.value = String(candidate.fade);
      const retry = el('button', { textContent: 'Retry Preview', hidden: true, onclick: () => start() });
      const apply = el('button', { className: 'apply', textContent: 'Apply to This Join', disabled: true });
      apply.onclick = () => finish({ correction: candidate.correction, fade: candidate.fade });

      function choose(next) {
        variant = variants.includes(next) ? next : 'a';
        const at = player.currentTime || 0;
        player.src = joinPreview.viewUrl(job, variant);
        player.currentTime = at;
        compare.ariaPressed = String(variant === 'a' && variants.length > 1);
        compare.textContent = variant === 'a' ? 'Show Candidate' : 'Show Direct Cut';
        compare.disabled = variants.length < 2;
      }
      function showSignalling(report) {
        if (!report) return signalling.replaceChildren();
        if (report.match) return signalling.replaceChildren(el('div', { textContent: 'Colour signalling matches on both sides.' }));
        return signalling.replaceChildren(
          el('div', { textContent: 'Colour signalling differs. Correct the sources before any colour match.' }),
          el('table', {}, [
            el('tr', {}, [el('th', {}), el('th', { textContent: 'Outgoing' }), el('th', { textContent: 'Incoming' })]),
            ...SIGNALS.map((name) =>
              el('tr', {}, [
                el('th', { textContent: name }),
                el('td', { textContent: report.outgoing?.[name] ?? '—' }),
                el('td', { textContent: report.incoming?.[name] ?? '—' }),
              ]),
            ),
          ]),
        );
      }
      function showMatch(report) {
        const usable = verified && report?.match && suggestion?.stable;
        match.disabled = !usable && !candidate.correction;
        matchHint.textContent = usable
          ? 'Tapers a bounded brightness and colour offset over the first frames of the incoming take.'
          : !verified
            ? 'Available only when the incoming take continues the outgoing take.'
            : report && !report.match
              ? 'Unavailable while colour signalling differs.'
              : 'No stable colour step was found at this join.';
      }
      async function release() {
        const id = job;
        job = null;
        if (id) await joinPreview.remove(id).catch(() => {});
      }
      async function start() {
        const token = ++generation;
        retry.hidden = true;
        apply.disabled = jump.disabled = compare.disabled = true;
        status.textContent = 'Preparing preview…';
        await release();
        try {
          const created = await joinPreview.create(
            { outgoing, incoming, join: { correction: candidate.correction, fade: candidate.fade } },
            signal,
          );
          if (token !== generation || !dialog.open) return void joinPreview.remove(created.id).catch(() => {});
          job = created.id;
          for (;;) {
            const report = await joinPreview.status(job, signal);
            if (token !== generation || !dialog.open) return;
            if (report.state === 'running') {
              status.textContent = `Preparing preview ${report.progress ?? 0}%`;
              await delay();
              if (token !== generation || !dialog.open) return;
              continue;
            }
            if (report.state !== 'ready') throw new Error(report.error || 'The preview could not be made.');
            variants = report.variants ?? ['a'];
            cut = report.cut ?? 0;
            suggestion = report.suggestion ?? suggestion;
            showSignalling(report.signalling);
            showMatch(report.signalling);
            status.textContent = '';
            jump.disabled = apply.disabled = false;
            choose(variants.includes('b') ? 'b' : 'a');
            return;
          }
        } catch (error) {
          if (token !== generation || !dialog.open) return;
          status.textContent = error.status === 429 ? 'Another preview is still being made. Retry shortly.' : error.message;
          retry.hidden = false;
        }
      }
      match.onchange = () => {
        candidate.correction = match.checked ? shape(suggestion?.correction) : null;
        void start();
      };
      fade.onchange = () => {
        candidate.fade = Number(fade.value);
        void start();
      };
      closing(() => {
        generation++;
        void release();
      });
      void start();
      return [
        el('div', { className: 'content' }, [
          status,
          signalling,
          player,
          el('div', { className: 'bar' }, [compare, jump, retry]),
          el('label', {}, [match, el('span', { textContent: 'Experimental: match colour across this join' })]),
          matchHint,
          el('label', {}, [el('span', { textContent: 'Click fade' }), fade]),
        ]),
        el('div', { className: 'actions' }, [
          el('button', { textContent: 'Cancel', onclick: () => finish() }),
          el('button', { textContent: 'Use Direct Cut', onclick: () => finish({ correction: null, fade: 0 }) }),
          apply,
        ]),
      ];
    },
    { signal },
  );
}
