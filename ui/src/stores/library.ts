import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptListItem } from '../api/types';

interface State {
  items: TranscriptListItem[];
  refresh: () => Promise<void>;
}

export const useLibrary = create<State>((set) => ({
  items: [],
  refresh: async () => set({ items: await api<TranscriptListItem[]>('/transcripts') }),
}));
