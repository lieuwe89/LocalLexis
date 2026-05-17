import { create } from 'zustand';
import { api } from '../api/client';
import { subscribeJob } from '../api/sse';
import type { JobRecord, SseEvent } from '../api/types';

interface JobView {
  id: string;
  status: 'pending' | 'running' | 'complete' | 'failed';
  stage: string;
  percent: number;
  lines: { speaker: string; ts: number; text: string }[];
  error: string | null;
  paths: Record<string, string>;
  transcriptId: string | null;
  startedAt: number;
}

interface JobsState {
  byId: Record<string, JobView>;
  start: (jobId: string) => void;
}

export const useJobs = create<JobsState>((set, get) => ({
  byId: {},
  start: (jobId) => {
    set(s => ({ byId: { ...s.byId, [jobId]: { id: jobId, status: 'pending', stage: '', percent: 0, lines: [], error: null, paths: {}, transcriptId: null, startedAt: Date.now() } } }));
    const apply = (mut: (v: JobView) => JobView) =>
      set(s => ({ byId: { ...s.byId, [jobId]: mut(s.byId[jobId]) } }));

    // Polling fallback. SSE only delivers events that arrive *after* a
    // subscriber connects; for fast jobs (or slow Tauri webview startup) the
    // stream can miss early events — or, for tiny clips, the entire job —
    // leaving the UI stuck in `pending`. Poll /jobs/{id} until terminal so
    // the store catches up regardless of what SSE delivered.
    const poll = setInterval(async () => {
      try {
        const rec = await fetchJob(jobId);
        const current = get().byId[jobId];
        if (!current || current.status === 'complete' || current.status === 'failed') {
          clearInterval(poll);
          return;
        }
        if (rec.status === 'complete') {
          apply(v => ({ ...v, status: 'complete', stage: rec.stage, percent: rec.percent, paths: rec.paths, transcriptId: rec.transcript_id }));
          clearInterval(poll);
        } else if (rec.status === 'failed') {
          apply(v => ({ ...v, status: 'failed', stage: rec.stage, error: rec.error }));
          clearInterval(poll);
        } else if (rec.stage && rec.stage !== current.stage) {
          // SSE missed a stage transition — sync it.
          apply(v => ({ ...v, status: 'running', stage: rec.stage, percent: rec.percent }));
        } else if (rec.status === 'running' && current.status === 'pending') {
          apply(v => ({ ...v, status: 'running', stage: rec.stage, percent: rec.percent }));
        }
      } catch {
        // ignore transient errors; next tick will retry
      }
    }, 1500);

    subscribeJob(jobId, (ev: SseEvent) => {
      if (ev.type === 'stage') apply(v => ({ ...v, status: 'running', stage: ev.stage, percent: ev.percent }));
      else if (ev.type === 'line') apply(v => ({ ...v, lines: [...v.lines, { speaker: ev.speaker, ts: ev.ts, text: ev.text }] }));
      else if (ev.type === 'complete') { apply(v => ({ ...v, status: 'complete', paths: ev.paths, transcriptId: ev.transcript_id })); clearInterval(poll); }
      else if (ev.type === 'error') { apply(v => ({ ...v, status: 'failed', error: ev.message })); clearInterval(poll); }
    }).catch(err => { apply(v => ({ ...v, status: 'failed', error: String(err) })); clearInterval(poll); });
  },
}));

export async function startTranscribe(path: string, opts: { language?: string; num_speakers?: number; backend?: string } = {}): Promise<string> {
  const { job_id } = await api<{ job_id: string }>('/jobs/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, ...opts }),
  });
  useJobs.getState().start(job_id);
  return job_id;
}

export async function startRecord(out: string, device?: string): Promise<string> {
  const { job_id } = await api<{ job_id: string }>('/jobs/record', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ out, device }),
  });
  useJobs.getState().start(job_id);
  return job_id;
}

export async function stopRecord(jobId: string): Promise<void> {
  await api(`/jobs/${jobId}/stop`, { method: 'POST' });
}

export async function cancelTranscribe(jobId: string): Promise<void> {
  await api(`/jobs/${jobId}/cancel`, { method: 'POST' });
}

export async function fetchJob(jobId: string): Promise<JobRecord> {
  return api<JobRecord>(`/jobs/${jobId}`);
}
