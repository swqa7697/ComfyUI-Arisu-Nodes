// Current-operation terminal shared by agent management and generation activity.
import { api } from '../../../../scripts/api.js';
import { closeOnBackdropClick, el } from '../common/dom.js';

export const ACTIVITY_STYLE = `
.arisu-activity{--log-bg:var(--comfy-input-bg,#181818);--log-text:var(--input-text,#ddd);--log-muted:var(--descrip-text,#aaa);
 --log-blue:#85caff;--log-green:#9bd4a3;--log-yellow:#edcc89;--log-red:#f4a4a4;--log-purple:#d4b6ff;
 display:flex;flex-direction:column;flex:1;min-height:0;gap:8px;}
.arisu-activity .activity-bar{display:flex;align-items:center;gap:12px;flex-shrink:0;min-height:32px;}
.arisu-activity .activity-bar strong{font-size:13px;}.arisu-activity .activity-state{flex:1;color:var(--log-muted);font-size:12px;}
.arisu-activity .terminal{flex:1;min-height:100px;overflow:auto;overscroll-behavior:contain;scrollbar-width:thin;
 background:var(--log-bg);color:var(--log-text);border:1px solid var(--border-color,#444);border-radius:6px;
 padding:14px;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;}
.arisu-activity .terminal:empty::before{content:attr(data-placeholder);color:var(--log-muted);}
.arisu-activity .log-details{margin:6px 0;border-left:2px solid var(--border-color,#444);padding-left:10px;}
.arisu-activity .log-details summary{cursor:pointer;color:var(--log-blue);white-space:normal;}
.arisu-activity .log-details .log-content{max-height:320px;overflow:auto;}
.arisu-activity .log-analysis,.arisu-activity .log-agent{font:13px/1.7 Arial,system-ui,sans-serif;margin:8px 0;}
.arisu-activity .log-line{display:block;min-height:1.65em;}.arisu-activity .log-analysis{color:var(--log-purple);}
.arisu-activity .log-tool{color:var(--log-blue);}.arisu-activity .log-success{color:var(--log-green);}
.arisu-activity .log-error{color:var(--log-red);}.arisu-activity .log-progress{color:var(--log-yellow);}
.arisu-activity a{color:var(--log-blue);text-decoration:underline;text-underline-offset:3px;}
.arisu-activity .activity-state.running::before,.arisu-workbench .status.running::before{content:'';display:inline-block;width:10px;height:10px;
 border:2px solid currentColor;border-right-color:transparent;border-radius:50%;margin-right:7px;vertical-align:-2px;}
@media(prefers-reduced-motion:no-preference){.arisu-activity .activity-state.running::before,.arisu-workbench .status.running::before{animation:arisu-agent-spin 1s linear infinite;}}
@keyframes arisu-agent-spin{to{transform:rotate(360deg);}}
.arisu-activity-modal{width:min(1100px,96vw);height:90vh;max-height:90vh;box-sizing:border-box;padding:0;
 border:1px solid var(--border-color,#444);border-radius:10px;background:var(--comfy-menu-bg,#303030);color:var(--fg-color,#ddd);
 box-shadow:0 24px 64px #0009;font:13px/1.5 Arial,system-ui,sans-serif;}
.arisu-activity-modal[open]{display:flex;flex-direction:column;overflow:hidden;}
.arisu-activity-modal::backdrop{background:#0009;backdrop-filter:blur(3px);}
.arisu-activity-modal header{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid var(--border-color,#444);}
.arisu-activity-modal header strong{flex:1;font-size:16px;}.arisu-activity-modal>.arisu-activity{padding:12px 18px 18px;}
.arisu-activity-modal button,.arisu-activity button{font:inherit;color:inherit;background:var(--comfy-input-bg,#222);border:1px solid var(--border-color,#555);
 border-radius:5px;min-height:34px;padding:5px 10px;cursor:pointer;}
.arisu-activity-modal :focus-visible,.arisu-activity :focus-visible{outline:2px solid #85caff;outline-offset:2px;}
`;

// Decode known provider envelopes; unknown structured output stays inspectable as details.
function activityText(line) {
  const raw = line.replace(/^\[(?:agent|analysis)\]\s*/, '');
  let event;
  try {
    event = JSON.parse(raw);
  } catch {
    return line;
  }
  if (!event || typeof event !== 'object' || Array.isArray(event)) return `[details] ${raw}`;
  const item = event.item ?? event;
  if (['reasoning', 'agent_message', 'thinking', 'text'].includes(item.type)) {
    const text = item.text ?? item.thinking;
    if (typeof text === 'string') return `[${['reasoning', 'thinking'].includes(item.type) ? 'analysis' : 'agent'}] ${text}`;
  }
  const blocks = event.message?.content ?? event.content;
  if (Array.isArray(blocks)) {
    return blocks
      .map((block) => {
        if (block?.type === 'thinking' && typeof block.thinking === 'string') return `[analysis] ${block.thinking}`;
        if (block?.type === 'text' && typeof block.text === 'string') return `[agent] ${block.text}`;
        if (block?.type === 'tool_use') return `[tool] ${block.name ?? 'Tool call'}\n${JSON.stringify(block.input ?? {}, null, 2)}`;
        // Image bytes never belong in the activity view.
        if (['image', 'image_url'].includes(block?.type)) return '[details] Image content omitted';
        return `[details] ${JSON.stringify(block, null, 2)}`;
      })
      .join('\n');
  }
  const delta = event.event?.delta ?? event.delta;
  if (delta?.type === 'thinking_delta' && typeof delta.thinking === 'string') return `[analysis] ${delta.thinking}`;
  if (delta?.type === 'text_delta' && typeof delta.text === 'string') return `[agent] ${delta.text}`;
  if (item.type === 'command_execution') return `[command] ${item.command ?? ''}\n${item.aggregated_output ?? ''}`;
  if (item.type === 'mcp_tool_call') {
    const content = item.result?.content;
    return (
      '[tool] ' +
      [item.server, item.tool].filter(Boolean).join('.') +
      '\n' +
      JSON.stringify(item.arguments ?? {}, null, 2) +
      '\n' +
      (Array.isArray(content)
        ? content
            .filter((block) => block?.type === 'text')
            .map((block) => block.text)
            .join('\n')
        : '')
    );
  }
  return `[details] ${JSON.stringify(event, null, 2)}`;
}

function logLine(text) {
  const kind = /^\[analysis\]/i.test(text)
    ? 'analysis'
    : /^\[agent\]/i.test(text)
      ? 'agent'
      : /^\[(tool|command|search|file_change)/i.test(text)
        ? 'tool'
        : /\b(error|failed|failure)\b/i.test(text)
          ? 'error'
          : /\b(done|complete|successfully|authenticated)\b/i.test(text)
            ? 'success'
            : /^(#\d+|\[(prepare|job|codex|grok|thread|turn))/i.test(text)
              ? 'progress'
              : '';
  const row = el('div', { className: `log-line log-${kind}` });
  // Render text, never HTML or terminal escape hyperlinks. Only explicit HTTP(S) URLs are links.
  let offset = 0;
  for (const match of text.matchAll(/https?:\/\/[^\s<>"']+/g)) {
    const url = match[0].replace(/[).,;!\]}]+$/, '');
    row.append(el('span', { textContent: text.slice(offset, match.index) }));
    row.append(el('a', { textContent: url, href: url, target: '_blank', rel: 'noopener noreferrer' }));
    offset = match.index + url.length;
  }
  row.append(el('span', { textContent: text.slice(offset) }));
  return row;
}

/** Incrementally append a session, retaining text and scroll position across polls. */
export function createActivity(label = 'Agent logs') {
  const output = el('div', { className: 'terminal', tabIndex: 0, ariaLabel: label });
  output.dataset.placeholder = 'No activity yet. Start an operation above.';
  const status = el('span', { className: 'activity-state', role: 'status', ariaLive: 'polite', textContent: 'Idle' });
  let following = true;
  let session = '';
  let cursor = 0;
  let epoch = 0;
  let group = null;
  let analysis = false;
  function appendLine(line) {
    const text = activityText(String(line));
    for (const part of text.split(/\n(?=\[[a-z])/i)) {
      const heading = /^\[([^\]]+)\]\s*/.exec(part);
      if (heading) {
        group = null;
        analysis = heading[1].toLowerCase() === 'analysis';
      }
      const noisy = heading && /^(tool|command|search|file_change|todo_list|details)/i.test(heading[1]);
      if (noisy || (!group && !analysis && (part.length > 800 || part.split('\n').length > 8))) {
        const content = el('div', { className: 'log-content' });
        const summary = part.split('\n')[0];
        const details = el('details', { className: 'log-details' }, [
          el('summary', { textContent: summary.slice(0, 120) + (summary.length > 120 ? '…' : '') }),
          content,
        ]);
        output.append(details);
        group = content;
      }
      (group ?? output).append(logLine(part));
    }
  }
  const follow = el('button', { textContent: 'Auto-scroll on', ariaPressed: 'true' });
  function followState(value) {
    following = value;
    follow.textContent = value ? 'Auto-scroll on' : 'Resume auto-scroll';
    follow.ariaPressed = String(value);
  }
  follow.onclick = () => {
    followState(!following);
    if (following) output.scrollTop = output.scrollHeight;
  };
  output.addEventListener('scroll', () => followState(output.scrollHeight - output.clientHeight - output.scrollTop < 24));
  const element = el('div', { className: 'arisu-activity' }, [
    el('div', { className: 'activity-bar' }, [el('strong', { textContent: 'Activity' }), status, follow]),
    output,
  ]);
  function reset() {
    epoch++;
    session = '';
    cursor = 0;
    output.replaceChildren();
    group = null;
    analysis = false;
    followState(true);
    status.textContent = 'Idle';
    status.className = 'activity-state';
  }
  function showStatus(message, running) {
    status.textContent = message;
    status.className = `activity-state${running ? ' running' : ''}`;
  }
  return {
    element,
    reset,
    showStatus,
    async read({ job = '', agent = '', running = null, message = '' } = {}) {
      const current = epoch;
      const query = new URLSearchParams({ session, cursor: String(cursor), ...(job ? { job } : {}) });
      try {
        const response = await api.fetchApi(`/arisu/workbench/logs?${query}`);
        if (!response.ok) throw new Error('Unable to read activity. Retrying…');
        const data = await response.json();
        if (epoch !== current) return false;
        if (agent && data.agent !== agent) {
          reset();
          return false;
        }
        if ((data.session ?? '') !== session) {
          output.replaceChildren();
          group = null;
          analysis = false;
          followState(true);
          session = data.session ?? '';
          cursor = 0;
        }
        for (const line of data.lines ?? []) appendLine(line);
        cursor = data.cursor ?? cursor;
        const live = running ?? data.state === 'running';
        status.className = `activity-state${live ? ' running' : ''}`;
        status.textContent =
          message ||
          [data.agent === 'grok' ? 'Grok Build' : data.agent === 'codex' ? 'Codex' : '', data.action, data.state]
            .filter(Boolean)
            .join(' · ') ||
          'Idle';
        if (following) output.scrollTop = output.scrollHeight;
        return data.more === true;
      } catch (error) {
        if (epoch === current) status.textContent = error.message;
        return false;
      }
    },
  };
}

/** Show this generation's exposed CLI activity, with no cross-job log replay. */
export function openAgentActivity(snapshot, onClose) {
  const dialog = el('dialog', { className: 'arisu-activity-modal', ariaLabel: 'Agent activity' });
  const activity = createActivity('Generation activity');
  let timer;
  let closed = false;
  async function refresh() {
    const state = snapshot();
    if (!state.job) activity.showStatus(state.message || 'Preparing workflow…', state.running);
    const more = state.job ? await activity.read(state) : false;
    if (!closed && (state.running || more)) timer = setTimeout(refresh, more ? 0 : 750);
  }
  dialog.append(
    el('style', { textContent: ACTIVITY_STYLE }),
    el('header', {}, [
      el('strong', { textContent: 'Agent activity' }),
      el('button', { textContent: 'Close', onclick: () => dialog.close() }),
    ]),
    activity.element,
  );
  closeOnBackdropClick(dialog);
  dialog.onclose = () => {
    closed = true;
    clearTimeout(timer);
    activity.reset();
    dialog.remove();
    onClose();
  };
  document.body.append(dialog);
  dialog.showModal();
  void refresh();
  return dialog;
}
