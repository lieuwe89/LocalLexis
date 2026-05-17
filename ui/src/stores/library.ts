import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptListItem } from '../api/types';

interface State {
  /** Most recently returned listing — what the UI renders right now. */
  items: TranscriptListItem[];
  /** Full unfiltered list, used by sidebars and the "recent" carousel
   *  so they don't go empty while the user is typing a search. */
  all: TranscriptListItem[];
  query: string;
  searching: boolean;
  refresh: () => Promise<void>;
  search: (q: string) => Promise<void>;
}

export const useLibrary = create<State>((set, get) => ({
  items: [],
  all: [],
  query: '',
  searching: false,
  refresh: async () => {
    const rows = await api<TranscriptListItem[]>('/transcripts');
    set({ all: rows });
    if (!get().query) set({ items: rows });
  },
  search: async (q: string) => {
    set({ query: q });
    const trimmed = q.trim();
    if (!trimmed) {
      set({ items: get().all, searching: false });
      return;
    }
    set({ searching: true });
    try {
      const rows = await api<TranscriptListItem[]>(
        `/transcripts?q=${encodeURIComponent(trimmed)}`,
      );
      // Guard against a stale response winning over a newer query
      if (get().query === q) set({ items: rows, searching: false });
    } catch {
      if (get().query === q) set({ searching: false });
    }
  },
}));
