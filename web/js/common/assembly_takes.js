// The take picker of Assemble Video: published takes of one project, chosen several at a time or one as a replacement.
import { listTakes, mediaUrl } from './assembly_api.js';
import { openDialog } from './assembly_dialogs.js';
import { fileName, seconds } from './assembly_format.js';
import { el } from './dom.js';
import { posterUrl, VIDEO_ICON } from './resource_browser.js';
import { takeCatalog } from './take_sources.js';

const stamp = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

function thumbnail(item, name, player) {
  const tile = el('button', {
    className: 'take-thumb',
    type: 'button',
    ariaLabel: `Preview ${name}`,
    title: 'Preview',
    ariaExpanded: 'false',
    onclick: () => {
      const open = player.hidden;
      player.hidden = !open;
      tile.ariaExpanded = String(open);
      if (open) {
        player.src = mediaUrl(item.root, item.path);
        player.play()?.catch(() => {});
      } else {
        player.pause();
        player.removeAttribute('src');
        player.load();
      }
    },
  });
  tile.innerHTML = VIDEO_ICON;
  const image = el('img', {
    alt: '',
    loading: 'lazy',
    decoding: 'async',
    src: posterUrl(item.root, item.path, Math.min(2, item.duration / 3), 256),
    onerror: (event) => event.currentTarget.remove(),
  });
  tile.append(image, el('span', { className: 'play-mark', ariaHidden: 'true', textContent: '▶' }));
  return tile;
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
      let identify = takeCatalog();
      const label = (take) => identify(take)?.name ?? fileName(take.path);
      let generation = 0;
      const status = el('output', { className: 'hint', ariaLive: 'polite', textContent: 'Loading takes…' });
      const list = el('div', { className: 'list', role: 'list' });
      const filter = el('input', { type: 'search', placeholder: 'Filter Takes', ariaLabel: 'Filter takes', oninput: () => show() });
      const legacy = el('input', { type: 'checkbox', onchange: () => load() });
      const confirm = el('button', {
        className: 'apply',
        textContent: 'Add Takes',
        disabled: true,
        onclick: () => finish(takes.filter((take) => chosen.has(key(take)))),
      });
      const key = (take) => `${take.root}|${take.path}`;
      const visible = () => {
        const wanted = filter.value.trim().toLowerCase();
        return takes.filter((take) => {
          if (!wanted) return true;
          const identity = identify(take);
          return [identity?.name, identity?.searchTitles, take.path, take.take?.segment].join(' ').toLowerCase().includes(wanted);
        });
      };
      const count = () => {
        confirm.textContent = chosen.size === 1 ? 'Add 1 Take' : `Add ${chosen.size} Takes`;
        confirm.disabled = !chosen.size;
      };
      function show() {
        const rows = visible().map((take) => {
          const isCurrent = current && current.root === take.root && current.path === take.path;
          const identity = identify(take);
          const selected = taken(take.root, take.path);
          const created = Date.parse(take.take?.created);
          const detail = [seconds(take.duration), identity && `Take ${identity.short}`, Number.isFinite(created) && stamp.format(created)]
            .filter(Boolean)
            .join(' · ');
          const accessible = identity ? `${label(take)} · Take ${identity.short}` : label(take);
          const pick =
            mode === 'add'
              ? el('input', {
                  type: 'checkbox',
                  checked: chosen.has(key(take)),
                  ariaLabel: `Select ${accessible}`,
                  onchange: (event) => {
                    if (event.target.checked) chosen.set(key(take), take);
                    else chosen.delete(key(take));
                    count();
                  },
                })
              : el('button', { textContent: isCurrent ? 'Keep' : 'Use', ariaLabel: `Use ${accessible}`, onclick: () => finish([take]) });
          const player = el('video', { controls: true, preload: 'none', hidden: true, ariaLabel: `Video preview of ${accessible}` });
          const row = el('div', { className: 'take', role: 'listitem' }, [
            pick,
            thumbnail(take, accessible, player),
            el('div', { className: 'take-info' }, [
              el('div', { className: 'name', textContent: label(take), title: take.path }),
              el('div', { className: 'detail', textContent: detail }),
            ]),
            el('div', { className: 'take-status' }, [
              ...(identity?.current ? [el('span', { textContent: 'Director choice' })] : []),
              ...(isCurrent || selected ? [el('span', { textContent: isCurrent ? 'Current' : 'In edit' })] : []),
            ]),
            player,
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
          identify = takeCatalog(takes);
          takes.sort((a, b) => {
            const left = identify(a),
              right = identify(b);
            if (!left || !right) return Number(!!right) - Number(!!left) || a.path.localeCompare(b.path, undefined, { numeric: true });
            return (
              left.order - right.order ||
              left.group.localeCompare(right.group, undefined, { numeric: true }) ||
              Number(right.current) - Number(left.current) ||
              (b.take.created || '').localeCompare(a.take.created || '') ||
              a.path.localeCompare(b.path)
            );
          });
          const available = new Set(takes.map(key));
          for (const key of chosen.keys()) if (!available.has(key)) chosen.delete(key);
          if (chosen.size || confirm.textContent !== 'Add Takes') count();
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
