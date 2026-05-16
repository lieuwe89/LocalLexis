import { useEffect, useMemo, useState } from 'react';
import { Icon } from '../primitives/Icon';
import { useLibrary } from '../stores/library';
import { useTranscripts } from '../stores/transcripts';
import type { Route } from '../types/route';

interface Props {
  setRoute: (r: Route) => void;
  setTid: (id: string) => void;
}

function fmtDur(s?: number) {
  if (!s) return '—';
  const m = Math.floor(s / 60);
  const ss = Math.floor(s % 60).toString().padStart(2, '0');
  return `${m}:${ss}`;
}

export function LibraryScreen({ setRoute, setTid }: Props) {
  const items = useLibrary(s => s.items);
  const refresh = useLibrary(s => s.refresh);
  const load = useTranscripts(s => s.load);
  const [q, setQ] = useState('');

  useEffect(() => { refresh(); }, [refresh]);

  const filtered = useMemo(() => {
    const n = q.toLowerCase();
    if (!n) return items;
    return items.filter(i => (i.audio_path || i.id).toLowerCase().includes(n));
  }, [items, q]);

  return (
    <div className="library">
      <div className="lib-search">
        <span className="ico"><Icon name="search" size={14} /></span>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search transcripts…" />
      </div>
      {filtered.length === 0 ? (
        <div className="lib-empty">No transcripts yet — drop an audio file on the Transcribe tab.</div>
      ) : (
        <div className="lib-list">
          {filtered.map(i => {
            const name = (i.audio_path || i.id).split('/').pop() || i.id;
            const date = i.created_at?.slice(0, 10) || '—';
            return (
              <div key={i.id}
                   className={'lib-row' + (i.error ? ' has-error' : '')}
                   onClick={async () => {
                     try { await load(i.id); setTid(i.id); setRoute('complete'); } catch {}
                   }}>
                <span className="ico"><Icon name="doc" size={14} /></span>
                <span className="name">{name}</span>
                <span className="dur">{fmtDur(i.duration_seconds)}</span>
                <span className="spk">{i.speakers ?? 0} speakers</span>
                <span className="lang">{i.language ?? '—'}</span>
                <span className="when">{date}</span>
                <span className="status">{i.error ? '⚠' : '✓'}</span>
                <span className="chev"><Icon name="chev" size={12} /></span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
