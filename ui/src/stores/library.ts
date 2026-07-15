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
  /** Phonetic + typo matching for searches. */
  fuzzy: boolean;
  /** Result ordering while a query is active. */
  sort: 'relevance' | 'date';
  refresh: () => Promise<void>;
  search: (q: string) => Promise<void>;
  setFuzzy: (f: boolean) => void;
  setSort: (s: 'relevance' | 'date') => void;
  remove: (id: string) => Promise<void>;
}

export const useLibrary = create<State>((set, get) => ({
  items: [],
  all: [],
  query: '',
  searching: false,
  fuzzy: false,
  sort: 'relevance',
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
    const { fuzzy, sort } = get();
    let url = `/transcripts?q=${encodeURIComponent(trimmed)}`;
    if (fuzzy) url += '&fuzzy=1';
    if (sort !== 'relevance') url += `&sort=${sort}`;
    try {
      const rows = await api<TranscriptListItem[]>(url);
      // Guard against a stale response winning over a newer query
      if (get().query === q) set({ items: rows, searching: false });
    } catch {
      if (get().query === q) set({ searching: false });
    }
  },
  setFuzzy: (f: boolean) => {
    set({ fuzzy: f });
    const q = get().query;
    if (q.trim()) void get().search(q);
  },
  setSort: (s: 'relevance' | 'date') => {
    set({ sort: s });
    const q = get().query;
    if (q.trim()) void get().search(q);
  },
  remove: async (id: string) => {
    await api(`/transcripts/${id}`, { method: 'DELETE' });
    await get().refresh();
  },
}));
