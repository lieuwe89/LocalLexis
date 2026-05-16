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
}

interface JobsState {
  byId: Record<string, JobView>;
  start: (jobId: string) => void;
}

export const useJobs = create<JobsState>((set) => ({
  byId: {},
  start: (jobId) => {
    set(s => ({ byId: { ...s.byId, [jobId]: { id: jobId, status: 'pending', stage: '', percent: 0, lines: [], error: null, paths: {}, transcriptId: null } } }));
    const apply = (mut: (v: JobView) => JobView) =>
      set(s => ({ byId: { ...s.byId, [jobId]: mut(s.byId[jobId]) } }));
    subscribeJob(jobId, (ev: SseEvent) => {
      if (ev.type === 'stage') apply(v => ({ ...v, status: 'running', stage: ev.stage, percent: ev.percent }));
      else if (ev.type === 'line') apply(v => ({ ...v, lines: [...v.lines, { speaker: ev.speaker, ts: ev.ts, text: ev.text }] }));
      else if (ev.type === 'complete') apply(v => ({ ...v, status: 'complete', paths: ev.paths, transcriptId: ev.transcript_id }));
      else if (ev.type === 'error') apply(v => ({ ...v, status: 'failed', error: ev.message }));
    }).catch(err => apply(v => ({ ...v, status: 'failed', error: String(err) })));
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

export async function fetchJob(jobId: string): Promise<JobRecord> {
  return api<JobRecord>(`/jobs/${jobId}`);
}
