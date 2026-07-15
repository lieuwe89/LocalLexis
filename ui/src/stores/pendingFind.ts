import { create } from 'zustand';

/**
 * One-shot handoff from a library search hit to the transcript view:
 * "open transcript `tid` with the find bar pre-filled and jump to
 * `segmentIndex`". Consumed (cleared) by CompleteScreen on mount.
 */
export interface PendingFind {
  tid: string;
  query: string;
  fuzzy: boolean;
  segmentIndex: number;
}

interface State {
  pending: PendingFind | null;
  set: (p: PendingFind) => void;
  /** Return and clear the pending find if it targets `tid`; else null. */
  consume: (tid: string) => PendingFind | null;
}

export const usePendingFind = create<State>((set, get) => ({
  pending: null,
  set: (p) => set({ pending: p }),
  consume: (tid) => {
    const p = get().pending;
    if (!p || p.tid !== tid) return null;
    set({ pending: null });
    return p;
  },
}));
