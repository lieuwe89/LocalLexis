import { useEffect, useState } from 'react';
import { Icon } from '../primitives/Icon';
import { useLibrary } from '../stores/library';
import { useTranscripts } from '../stores/transcripts';
import { usePendingFind } from '../stores/pendingFind';
import { AskPanel } from './AskPanel';
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

function fmtWhen(iso?: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function fmtTs(secs: number) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function LibraryScreen({ setRoute, setTid }: Props) {
  const items = useLibrary(s => s.items);
  const all = useLibrary(s => s.all);
  const refresh = useLibrary(s => s.refresh);
  const search = useLibrary(s => s.search);
  const searching = useLibrary(s => s.searching);
  const remove = useLibrary(s => s.remove);
  const load = useTranscripts(s => s.load);
  const rename = useTranscripts(s => s.rename);
  const fuzzy = useLibrary(s => s.fuzzy);
  const setFuzzy = useLibrary(s => s.setFuzzy);
  const semantic = useLibrary(s => s.semantic);
  const setSemantic = useLibrary(s => s.setSemantic);
  const sort = useLibrary(s => s.sort);
  const setSort = useLibrary(s => s.setSort);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [editing, setEditing] = useState<{ id: string; draft: string } | null>(null);

  useEffect(() => { refresh(); }, [refresh]);

  // Debounce so we don't hit /transcripts on every keystroke.
  useEffect(() => {
    setExpanded(null); // new search → collapse any expanded hit list
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
        <button
          className={'lib-toggle' + (fuzzy ? ' on' : '')}
          aria-label="Fuzzy matching"
          aria-pressed={fuzzy}
          title="Fuzzy matching — also finds words that sound alike"
          onClick={() => setFuzzy(!fuzzy)}
        >~ fuzzy</button>
        <button
          className={'lib-toggle' + (semantic ? ' on' : '')}
          aria-label="Semantic search"
          aria-pressed={semantic}
          title="Semantic search — match by meaning instead of exact words"
          onClick={() => setSemantic(!semantic)}
        >≈ meaning</button>
        {isSearching && (
          <button
            className="lib-toggle"
            aria-label="Sort order"
            title="Toggle between relevance and date ordering"
            onClick={() => setSort(sort === 'relevance' ? 'date' : 'relevance')}
          >{sort === 'relevance' ? '↓ relevance' : '↓ date'}</button>
        )}
      </div>
      <AskPanel setRoute={setRoute} setTid={setTid} />
      {items.length === 0 ? (
        <div className="lib-empty">
          {libraryEmpty
            ? 'No transcripts yet — drop an audio file on the Transcribe tab.'
            : <>No transcripts match <em>“{q.trim()}”</em>.</>}
        </div>
      ) : (
        <div className="lib-list">
          {items.map(i => {
            const name = i.title || (i.audio_path || i.id).split('/').pop() || i.id;
            const when = fmtWhen(i.created_at);
            return (
              <div key={i.id}
                   className={'lib-row' + (i.error ? ' has-error' : '') + ((i.hits?.length || i.snippet_parts?.length) ? ' has-snippet' : '')}
                   onClick={async () => {
                     try { await load(i.id); setTid(i.id); setRoute('complete'); } catch {}
                   }}>
                <div className="lib-row-main">
                  <span className="ico"><Icon name="doc" size={14} /></span>
                  {editing?.id === i.id ? (
                    <input
                      className="rename-input"
                      autoFocus
                      value={editing.draft}
                      onClick={e => e.stopPropagation()}
                      onChange={e => setEditing({ id: i.id, draft: e.target.value })}
                      onKeyDown={async e => {
                        if (e.key === 'Enter') {
                          if (editing.draft.trim()) {
                            await rename(i.id, editing.draft.trim());
                            setEditing(null);
                            refresh();
                          }
                        } else if (e.key === 'Escape') {
                          setEditing(null);
                        }
                      }}
                    />
                  ) : (
                    <span className="name">
                      {name}
                      {i.origin === 'hub' && <span className="origin-badge" title="Synced from hub">hub</span>}
                    </span>
                  )}
                  <span className="dur">{fmtDur(i.duration_seconds)}</span>
                  <span className="spk">{i.speakers ?? 0} speakers</span>
                  <span className="lang">{i.language ?? '—'}</span>
                  <span className="when">{when}</span>
                  <span className="status">{i.error ? '⚠' : '✓'}</span>
                  <button className="icon-btn row-action" aria-label={`Rename ${name}`} title="Rename"
                    onClick={e => { e.stopPropagation(); setEditing({ id: i.id, draft: i.title || name }); }}>
                    <Icon name="pencil" size={13} />
                  </button>
                  <button className="icon-btn row-action" aria-label={`Delete ${name}`} title="Move to trash"
                    onClick={async e => {
                      e.stopPropagation();
                      if (window.confirm(`Move '${name}' to trash?\n\nYou can restore it from Settings → Trash.`)) {
                        await remove(i.id).catch(err => window.alert(`Delete failed: ${err}`));
                      }
                    }}>
                    <Icon name="trash" size={13} />
                  </button>
                  <span className="chev"><Icon name="chev" size={12} /></span>
                </div>
                {i.hits && i.hits.length > 0 ? (
                  <div className="lib-hits">
                    {(expanded === i.id ? i.hits : i.hits.slice(0, 3)).map(h => (
                      <button
                        key={h.segment_index}
                        className="lib-hit"
                        aria-label={`Jump to match at segment ${h.segment_index}`}
                        onClick={async e => {
                          e.stopPropagation();
                          // The rendered hits came from the store's query, not
                          // the (debounced) input — use the store so a mid-edit
                          // click can't record a mismatched find query.
                          usePendingFind.getState().set({
                            tid: i.id,
                            // Semantic hits have no lexical query — empty query
                            // makes the transcript view fall back to a plain
                            // segment scroll.
                            query: semantic ? '' : useLibrary.getState().query.trim(),
                            fuzzy: semantic ? false : fuzzy,
                            segmentIndex: h.segment_index,
                          });
                          try { await load(i.id); setTid(i.id); setRoute('complete'); } catch {}
                        }}
                      >
                        {h.start != null && <span className="lib-hit-ts">{fmtTs(h.start)}</span>}
                        <span className="lib-hit-text">
                          {h.snippet_parts.map((p, idx) =>
                            p.match
                              ? <mark key={idx}>{p.text}</mark>
                              : <span key={idx}>{p.text}</span>
                          )}
                        </span>
                      </button>
                    ))}
                    {i.hits.length > 3 && expanded !== i.id && (
                      <button
                        className="lib-hit-more"
                        onClick={e => { e.stopPropagation(); setExpanded(i.id); }}
                      >
                        {/* Promise only what expanding reveals; hits[] is capped
                            server-side, so surface the true total separately. */}
                        +{i.hits.length - 3} more
                        {i.total_hits != null && i.total_hits > i.hits.length ? ` (of ${i.total_hits})` : ''}
                      </button>
                    )}
                  </div>
                ) : i.snippet_parts && i.snippet_parts.length > 0 && (
                  <div className="lib-snippet">
                    {i.snippet_parts.map((p, idx) =>
                      p.match
                        ? <mark key={idx}>{p.text}</mark>
                        : <span key={idx}>{p.text}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
