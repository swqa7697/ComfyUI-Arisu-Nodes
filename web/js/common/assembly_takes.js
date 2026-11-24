// The take picker of Assemble Video: published takes of one project, chosen several at a time or one as a replacement.
import { listTakes, mediaUrl } from './assembly_api.js';
import { openDialog } from './assembly_dialogs.js';
import { audioLabel, fileName, seconds } from './assembly_format.js';
import { el } from './dom.js';

function label(take) {
  const segment = take.take?.segment;
  return `${segment ? `${segment} · ` : ''}${fileName(take.path)}`;
}

function detail(take, taken) {
  const parts = [
    `${take.frames} f`,
    seconds(take.duration),
    `${take.width}×${take.height}`,
    audioLabel(take.audio),
    ...(take.take?.origin === 'director' ? ['Director'] : []),
    ...(taken ? ['In edit'] : []),
  ];
  return parts.join(' · ');
}

/**
 * List the project's takes and resolve the chosen descriptions, or null when dismissed.
 *
 * `mode: 'add'` selects any number; `mode: 'replace'` returns one, with each candidate playable
 * beside the take it would replace. `taken(root, path)` marks footage already in the edit and
 * `current` is the location being replaced.
 */
export function pickTakes({ project, mode = 'add', taken = () => false, current = null, signal }) {
  return openDialog(
    mode === 'add' ? `Takes of ${project}` : `Replace with a take of ${project}`,
    (finish, dialog) => {
      const chosen = new Map();
      let takes = [];
      let generation = 0;
      const status = el('output', { className: 'hint', ariaLive: 'polite', textContent: 'Loading takes…' });
      const list = el('div', { className: 'list', role: 'list' });
      const filter = el('input', { type: 'search', placeholder: 'Filter Takes', ariaLabel: 'Filter takes', oninput: () => show() });
      const legacy = el('input', { type: 'checkbox', onchange: () => load() });
      const confirm = el('button', {
        className: 'apply',
        textContent: 'Add Takes',
        disabled: true,
        onclick: () => finish([...chosen.values()]),
      });
      const key = (take) => `${take.root}|${take.path}`;
      const visible = () => {
        const wanted = filter.value.trim().toLowerCase();
        return takes.filter((take) => !wanted || `${take.path} ${take.take?.segment ?? ''}`.toLowerCase().includes(wanted));
      };
      const count = () => {
        confirm.textContent = chosen.size === 1 ? 'Add 1 Take' : `Add ${chosen.size} Takes`;
        confirm.disabled = !chosen.size;
      };
      function show() {
        const rows = visible().map((take) => {
          const isCurrent = current && current.root === take.root && current.path === take.path;
          const pick =
            mode === 'add'
              ? el('input', {
                  type: 'checkbox',
                  checked: chosen.has(key(take)),
                  ariaLabel: `Select ${label(take)}`,
                  onchange: (event) => {
                    if (event.target.checked) chosen.set(key(take), take);
                    else chosen.delete(key(take));
                    count();
                  },
                })
              : el('button', { textContent: isCurrent ? 'Keep' : 'Use', ariaLabel: `Use ${label(take)}`, onclick: () => finish([take]) });
          const row = el('div', { className: 'take', role: 'listitem' }, [
            pick,
            el('div', {}, [
              el('div', { className: 'name', textContent: label(take), title: take.path }),
              el('div', { className: 'detail', textContent: detail(take, taken(take.root, take.path)) }),
            ]),
            el('span', { className: 'detail', textContent: isCurrent ? 'Current' : '' }),
            // Nothing is fetched until the user opens the preview and presses play.
            el('details', {}, [
              el('summary', { textContent: 'Preview' }),
              el('video', { controls: true, preload: 'none', src: mediaUrl(take.root, take.path) }),
            ]),
          ]);
          if (isCurrent) row.dataset.current = '';
          return row;
        });
        list.replaceChildren(...rows);
        status.textContent = takes.length ? (rows.length ? '' : 'No take matches the filter.') : 'No published takes in this project.';
      }
      async function load() {
        const token = ++generation;
        status.textContent = 'Loading takes…';
        try {
          const data = await listTakes(project, legacy.checked, signal);
          if (token !== generation || !dialog.open) return;
          takes = data.takes.filter((take) => take.state === 'ok');
          show();
        } catch (error) {
          if (token === generation && dialog.open) status.textContent = error.message;
        }
      }
      void load();
      return [
        el('div', { className: 'content' }, [
          el('div', { className: 'bar' }, [
            filter,
            el('label', {}, [legacy, el('span', { textContent: 'Legacy Director takes' })]),
            ...(mode === 'add'
              ? [
                  el('button', {
                    textContent: 'Select All',
                    onclick: () => {
                      for (const take of visible()) chosen.set(key(take), take);
                      count();
                      show();
                    },
                  }),
                ]
              : []),
          ]),
          status,
          list,
        ]),
        el('div', { className: 'actions' }, [
          el('button', { textContent: 'Cancel', onclick: () => finish() }),
          ...(mode === 'add' ? [confirm] : []),
        ]),
      ];
    },
    { signal },
  );
}
