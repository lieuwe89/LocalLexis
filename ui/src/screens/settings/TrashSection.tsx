import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { TrashItem } from '../../api/types';

function fmtSize(b: number) {
  if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(b / 1e3))} KB`;
}

export function TrashSection() {
  const [items, setItems] = useState<TrashItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api<TrashItem[]>('/trash').then(setItems).catch(() => setItems([]));
  useEffect(() => { refresh(); }, []);

  const restore = async (t: TrashItem) => {
    setError(null);
    try {
      await api(`/trash/${encodeURIComponent(t.tid)}/restore`, { method: 'POST' });
      await refresh();
    } catch (e) {
      setError(`Restore failed: ${e}`);
    }
  };

  const empty = async () => {
    if (!window.confirm(
      `Permanently delete ${items.length} item(s) from the trash?\n\nThis cannot be undone.`,
    )) return;
    setError(null);
    try {
      await api('/trash', { method: 'DELETE' });
      await refresh();
    } catch (e) {
      setError(`Empty trash failed: ${e}`);
    }
  };

  return (
    <section className="trash-section" style={{ marginTop: '2rem', borderTop: '1px solid var(--rule)', paddingTop: '1.25rem' }}>
      <h2 style={{ margin: '0 0 0.5rem' }}>Trash ({items.length})</h2>
      {error && <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{error}</p>}
      {items.length === 0 ? (
        <p style={{ color: 'var(--ink-muted)' }}>Trash is empty.</p>
      ) : (
        <>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {items.map(t => (
              <li key={t.tid} style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', padding: '0.5rem 0', borderBottom: '1px solid var(--rule, #e5e0d3)' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>{t.title || t.tid}</strong>
                  <div style={{ fontSize: '0.85em', color: 'var(--ink-muted)' }}>
                    deleted {t.deleted_at ? new Date(t.deleted_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—'} · {fmtSize(t.size_bytes)}
                  </div>
                </div>
                <button type="button" onClick={() => restore(t)}>Restore</button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={empty}>Empty trash</button>
        </>
      )}
    </section>
  );
}
