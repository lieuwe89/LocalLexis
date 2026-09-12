import { create } from 'zustand';
import { useJobs } from './jobs';

interface State {
  jobId: string | null;
  active: boolean;
  paused: boolean;
  elapsed: number;
  error: string | null;
  deviceId: string | null;
  /** Seconds accumulated before the current run segment (pause bookkeeping). */
  base: number;
  /** Wall-clock ms when the current run segment started; null while paused. */
  resumedAt: number | null;
  start: (jobId: string) => void;
  setActive: (v: boolean) => void;
  setPaused: (v: boolean) => void;
  tick: () => void;
  reset: () => void;
  setDevice: (id: string | null) => void;
}

let unsubJob: (() => void) | null = null;

export const useRecording = create<State>((set, get) => ({
  jobId: null, active: false, paused: false, elapsed: 0, error: null, deviceId: null,
  base: 0, resumedAt: null,
  start: (jobId) => {
    unsubJob?.();
    set({ jobId, active: true, paused: false, elapsed: 0, error: null, base: 0, resumedAt: Date.now() });
    // The sidecar's record job can die instantly (stale audio device, missing
    // mic). Without this the UI stays "Recording" on a 0-byte file forever.
    unsubJob = useJobs.subscribe((s) => {
      const job = s.byId[jobId];
      if (!job || !get().active || get().jobId !== jobId) return;
      if (job.status === 'failed') { set({ active: false, paused: false, error: job.error ?? 'Recording failed' }); unsubJob?.(); unsubJob = null; }
      else if (job.status === 'complete') { set({ active: false, paused: false }); unsubJob?.(); unsubJob = null; }
    });
  },
  setActive: (v) => set({ active: v }),
  setPaused: (v) => set(s => {
    if (v === s.paused) return {};
    if (v) return { paused: true, base: currentElapsed(s), resumedAt: null };
    return { paused: false, resumedAt: Date.now() };
  }),
  // Wall clock, not tick accumulation: WebKit suspends the webview (and its
  // setInterval) when the window is on another desktop; on resume we catch up.
  tick: () => set(s => ({ elapsed: currentElapsed(s) })),
  reset: () => { unsubJob?.(); unsubJob = null; set({ jobId: null, active: false, paused: false, elapsed: 0, error: null, base: 0, resumedAt: null }); },
  setDevice: (id) => set({ deviceId: id }),
}));

function currentElapsed(s: State): number {
  return s.resumedAt === null ? s.base : s.base + (Date.now() - s.resumedAt) / 1000;
}
