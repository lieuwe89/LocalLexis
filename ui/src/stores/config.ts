import { create } from 'zustand';
import { api } from '../api/client';
import type { ConfigDto } from '../api/types';

interface State {
  cfg: ConfigDto | null;
  load: () => Promise<void>;
  patch: (updates: Partial<ConfigDto> & { hf_token?: string }) => Promise<void>;
}

export const useConfig = create<State>((set) => ({
  cfg: null,
  load: async () => set({ cfg: await api<ConfigDto>('/config') }),
  patch: async (updates) => {
    const cfg = await api<ConfigDto>('/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    set({ cfg });
  },
}));
