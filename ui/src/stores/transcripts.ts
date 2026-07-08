import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptDoc, JobRecord } from '../api/types';

interface State {
  byId: Record<string, TranscriptDoc>;
  load: (id: string) => Promise<TranscriptDoc>;
  relabel: (id: string, mapping: Record<string, string>) => Promise<void>;
  patchOp: (id: string, op: string, key: string, value: unknown) => Promise<void>;
  rename: (id: string, title: string) => Promise<void>;
  editSegment: (id: string, index: number, text: string) => Promise<void>;
  summarize: (id: string, opts?: { pollMs?: number }) => Promise<void>;
}

export const useTranscripts = create<State>((set) => ({
  byId: {},
  load: async (id) => {
    const doc = await api<TranscriptDoc>(`/transcripts/${id}`);
    set(s => ({ byId: { ...s.byId, [id]: doc } }));
    return doc;
  },
  relabel: async (id, mapping) => {
    const { platform } = await import('@/platform');
    await platform.relabelTranscript(id, mapping);
    await useTranscripts.getState().load(id);
  },
  patchOp: async (id, op, key, value) => {
    const doc = useTranscripts.getState().byId[id];
    let observed = 0;
    for (const c of Object.values(doc?._clocks ?? {})) {
      if (c && typeof c.lamport === 'number') observed = Math.max(observed, c.lamport);
    }
    await api(`/transcripts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op, key, value, lamport_observed: observed }),
    });
    await useTranscripts.getState().load(id);
  },
  rename: async (id, title) => {
    await useTranscripts.getState().patchOp(id, 'set_title', 'title', title);
  },
  editSegment: async (id, index, text) => {
    await useTranscripts.getState().patchOp(id, 'edit_segment', `segments.${index}.text`, text);
  },
  summarize: async (id, opts) => {
    const pollMs = opts?.pollMs ?? 1500;
    const { job_id } = await api<{ job_id: string }>(`/transcripts/${id}/summarize`, { method: 'POST' });
    for (;;) {
      const rec = await api<JobRecord>(`/jobs/${job_id}`);
      if (rec.status === 'complete') break;
      if (rec.status === 'failed') throw new Error(rec.error ?? 'summarize failed');
      await new Promise(r => setTimeout(r, pollMs));
    }
    await useTranscripts.getState().load(id);
  },
}));
