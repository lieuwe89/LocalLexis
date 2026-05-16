import { useState, useMemo } from 'react';
import { Icon } from '../primitives/Icon';
import { SPEAKER_COLORS } from '../primitives/colors';
import type { TranscriptDoc } from '../api/types';
import { open as shellOpen } from '@tauri-apps/plugin-shell';

interface Props {
  doc: TranscriptDoc;
  txtPath?: string;
  jsonPath?: string;
  onRelabel: (mapping: Record<string, string>) => Promise<void> | void;
}

function fmtTimestamp(secs: number) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export function CompleteScreen({ doc, txtPath, jsonPath, onRelabel }: Props) {
  const speakerIds = useMemo(() => Object.keys(doc.speakers), [doc.speakers]);
  const [labels, setLabels] = useState<Record<string, string>>(() => ({ ...doc.speakers }));
  const [applied, setApplied] = useState(true);

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

  const onCopy = () => navigator.clipboard.writeText(renderedText).catch(() => {});
  const onOpenTxt = () => txtPath && shellOpen(txtPath).catch(() => {});
  const onOpenJson = () => jsonPath && shellOpen(jsonPath).catch(() => {});

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

  const date = doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '—';
  const dur = doc.duration_seconds
    ? `${Math.floor(doc.duration_seconds / 60)}:${Math.floor(doc.duration_seconds % 60).toString().padStart(2, '0')}`
    : '—';
  const model = doc.models?.asr?.split(':')[1] || doc.models?.asr || '—';
  const title = doc.audio_path?.split('/').pop()?.replace(/\.[^.]+$/, '') || 'Transcript';

  return (
    <div className="complete">
      <div className="doc-head">
        <div className="title-stack">
          <div className="file-meta">
            <span>{doc.audio_path}</span>
            <span style={{ color: 'var(--ink-faint)' }}>·</span>
            <span>local</span>
          </div>
          <h1>{title}</h1>
          <div className="subline">
            <span>{dur}</span><span className="sep">·</span>
            <span>{speakerIds.length} speakers</span><span className="sep">·</span>
            <span>{doc.language || '—'}</span><span className="sep">·</span>
            <span>{model}</span><span className="sep">·</span>
            <span>{date}</span>
          </div>
        </div>
        <div className="actions">
          <button className="icon-btn" title="Copy transcript" onClick={onCopy}><Icon name="copy" size={15} /></button>
          <button className="icon-btn" title="Open .txt" onClick={onOpenTxt}><Icon name="doc" size={15} /></button>
          <button className="icon-btn" title="Open .json" onClick={onOpenJson}><Icon name="braces" size={15} /></button>
        </div>
      </div>

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

      <div className="transcript">
        {doc.segments.map((seg, i) => {
          const idx = speakerIndex[seg.speaker] ?? 0;
          return (
            <div key={i} className="turn">
              <div className="ts">{fmtTimestamp(seg.start)}</div>
              <div className="spk" data-ts={fmtTimestamp(seg.start)}>
                <span className="dot" style={{ background: SPEAKER_COLORS[idx % SPEAKER_COLORS.length] }} />
                {labels[seg.speaker] || seg.speaker}
              </div>
              <p>{seg.text}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
