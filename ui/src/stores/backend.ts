import { create } from 'zustand';
import { baseUrl } from '../api/client';

export type BackendStatus = 'starting' | 'ready' | 'failed';

interface State {
  status: BackendStatus;
  elapsedMs: number;
  error: string | null;
  start: () => void;
  /** Test-only: resets closure state so a subsequent start() runs from scratch. */
  _resetForTests: () => void;
}

const TICK_MS = 250;

export const useBackend = create<State>((set, get) => {
  let started = false;
  let startTs = 0;
  let tickHandle: ReturnType<typeof setInterval> | null = null;

  const stopTicking = () => {
    if (tickHandle !== null) {
      clearInterval(tickHandle);
      tickHandle = null;
    }
  };

  return {
    status: 'starting',
    elapsedMs: 0,
    error: null,
    start: () => {
      if (started) return;
      started = true;
      startTs = Date.now();
      tickHandle = setInterval(() => {
        if (get().status === 'starting') {
          set({ elapsedMs: Date.now() - startTs });
        }
      }, TICK_MS);

      baseUrl()
        .then(() => {
          set({ status: 'ready', elapsedMs: Date.now() - startTs });
          stopTicking();
        })
        .catch((e) => {
          const msg = e instanceof Error ? e.message : String(e);
          set({ status: 'failed', error: msg, elapsedMs: Date.now() - startTs });
          stopTicking();
        });
    },
    _resetForTests: () => {
      stopTicking();
      started = false;
      startTs = 0;
    },
  };
});
