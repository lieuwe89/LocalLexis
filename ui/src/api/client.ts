import { platform } from '@/platform';
import type { SidecarAuth } from '@/platform';

export type SidecarInfo = SidecarAuth;

export function sidecarInfo(): Promise<SidecarInfo> {
  return platform.sidecarAuth();
}

// Toggling hub mode respawns the sidecar on a new port/token; drop the cache
// so the next api() call re-discovers it.
export function resetSidecarInfo(): void {
  platform.resetSidecarAuth();
}

export async function baseUrl(): Promise<string> {
  return (await platform.sidecarAuth()).url;
}

const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD', 'PUT', 'DELETE', 'OPTIONS']);

// Only methods that are safe to repeat may be retried on a network error.
// A POST/PATCH can reach the server and have its response lost; resending it
// would duplicate the side effect (e.g. queue a second transcription job).
function isIdempotent(method: string | undefined): boolean {
  return IDEMPOTENT_METHODS.has((method ?? 'GET').toUpperCase());
}

// Opt-in hook fired when the server returns 401. The web shell registers this
// to clear the stored admin token and return to the login screen (spec: "any
// 401 returns to login"). Native never registers it — its loopback bearer
// doesn't expire — so native behavior is unchanged.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const info = await sidecarInfo();
  const headers = new Headers(init?.headers);
  headers.set('Authorization', `Bearer ${info.token}`);
  let lastErr: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(info.url + path, { ...init, headers });
      if (!r.ok) {
        if (r.status === 401) onUnauthorized?.();
        throw new Error(`${r.status} ${path}: ${await r.text()}`);
      }
      return r.json() as Promise<T>;
    } catch (e) {
      lastErr = e;
      if (e instanceof TypeError && isIdempotent(init?.method)) {
        await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
        continue;
      }
      throw e;
    }
  }
  throw lastErr;
}

// Binary variant of api(): same auth + error semantics, returns a Blob.
// Used for audio playback/download — <audio src> can't send bearer headers,
// so we fetch the bytes ourselves and mount an object URL.
export async function apiBlob(path: string): Promise<Blob> {
  const info = await sidecarInfo();
  const r = await fetch(info.url + path, {
    headers: { Authorization: `Bearer ${info.token}` },
  });
  if (!r.ok) {
    if (r.status === 401) onUnauthorized?.();
    throw new Error(`${r.status} ${path}: ${await r.text()}`);
  }
  return r.blob();
}
