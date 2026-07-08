import { useState, useMemo, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Icon } from '../primitives/Icon';
import { SPEAKER_COLORS } from '../primitives/colors';
import type { TranscriptDoc } from '../api/types';
import { platform } from '@/platform';
import { AudioPanel } from './AudioPanel';

interface Props {
  doc: TranscriptDoc;
  txtPath?: string;
  jsonPath?: string;
  tid?: string;
  onRelabel: (mapping: Record<string, string>) => Promise<void> | void;
  onRename?: (title: string) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
  onEditSegment?: (index: number, text: string) => Promise<void> | void;
  onSummarize?: () => Promise<void>;
}

function fmtTimestamp(secs: number) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function highlight(text: string, q: string): ReactNode {
  if (!q) return text;
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const parts: ReactNode[] = [];
  let pos = 0;
  for (let hit = lower.indexOf(ql); hit !== -1; hit = lower.indexOf(ql, pos)) {
    if (hit > pos) parts.push(text.slice(pos, hit));
    parts.push(<mark key={hit}>{text.slice(hit, hit + q.length)}</mark>);
    pos = hit + q.length;
  }
  parts.push(text.slice(pos));
  return parts;
}

export function CompleteScreen({ doc, txtPath, jsonPath, tid, onRelabel, onRename, onDelete, onEditSegment, onSummarize }: Props) {
  const speakerIds = useMemo(() => Object.keys(doc.speakers), [doc.speakers]);
  const [labels, setLabels] = useState<Record<string, string>>(() => ({ ...doc.speakers }));
  const [applied, setApplied] = useState(true);
  const [titleEdit, setTitleEdit] = useState<string | null>(null);
  const [segEdit, setSegEdit] = useState<{ i: number; draft: string } | null>(null);
  const [findQ, setFindQ] = useState('');
  const [findIdx, setFindIdx] = useState(0);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const speakerIndex = useMemo(() => {
    const m: Record<string, number> = {};
    speakerIds.forEach((id, i) => { m[id] = i; });
    return m;
  }, [speakerIds]);

  const renderedText = useMemo(() =>
    doc.segments
      .map(s => `[${fmtTimestamp(s.start)}] ${labels[s.speaker] || s.speaker}: ${s.text}`)
      .join('\n') + '\n',
    [doc.segments, labels]
  );

  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(renderedText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // clipboard API can fail in restricted contexts; ignore
    }
  };
  const onOpenTxt = () => txtPath && platform.openPath(txtPath).catch((e) => console.error('open txt failed:', e));
  const onOpenJson = () => jsonPath && platform.openPath(jsonPath).catch((e) => console.error('open json failed:', e));

  const apply = async () => {
    const changed: Record<string, string> = {};
    for (const id of speakerIds) {
      if (labels[id] !== doc.speakers[id]) changed[id] = labels[id];
    }
    if (Object.keys(changed).length > 0) {
      await onRelabel(changed);
    }
    setApplied(true);
  };

  const matches = useMemo(() => {
    const q = findQ.trim().toLowerCase();
    if (!q) return [];
    return doc.segments.reduce<number[]>((acc, s, i) => {
      if (s.text.toLowerCase().includes(q)) acc.push(i);
      return acc;
    }, []);
  }, [doc.segments, findQ]);

  useEffect(() => { setFindIdx(0); }, [findQ]);
  const currentMatchSeg = matches.length ? matches[findIdx % matches.length] : null;

  const seekRef = useRef<((secs: number) => void) | null>(null);

  const segRefs = useRef<Record<number, HTMLDivElement | null>>({});
  useEffect(() => {
    if (currentMatchSeg !== null) {
      segRefs.current[currentMatchSeg]?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [currentMatchSeg]);

  const step = (dir: 1 | -1) => {
    if (!matches.length) return;
    setFindIdx(i => (i + dir + matches.length) % matches.length);
  };

  const date = doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '—';
  const dur = doc.duration_seconds
    ? `${Math.floor(doc.duration_seconds / 60)}:${Math.floor(doc.duration_seconds % 60).toString().padStart(2, '0')}`
    : '—';
  const model = doc.models?.asr?.split(':')[1] || doc.models?.asr || '—';
  const fileTitle = doc.audio_path?.split('/').pop()?.replace(/\.[^.]+$/, '') || 'Transcript';
  const title = doc.title || fileTitle;

  return (
    <div className="complete">
      <div className="doc-head">
        <div className="title-stack">
          <div className="file-meta">
            <span>{doc.audio_path}</span>
            <span style={{ color: 'var(--ink-faint)' }}>·</span>
            <span>local</span>
          </div>
          {titleEdit !== null ? (
            <input
              className="title-input"
              autoFocus
              value={titleEdit}
              onChange={e => setTitleEdit(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter') {
                  if (titleEdit.trim()) {
                    await onRename?.(titleEdit.trim());
                    setTitleEdit(null);
                  }
                } else if (e.key === 'Escape') {
                  setTitleEdit(null);
                }
              }}
              onBlur={() => setTitleEdit(null)}
            />
          ) : (
            <h1>
              {title}
              {onRename && (
                <button className="icon-btn" aria-label="Rename transcript" title="Rename"
                  onClick={() => setTitleEdit(title)}>
                  <Icon name="pencil" size={14} />
                </button>
              )}
            </h1>
          )}
          <div className="subline">
            <span>{dur}</span><span className="sep">·</span>
            <span>{speakerIds.length} speakers</span><span className="sep">·</span>
            <span>{doc.language || '—'}</span><span className="sep">·</span>
            <span>{model}</span><span className="sep">·</span>
            <span>{date}</span>
          </div>
        </div>
        <div className="actions">
          <button className="icon-btn" title={copied ? 'Copied!' : 'Copy transcript'} onClick={onCopy}>
            <Icon name={copied ? 'check' : 'copy'} size={15} stroke={copied ? 2 : 1.5} />
          </button>
          <button
            className="icon-btn"
            title={txtPath ? `Open ${txtPath}` : 'No .txt file available'}
            onClick={onOpenTxt}
            disabled={!txtPath}
          >
            <Icon name="doc" size={15} />
          </button>
          <button
            className="icon-btn"
            title={jsonPath ? `Open ${jsonPath}` : 'No .json file available'}
            onClick={onOpenJson}
            disabled={!jsonPath}
          >
            <Icon name="braces" size={15} />
          </button>
          {onDelete && (
            <button className="icon-btn" aria-label="Delete transcript" title="Move to trash"
              onClick={async () => {
                if (window.confirm(`Move '${title}' to trash?\n\nYou can restore it from Settings → Trash.`)) {
                  await onDelete();
                }
              }}>
              <Icon name="trash" size={15} />
            </button>
          )}
          {onSummarize && (
            <button className="btn-summarize" aria-label="Summarize transcript"
                    title={doc.summary ? 'Regenerate the summary' : 'Summarize this transcript'}
                    disabled={summarizing}
                    onClick={async () => {
                      setSummarizing(true); setSummaryError(null);
                      try { await onSummarize(); }
                      catch (e) { setSummaryError(String(e)); }
                      finally { setSummarizing(false); }
                    }}>
              {summarizing
                ? <span className="activity-spinner" aria-hidden="true" />
                : <Icon name="sparkle" size={14} />}
              <span>{summarizing ? 'Summarizing…' : doc.summary ? 'Regenerate' : 'Summarize'}</span>
            </button>
          )}
        </div>
      </div>

      {tid && (
        <AudioPanel
          tid={tid}
          filename={doc.audio_path?.split('/').pop() || `${title}.audio`}
          onReady={fn => { seekRef.current = fn; }}
        />
      )}

      <div className="relabel">
        <div className="relabel-head">
          <span className="lbl">Speakers · {speakerIds.length} detected</span>
          <button className="btn-apply" disabled={applied} onClick={apply}>
            {applied
              ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon name="check" size={11} stroke={2} /> Applied</span>
              : 'Apply'}
          </button>
        </div>
        <div className="relabel-grid">
          {speakerIds.map(id => {
            const i = speakerIndex[id] % SPEAKER_COLORS.length;
            return (
              <div key={id} className="relabel-row">
                <span className="swatch" style={{ background: SPEAKER_COLORS[i] }} />
                <span className="src">{id}</span>
                <span className="arrow">→</span>
                <input
                  value={labels[id] || ''}
                  placeholder="Name…"
                  onChange={(e) => {
                    setLabels(prev => ({ ...prev, [id]: e.target.value }));
                    setApplied(false);
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>

      {summaryError && <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{summaryError}</p>}
      {doc.summary && (
        <div className="summary-panel">
          <div className="summary-head">
            <span className="lbl">Summary</span>
            {doc.summary_meta && (
              <span className="summary-meta">{doc.summary_meta.model} · {new Date(doc.summary_meta.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</span>
            )}
          </div>
          <div className="summary-body">{doc.summary}</div>
        </div>
      )}

      <div className="doc-find">
        <Icon name="search" size={13} />
        <input
          aria-label="Search in transcript"
          placeholder="Find in transcript…"
          value={findQ}
          onChange={e => setFindQ(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') step(e.shiftKey ? -1 : 1); }}
        />
        {findQ.trim() && (
          <>
            <span className="find-count">{matches.length ? `${(findIdx % matches.length) + 1} / ${matches.length}` : '0 / 0'}</span>
            <button className="icon-btn" aria-label="Previous match" onClick={() => step(-1)}>↑</button>
            <button className="icon-btn" aria-label="Next match" onClick={() => step(1)}>↓</button>
          </>
        )}
      </div>

      <div className="transcript">
        {doc.segments.map((seg, i) => {
          const idx = speakerIndex[seg.speaker] ?? 0;
          return (
            <div key={i} className={'turn' + (i === currentMatchSeg ? ' find-current' : '')}
                 ref={el => { segRefs.current[i] = el; }}>
              <div className="ts ts-seek" role="button" title="Play from here"
                   onClick={() => seekRef.current?.(seg.start)}>{fmtTimestamp(seg.start)}</div>
              <div className="spk" data-ts={fmtTimestamp(seg.start)}>
                <span className="dot" style={{ background: SPEAKER_COLORS[idx % SPEAKER_COLORS.length] }} />
                {labels[seg.speaker] || seg.speaker}
              </div>
              {segEdit?.i === i ? (
                <textarea
                  className="seg-edit" autoFocus rows={2} value={segEdit.draft}
                  onChange={e => setSegEdit({ i, draft: e.target.value })}
                  onKeyDown={async e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      if (segEdit.draft.trim() && segEdit.draft !== seg.text) {
                        await onEditSegment?.(i, segEdit.draft.trim());
                      }
                      setSegEdit(null);
                    } else if (e.key === 'Escape') {
                      setSegEdit(null);
                    }
                  }}
                  onBlur={() => setSegEdit(null)}
                />
              ) : (
                <p>
                  {highlight(seg.text, findQ.trim())}
                  {onEditSegment && (
                    <button className="icon-btn seg-edit-btn" aria-label={`Edit line ${i + 1}`}
                            title="Edit line" onClick={() => setSegEdit({ i, draft: seg.text })}>
                      <Icon name="pencil" size={12} />
                    </button>
                  )}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
