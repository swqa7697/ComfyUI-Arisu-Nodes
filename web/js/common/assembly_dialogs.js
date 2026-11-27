// Small modal dialogs of Assemble Video: one entry's footage and trim, and the confirmation before files are deleted.
import { mediaUrl } from './assembly_api.js';
import { bytes, fileName } from './assembly_format.js';
import { closeOnBackdropClick, el } from './dom.js';

export const DIALOG_STYLE = `
.arisu-assembly-dialog{width:min(720px,92vw);max-height:88vh;padding:0;border:1px solid var(--border-color,#444);
 background:var(--comfy-menu-bg,#202020);color:var(--fg-color,#ddd);font:13px/1.4 Arial,system-ui,sans-serif;overflow:hidden;}
.arisu-assembly-dialog[open]{display:flex;flex-direction:column;}
.arisu-assembly-dialog *{box-sizing:border-box;}
.arisu-assembly-dialog h3{margin:0;padding:12px 16px;font-size:14px;border-bottom:1px solid var(--border-color,#444);}
.arisu-assembly-dialog .content{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:10px;padding:12px 16px;}
.arisu-assembly-dialog .actions{display:flex;justify-content:flex-end;gap:8px;padding:10px 16px;border-top:1px solid var(--border-color,#444);}
.arisu-assembly-dialog .bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;}
.arisu-assembly-dialog :is(button,input,select){font:inherit;color:inherit;min-height:32px;padding:4px 10px;
 border:1px solid var(--border-color,#444);background:var(--comfy-input-bg,#333);}
.arisu-assembly-dialog button{cursor:pointer;}
.arisu-assembly-dialog input[type=checkbox]{min-height:0;width:16px;height:16px;padding:0;accent-color:var(--arisu-accent);}
.arisu-assembly-dialog label{display:flex;align-items:center;gap:8px;}
.arisu-assembly-dialog video{width:100%;max-height:46vh;background:#000;}
.arisu-assembly-dialog .hint{color:var(--descrip-text,#999);font-size:12px;}
.arisu-assembly-dialog .list{display:flex;flex-direction:column;gap:4px;}
.arisu-assembly-dialog .take{display:grid;grid-template-columns:auto clamp(76px,14vw,122px) minmax(0,1fr) auto;align-items:center;column-gap:12px;row-gap:0;padding:8px 10px;
 border:1px solid var(--border-color,#444);border-radius:4px;background:var(--comfy-input-bg,#2a2a2a);}
.arisu-assembly-dialog .take[data-current]{border-color:var(--arisu-accent);}
.arisu-assembly-dialog .take:has(input:checked){border-color:var(--arisu-accent);}
.arisu-assembly-dialog button.take-thumb{padding:0;border:0;position:relative;display:grid;place-items:center;align-self:center;aspect-ratio:16/9;background:var(--comfy-menu-bg,#181818);border-radius:3px;overflow:hidden;}
.arisu-assembly-dialog .take-thumb svg{width:20px;height:20px;opacity:.55;}
.arisu-assembly-dialog .take-thumb img{position:absolute;width:100%;height:100%;object-fit:contain;background:var(--comfy-menu-bg,#181818);}
.arisu-assembly-dialog .take .name{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-weight:600;}
.arisu-assembly-dialog .take-info .detail{margin-top:4px;}
.arisu-assembly-dialog .take-status{display:grid;gap:3px;justify-items:end;font-size:11px;}
.arisu-assembly-dialog .take-status span{padding:1px 5px;border:1px solid var(--border-color,#555);border-radius:4px;}
.arisu-assembly-dialog .play-mark{position:absolute;bottom:4px;right:4px;padding:1px 5px;border-radius:3px;background:#000b;color:white;font-size:10px;}
.arisu-assembly-dialog.take-preview[open]{width:min(900px,92vw);display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;}
.arisu-assembly-dialog.take-preview h3{border:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.arisu-assembly-dialog.take-preview button{margin:8px 12px;}
.arisu-assembly-dialog.take-preview video{grid-column:1/-1;display:block;height:auto;max-height:calc(88vh - 54px);object-fit:contain;}
.arisu-assembly-dialog .take-thumb:focus-visible{outline:2px solid var(--arisu-accent);outline-offset:2px;}
.arisu-assembly-dialog .hint:empty{display:none;}
.arisu-assembly-dialog .take .detail{color:var(--descrip-text,#999);font-size:12px;font-variant-numeric:tabular-nums;}
.arisu-assembly-dialog table{border-collapse:collapse;font-size:12px;}
.arisu-assembly-dialog :is(td,th){padding:3px 10px 3px 0;text-align:left;font-variant-numeric:tabular-nums;}
.arisu-assembly-dialog .path{overflow-wrap:anywhere;}
.arisu-assembly-dialog .size{text-align:right;color:var(--descrip-text,#999);}
`;

/**
 * Open a modal with the shared frame. `build(finish, dialog, closing)` returns its content: `finish(value)`
 * closes it and resolves the returned promise with that value (null when dismissed), and `closing(fn)`
 * registers work for the moment it closes, however that happens.
 */
export function openDialog(title, build, { signal, invoker = document.activeElement } = {}) {
  return new Promise((resolve) => {
    let result = null;
    const cleanups = [];
    const dialog = el('dialog', { className: 'arisu-assembly-dialog', ariaLabel: title });
    const abort = () => dialog.open && dialog.close();
    const finish = (value = null) => {
      result = value;
      dialog.close();
    };
    dialog.onclose = () => {
      signal?.removeEventListener('abort', abort);
      for (const cleanup of cleanups) cleanup();
      dialog.remove();
      invoker?.focus?.({ preventScroll: true });
      resolve(result);
    };
    const content = build(finish, dialog, (cleanup) => cleanups.push(cleanup));
    dialog.append(el('style', { textContent: DIALOG_STYLE }), el('h3', { textContent: title }), ...content);
    closeOnBackdropClick(dialog);
    document.body.append(dialog);
    dialog.showModal();
    if (signal?.aborted) dialog.close();
    else signal?.addEventListener('abort', abort, { once: true });
  });
}

/**
 * Play one entry and edit its audio source and, for an unregistered file, a head trim.
 *
 * A take saved by the pack is already trimmed by this run's real overlap, so only a file without a
 * record may skip frames at its head. Resolves `{ audio, range }` or null.
 */
export function editEntry(entry, info, options) {
  return openDialog(
    fileName(entry.path),
    (finish) => {
      const audio = el(
        'select',
        { ariaLabel: 'Audio source' },
        [
          ['auto', 'Automatic: saved PCM, then embedded'],
          ['embedded', 'Embedded audio'],
          ['none', 'Silent'],
        ].map(([value, label]) => el('option', { value, textContent: label, selected: value === entry.audio })),
      );
      audio.value = entry.audio;
      const skip = el('input', {
        type: 'number',
        min: 0,
        max: Math.max(0, (info.frames ?? 1) - 1),
        step: 1,
        ariaLabel: 'Skip head frames',
      });
      skip.value = String(entry.range?.[0] ?? 0);
      const trim = info.take
        ? []
        : [
            el('label', {}, [el('span', { textContent: 'Skip head frames' }), skip]),
            el('div', {
              className: 'hint',
              textContent: 'Only for a video that still contains its continuation overlap. Sound is cut at the same time.',
            }),
          ];
      return [
        el('div', { className: 'content' }, [
          el('video', { controls: true, preload: 'metadata', src: mediaUrl(entry.root, entry.path) }),
          el('label', {}, [el('span', { textContent: 'Audio source' }), audio]),
          ...trim,
        ]),
        el('div', { className: 'actions' }, [
          el('button', { textContent: 'Cancel', onclick: () => finish() }),
          el('button', {
            className: 'apply',
            textContent: 'Apply',
            onclick: () => {
              const head = info.take ? (entry.range?.[0] ?? 0) : Math.trunc(Number(skip.value) || 0);
              const end = entry.range?.[1] ?? info.frames;
              // An interval that would leave no frame is refused here and again on the server.
              if (head < 0 || !end || head >= end) return;
              finish({ audio: audio.value, range: head > 0 || entry.range ? [head, end] : null });
            },
          }),
        ]),
      ];
    },
    options,
  );
}

/** A take's MP4 can sit beside its companion folder. Group only the folder's contents under its heading. */
function deletionGroup({ root, directory, files }) {
  const standalone = [];
  const contents = [];
  for (const file of files) {
    const rows = directory && file.path.startsWith(`${directory}/`) ? contents : standalone;
    rows.push(
      el('tr', {}, [
        el('td', { className: 'path', textContent: `${root}:${file.path}` }),
        el('td', { className: 'size', textContent: bytes(file.bytes) }),
      ]),
    );
  }
  if (directory)
    standalone.push(el('tr', {}, [el('th', { className: 'path', colSpan: 2, scope: 'rowgroup', textContent: `${root}:${directory}/` })]));
  return el('tbody', {}, [...standalone, ...contents]);
}

/** Show what a confirmed deletion removes. Resolves true only on the explicit destructive action. */
export function confirmDeletion(plan, { signal, unbound = 0 } = {}) {
  const reviewed = plan.entries.filter((entry) => entry.state === 'deletable');
  const unavailable = plan.entries.filter((entry) => entry.state !== 'deletable');
  const folders = reviewed.filter((entry) => entry.directory).length;
  const files = reviewed.reduce((sum, entry) => sum + entry.files.length, 0);
  const folderCount = folders ? `${folders} ${folders === 1 ? 'Folder' : 'Folders'} and ` : '';
  const count = `${folderCount}${files} ${files === 1 ? 'File' : 'Files'}`;
  return openDialog(
    'Delete Files from Disk',
    (finish) => [
      el('div', { className: 'content' }, [
        el('div', {
          textContent: files ? 'Permanently delete this selection? Undo only restores rows in the edit.' : 'There are no files to delete.',
        }),
        ...(folders ? [el('strong', { textContent: 'Each folder will be permanently deleted with all its contents.' })] : []),
        el('table', {}, [
          ...reviewed.map(deletionGroup),
          el('tfoot', {}, [
            el('tr', {}, [el('th', { textContent: count.toLowerCase() }), el('th', { className: 'size', textContent: bytes(plan.bytes) })]),
          ]),
        ]),
        ...(unavailable.length
          ? [
              el('div', { className: 'hint', textContent: 'Unavailable files will be skipped.' }),
              ...unavailable.map((entry) => el('div', { className: 'hint path', textContent: `${entry.root}:${entry.path}` })),
            ]
          : []),
        ...(unbound ? [el('div', { className: 'hint', textContent: 'Selected rows without a file location will be skipped.' })] : []),
      ]),
      el('div', { className: 'actions' }, [
        el('button', { textContent: 'Cancel', autofocus: true, onclick: () => finish(false) }),
        el('button', {
          className: 'danger',
          textContent: `Delete ${count}`,
          disabled: !files,
          onclick: () => finish(true),
        }),
      ]),
    ],
    { signal },
  ).then((confirmed) => confirmed === true);
}
