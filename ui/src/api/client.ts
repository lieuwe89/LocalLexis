import { invoke } from '@tauri-apps/api/core';

let cached: string | null = null;

export async function baseUrl(): Promise<string> {
  if (cached) return cached;
  for (let i = 0; i < 50; i++) {
    const u = (await invoke('sidecar_url')) as string | null;
    if (u) { cached = u; return u; }
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error('sidecar did not start within 5 seconds');
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const u = await baseUrl();
  const r = await fetch(u + path, init);
  if (!r.ok) throw new Error(`${r.status} ${path}: ${await r.text()}`);
  return r.json() as Promise<T>;
}
