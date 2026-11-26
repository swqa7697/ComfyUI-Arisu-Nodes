import { api } from '../../../../scripts/api.js';
import { app } from '../../../../scripts/app.js';
import { observeWorkflowLoads } from '../common/selection_context.js';
import { workbenchRequest } from './agent_settings.js';
import { executionTarget } from './settings_broadcast.js';

function identity() {
  return globalThis.crypto?.randomUUID?.() ?? `${String(Date.now())}-${Math.random().toString(36).slice(2)}`;
}
export function generationTime(run) {
  if (run.elapsedMs == null) return '';
  const seconds = Math.floor(run.elapsedMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const duration =
    minutes < 60
      ? `${minutes}:${String(seconds % 60).padStart(2, '0')}`
      : `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  return `Agent time ${duration}${run.timingUnavailable ? ' (updates unavailable)' : ''}`;
}

export function workbenchSessions(nodes, render, notify, messages, onComplete) {
  // Sessions belong to frontend workflow objects, never serialized workflow IDs or node objects.
  const sessions = new Map();
  const views = new Set();
  let loading = false;
  let loadOwner = null;
  let sessionTimer;

  function workflowOwner() {
    return loading ? loadOwner : (app.extensionManager?.workflow?.activeWorkflow ?? app.rootGraph ?? app.graph);
  }

  function bindSession(node) {
    const state = nodes.get(node);
    if (!state || loading || !node.graph) return;
    let target;
    try {
      target = executionTarget(node);
    } catch {
      return;
    }
    if (!target) return;
    const owner = workflowOwner();
    let owned = sessions.get(owner);
    if (!owned) {
      owned = new Map();
      sessions.set(owner, owned);
    }
    let run = owned.get(target.id);
    if (!run && state.run?.owner === owner && !state.run.disposed) {
      run = state.run;
      owned.delete(run.key);
      run.key = target.id;
      owned.set(target.id, run);
    }
    if (!run) {
      run = { epoch: 0, workflow: identity(), running: false, draft: '', hasOutput: false, status: '', owner, key: target.id };
      owned.set(target.id, run);
    }
    if (state.run && state.run !== run && state.run.node === node) state.run.node = null;
    state.run = run;
    run.node = node;
    if (!sessionTimer) sessionTimer = setInterval(reapSessions, 1500);
    sessionTimer.unref?.();
  }

  function updateRun(run) {
    if (run.node && nodes.get(run.node)?.run === run) render(run.node);
    run.activity?.refreshOutput();
  }

  async function cancelGeneration(run) {
    if (run.cancelling) return;
    run.cancelling = true;
    run.status = 'Cancelling…';
    updateRun(run);
    if (!run.job) return;
    const epoch = run.epoch;
    try {
      await workbenchRequest('/release', { id: run.job });
    } catch (error) {
      if (run.disposed || run.epoch !== epoch || !run.running) return;
      run.cancelling = false;
      run.status = error.message;
      notify('error', error.message);
      updateRun(run);
    }
  }

  function refreshProgress(run) {
    const state = nodes.get(run.node);
    if (state?.run === run) {
      if (state.statusElement?.textContent !== run.status) state.statusElement.textContent = run.status;
      const time = generationTime(run);
      if (state.timeElement) state.timeElement.textContent = time ? ` · ${time}` : '';
    }
    run.activity?.refreshOutput();
  }

  function disposeSession(run) {
    run.epoch++;
    run.disposed = true;
    run.running = false;
    run.activity?.close();
    if (run.started) void workbenchRequest('/release', { workflow: run.workflow }).catch(() => {});
    sessions.get(run.owner)?.delete(run.key);
  }

  function reapSessions() {
    if (loading) return;
    const manager = app.extensionManager?.workflow;
    const open = manager?.openWorkflows;
    for (const [owner, owned] of sessions) {
      if (Array.isArray(open) && owner !== manager.activeWorkflow && !open.includes(owner)) {
        for (const run of owned.values()) disposeSession(run);
      }
      if (!owned.size) sessions.delete(owner);
    }
    if (!sessions.size) {
      clearInterval(sessionTimer);
      sessionTimer = null;
    }
  }

  globalThis.addEventListener?.('pagehide', () => {
    for (const owned of sessions.values()) for (const run of owned.values()) disposeSession(run);
    reapSessions();
  });

  observeWorkflowLoads({
    before(_current, target) {
      loading = true;
      loadOwner = target;
      for (const owned of sessions.values()) for (const run of owned.values()) run.activity?.close();
    },
    after(active, succeeded) {
      loading = false;
      // A failed or imported load cannot borrow a previous workflow's runtime state.
      if (!succeeded || !loadOwner) {
        const owned = sessions.get(active);
        if (owned) for (const run of owned.values()) disposeSession(run);
      }
      for (const node of views) {
        bindSession(node);
        render(node);
      }
      const owned = sessions.get(active);
      if (owned) for (const run of owned.values()) if (!run.node || !views.has(run.node)) disposeSession(run);
      loadOwner = null;
      reapSessions();
    },
  });

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function generate(node, capture) {
    bindSession(node);
    const run = nodes.get(node)?.run;
    if (!run || run.running) return;
    run.epoch++;
    run.draft = '';
    run.hasOutput = false;
    run.activityJob = null;
    run.activity?.close();
    run.running = true;
    run.cancelling = false;
    run.elapsedMs = null;
    run.timingUnavailable = false;
    run.status = 'Preparing workflow…';
    const epoch = run.epoch;
    const current = () => !run.disposed && run.epoch === epoch;
    let terminal = false;
    try {
      // Capture everything in one synchronous turn. Edits after this point belong to the next Generate.
      const captured = capture(node, run);
      updateRun(run);
      const payload = captured?.then ? await captured : captured;
      if (!current() || run.cancelling) {
        run.status = 'Generation cancelled';
        return;
      }
      run.started = true;
      const response = await workbenchRequest('/generate', { ...payload, workflow: run.workflow, client_id: api.clientId });
      if (!current()) {
        void workbenchRequest('/release', { id: response.id }).catch(() => {});
        return;
      }
      run.job = response.id;
      run.activityJob = response.id;
      if (run.cancelling) {
        run.cancelling = false;
        await cancelGeneration(run);
      }
      while (current()) {
        const response = await api.fetchApi(`/arisu/workbench/jobs/${run.job}`);
        if (!response.ok) throw new Error('Generation job is unavailable.');
        const job = await response.json();
        if (!current()) return;
        if (Number.isFinite(job.generation_elapsed_ms) && job.generation_elapsed_ms >= 0) run.elapsedMs = job.generation_elapsed_ms;
        terminal = ['complete', 'failed', 'cancelled'].includes(job.state);
        run.status =
          run.cancelling && !terminal
            ? 'Cancelling…'
            : ({
                preparing: 'Loading motion context…',
                preparing_media: 'Preparing selected references…',
                generating: messages.generating,
                complete: 'Output ready to apply',
                cancelled: 'Generation cancelled',
              }[job.state] ?? job.state);
        if (job.state === 'complete') {
          run.draft = job.draft;
          run.hasOutput = true;
          onComplete?.(run, job);
          notify('success', messages.ready);
          break;
        }
        if (job.state === 'cancelled') break;
        if (job.state === 'failed') throw new Error(job.error || run.status);
        refreshProgress(run);
        await wait(750);
      }
    } catch (error) {
      if (current()) {
        run.timingUnavailable = !terminal;
        run.status = error.message;
        notify('error', error.message);
      }
    } finally {
      if (current()) {
        run.running = false;
        run.job = null;
        updateRun(run);
      }
    }
  }

  function remove(node) {
    views.delete(node);
    const run = nodes.get(node)?.run;
    if (run?.node === node) {
      run.node = null;
      if (!loading) disposeSession(run);
    }
    reapSessions();
  }

  function resetSession(node) {
    const run = nodes.get(node)?.run;
    if (run?.node !== node) return;
    disposeSession(run);
    run.node = null;
    bindSession(node);
  }
  return { bindSession, views, updateRun, generate, cancelGeneration, resetSession, remove };
}
