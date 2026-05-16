import { create } from 'zustand';

interface State {
  jobId: string | null;
  active: boolean;
  paused: boolean;
  elapsed: number;
  deviceId: string | null;
  setJob: (id: string | null) => void;
  setActive: (v: boolean) => void;
  setPaused: (v: boolean) => void;
  tick: (delta: number) => void;
  reset: () => void;
  setDevice: (id: string | null) => void;
}

export const useRecording = create<State>((set) => ({
  jobId: null, active: false, paused: false, elapsed: 0, deviceId: null,
  setJob: (id) => set({ jobId: id }),
  setActive: (v) => set({ active: v }),
  setPaused: (v) => set({ paused: v }),
  tick: (delta) => set(s => ({ elapsed: s.elapsed + delta })),
  reset: () => set({ jobId: null, active: false, paused: false, elapsed: 0 }),
  setDevice: (id) => set({ deviceId: id }),
}));
