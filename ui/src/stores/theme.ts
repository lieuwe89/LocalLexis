import { create } from 'zustand';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'localscribe.theme';

function readInitial(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'dark' || v === 'light') return v;
  } catch {}
  return 'dark';
}

function apply(t: Theme) {
  document.documentElement.setAttribute('data-theme', t);
}

interface State {
  theme: Theme;
  toggle: () => void;
}

const initial = readInitial();
apply(initial);

export const useTheme = create<State>((set, get) => ({
  theme: initial,
  toggle: () => {
    const next: Theme = get().theme === 'dark' ? 'light' : 'dark';
    apply(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch {}
    set({ theme: next });
  },
}));
