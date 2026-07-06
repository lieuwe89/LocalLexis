type ApiFn = <T>(path: string, init?: RequestInit) => Promise<T>;

// Mirror of the desktop's _forward_relabel_to_hub: convert a speaker mapping
// into chained CRDT ops so the hub assigns Lamports and the change syncs to
// every device. Uses the browser's admin-bearer api(), not a signed client.
export async function webRelabel(
  api: ApiFn,
  id: string,
  mapping: Record<string, string>,
): Promise<void> {
  const doc = await api<{ _clocks?: Record<string, { lamport?: number }> }>(`/transcripts/${id}`);
  let observed = 0;
  for (const c of Object.values(doc._clocks ?? {})) {
    observed = Math.max(observed, Number(c?.lamport ?? 0));
  }
  for (const [speakerId, newName] of Object.entries(mapping)) {
    const result = await api<{ lamport_assigned?: number }>(`/transcripts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        op: 'relabel', key: `speakers.${speakerId}`, value: newName, lamport_observed: observed,
      }),
    });
    if (typeof result.lamport_assigned === 'number') {
      observed = Math.max(observed, result.lamport_assigned);
    }
  }
}
