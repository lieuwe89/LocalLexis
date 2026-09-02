import { invoke } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';
import { audioDir as tauriAudioDir, join as tauriJoin } from '@tauri-apps/api/path';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { openPath as tauriOpenPath } from '@tauri-apps/plugin-opener';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { checkForUpdates as tauriCheckForUpdates } from '../updater.impl';

export interface SidecarAuth {
  url: string;
  token: string;
}

// A drag-and-drop event surfaced to screens. `enter`/`over`/`leave` drive
// drop-zone highlighting; `drop` carries the dropped file paths. Native maps
// Tauri's onDragDropEvent payload; the web build never mounts capture screens
// so its impl is an inert no-op.
export type FileDropEvent =
  | { type: 'enter' | 'over' | 'leave' }
  | { type: 'drop'; paths: string[] };

// The host-capability surface every shared screen depends on. The web impl
// (web.ts) provides browser equivalents or no-ops; screens import '@/platform'
// and never '@tauri-apps/*' directly, so the --mode hub bundle is tauri-free.
export interface Platform {
  // API base URL + bearer token. Native: discovered sidecar. Web: origin + stored token.
  sidecarAuth(): Promise<SidecarAuth>;
  resetSidecarAuth(): void;
  appVersion(): Promise<string>;
  openPath(path: string): Promise<void>;
  openFileDialog(opts?: { directory?: boolean; multiple?: boolean; filters?: { name: string; extensions: string[] }[] }): Promise<string | string[] | null>;
  audioDir(): Promise<string>;
  pathJoin(...parts: string[]): Promise<string>;
  onFileDrop(cb: (event: FileDropEvent) => void): Promise<() => void>;
  checkForUpdates(silent?: boolean): Promise<void>;
  // Relabel a transcript's speakers. Native: existing /relabel route (which
  // forwards CRDT ops for hub-origin docs). Web: CRDT ops direct to the hub.
  relabelTranscript(id: string, mapping: Record<string, string>): Promise<void>;
  // Web only: save a transcript's .txt/.json as a browser download (no
  // filesystem to openPath into). Absent on native, where openPath is used.
  downloadTranscriptFile?(tid: string, fmt: 'txt' | 'json'): Promise<void>;
}

let cached: SidecarAuth | null = null;
let readyPromise: Promise<SidecarAuth> | null = null;

const READY_TIMEOUT_MS = 120_000;
const POLL_INTERVAL_MS = 200;

async function discoverAndProbe(): Promise<SidecarAuth> {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  let url: string | null = null;
  let token = '';
  while (Date.now() < deadline) {
    if (!url || !token) {
      const info = (await invoke('sidecar_url')) as { url: string | null; token: string };
      url = info.url;
      token = info.token;
    }
    if (url && token) {
      try {
        const r = await fetch(url + '/health', { headers: { Authorization: `Bearer ${token}` } });
        if (r.ok) return { url, token };
      } catch {}
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error('sidecar did not become healthy within 120 seconds');
}

export const platform: Platform = {
  async sidecarAuth() {
    if (cached) return cached;
    if (!readyPromise) {
      readyPromise = discoverAndProbe().then(info => { cached = info; return info; });
    }
    return readyPromise;
  },
  resetSidecarAuth() {
    cached = null;
    readyPromise = null;
  },
  appVersion: () => getVersion(),
  openPath: (p) => tauriOpenPath(p),
  openFileDialog: (opts) => openDialog(opts) as Promise<string | string[] | null>,
  audioDir: () => tauriAudioDir(),
  pathJoin: (...parts) => tauriJoin(...parts),
  async onFileDrop(cb) {
    const unlisten = await getCurrentWebview().onDragDropEvent((event) => {
      const t = event.payload.type;
      if (t === 'drop') cb({ type: 'drop', paths: event.payload.paths });
      else if (t === 'enter' || t === 'over' || t === 'leave') cb({ type: t });
    });
    return unlisten;
  },
  checkForUpdates: (silent) => tauriCheckForUpdates(silent),
  async relabelTranscript(id, mapping) {
    const { api } = await import('../api/client');
    await api(`/transcripts/${id}/relabel`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mapping),
    });
  },
};
