import { useEffect, useState } from 'react';
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
  const all = useLibrary(s => s.all);
  const refresh = useLibrary(s => s.refresh);
  const search = useLibrary(s => s.search);
  const searching = useLibrary(s => s.searching);
  const load = useTranscripts(s => s.load);
  const [q, setQ] = useState('');

  useEffect(() => { refresh(); }, [refresh]);

  // Debounce so we don't hit /transcripts on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => { search(q); }, 200);
    return () => clearTimeout(t);
  }, [q, search]);

  const isSearching = q.trim().length > 0;
  const libraryEmpty = all.length === 0;

  return (
    <div className="library">
      <div className="lib-search">
        <span className="ico"><Icon name="search" size={14} /></span>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search transcripts by content, filename, speaker, or language…"
        />
        {searching && <span className="lib-search-spinner" aria-label="Searching" />}
        {isSearching && (
          <button
            className="lib-search-clear"
            onClick={() => setQ('')}
            title="Clear search"
            aria-label="Clear search"
          >×</button>
        )}
      </div>
      {items.length === 0 ? (
        <div className="lib-empty">
          {libraryEmpty
            ? 'No transcripts yet — drop an audio file on the Transcribe tab.'
            : <>No transcripts match <em>“{q.trim()}”</em>.</>}
        </div>
      ) : (
        <div className="lib-list">
          {items.map(i => {
            const name = (i.audio_path || i.id).split('/').pop() || i.id;
            const date = i.created_at?.slice(0, 10) || '—';
            return (
              <div key={i.id}
                   className={'lib-row' + (i.error ? ' has-error' : '') + (i.snippet ? ' has-snippet' : '')}
                   onClick={async () => {
                     try { await load(i.id); setTid(i.id); setRoute('complete'); } catch {}
                   }}>
                <div className="lib-row-main">
                  <span className="ico"><Icon name="doc" size={14} /></span>
                  <span className="name">{name}</span>
                  <span className="dur">{fmtDur(i.duration_seconds)}</span>
                  <span className="spk">{i.speakers ?? 0} speakers</span>
                  <span className="lang">{i.language ?? '—'}</span>
                  <span className="when">{date}</span>
                  <span className="status">{i.error ? '⚠' : '✓'}</span>
                  <span className="chev"><Icon name="chev" size={12} /></span>
                </div>
                {i.snippet && (
                  <div
                    className="lib-snippet"
                    // FTS5 snippet() wraps matches in <mark> tags we control.
                    dangerouslySetInnerHTML={{ __html: i.snippet }}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
