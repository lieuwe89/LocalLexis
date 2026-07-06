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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const info = await sidecarInfo();
  const headers = new Headers(init?.headers);
  headers.set('Authorization', `Bearer ${info.token}`);
  let lastErr: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(info.url + path, { ...init, headers });
      if (!r.ok) throw new Error(`${r.status} ${path}: ${await r.text()}`);
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
