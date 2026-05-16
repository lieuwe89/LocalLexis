import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { open as openDialog } from '@tauri-apps/plugin-dialog';

interface Status {
  running: boolean;
  directory: string | null;
  events: { ts: number; kind: string; path?: string; message?: string }[];
}

export function WatchScreen() {
  const [status, setStatus] = useState<Status | null>(null);
  const [recursive, setRecursive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDir, setPendingDir] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setStatus(await api<Status>('/watch/status'));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1000);
    return () => clearInterval(id);
  }, []);

  const pick = async () => {
    const dir = await openDialog({ directory: true, multiple: false });
    if (typeof dir !== 'string') return;
    setPendingDir(dir);
    setError(null);
    setBusy(true);
    try {
      await api('/watch/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directory: dir, recursive }),
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const stop = async () => {
    setError(null);
    setBusy(true);
    try {
      await api('/watch/stop', { method: 'POST' });
      setPendingDir(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const activeDir = status?.running ? status.directory : pendingDir;

  return (
    <div className="watch">
      <div className="watch-control">
        {status?.running ? (
          <>
            <div className="watch-active">Watching <code>{status.directory}</code></div>
            <button className="btn-secondary danger" onClick={stop} disabled={busy}>Stop</button>
          </>
        ) : (
          <>
            <button className="btn-ghost" onClick={pick} disabled={busy}>
              {busy ? 'Starting…' : 'Choose folder…'}
            </button>
            <label className="watch-recursive">
              <input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} /> Recursive
            </label>
            {activeDir && !status?.running && (
              <div className="watch-pending">Selected: <code>{activeDir}</code></div>
            )}
          </>
        )}
      </div>
      {error && (
        <div className="banner warn" style={{ margin: '8px 0' }}>
          Watcher error: {error}
        </div>
      )}
      <div className="watch-events">
        {(status?.events || []).length === 0 && <div className="watch-empty">Waiting for new files…</div>}
        {(status?.events || []).map((e, i) => (
          <div key={i} className={'evt evt-' + e.kind}>
            <span className="ts">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
            <span className="kind">{e.kind}</span>
            <span className="msg">{e.path || e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
