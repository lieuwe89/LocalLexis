import { baseUrl } from './client';
import type { SseEvent } from './types';

export async function subscribeJob(jobId: string, onEvent: (e: SseEvent) => void, signal?: AbortSignal): Promise<void> {
  const url = (await baseUrl()) + `/jobs/${jobId}/stream`;
  const resp = await fetch(url, { signal });
  if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = chunk
        .split('\n')
        .filter(l => l.startsWith('data: '))
        .map(l => l.slice(6))
        .join('');
      if (!data) continue;
      try { onEvent(JSON.parse(data) as SseEvent); } catch {}
    }
  }
}
