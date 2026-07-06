import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptDoc } from '../api/types';

interface State {
  byId: Record<string, TranscriptDoc>;
  load: (id: string) => Promise<TranscriptDoc>;
  relabel: (id: string, mapping: Record<string, string>) => Promise<void>;
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
}));
