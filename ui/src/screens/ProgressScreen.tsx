import { useEffect, useRef, useState } from 'react';
import { useJobs, cancelTranscribe } from '../stores/jobs';

const STAGES = ['load', 'ingest', 'asr', 'diarize', 'merge', 'write'] as const;

const STAGE_LABELS: Record<typeof STAGES[number], string> = {
  load:    'load models',
  ingest:  'ingest',
  asr:     'transcribe',
  diarize: 'diarize',
  merge:   'merge',
  write:   'write',
};

function fmtTimestamp(secs: number) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function fmtElapsed(secs: number) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

interface Props {
  jobId: string;
  audioPath: string;
  onComplete: (transcriptId: string) => void;
  onCancelled: () => void;
}

export function ProgressScreen({ jobId, audioPath, onComplete, onCancelled }: Props) {
  const job = useJobs(s => s.byId[jobId]);
  const startedAt = job?.startedAt ?? Date.now();
  const [elapsed, setElapsed] = useState(() => (Date.now() - startedAt) / 1000);
  const [cancelling, setCancelling] = useState(false);
  const lastPctRef = useRef<number>(0);
  const lastChangeRef = useRef<number>(Date.now());

  useEffect(() => {
    setElapsed((Date.now() - startedAt) / 1000);
    const id = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 250);
    return () => clearInterval(id);
  }, [startedAt]);

  useEffect(() => {
    if (job?.status === 'complete') {
      const transcriptId = job.transcriptId ?? jobId;
      onComplete(transcriptId);
    } else if (job?.status === 'failed' && job.error === 'cancelled') {
      onCancelled();
    }
  }, [job?.status, job?.transcriptId, job?.error, jobId, onComplete, onCancelled]);

  if (!job) return null;

  const currentIdx = STAGES.indexOf(job.stage as typeof STAGES[number]);
  const overallPercent = currentIdx < 0
    ? 0
    : ((currentIdx + job.percent) / STAGES.length) * 100;

  if (overallPercent !== lastPctRef.current) {
    lastPctRef.current = overallPercent;
    lastChangeRef.current = Date.now();
  }
  const stalled = Date.now() - lastChangeRef.current > 3000;

  const handleCancel = async () => {
    if (cancelling) return;
    setCancelling(true);
    try { await cancelTranscribe(jobId); } catch { setCancelling(false); }
  };

  return (
    <div className="progress">
      <div className="doc-head">
        <div className="file-meta">{audioPath}</div>
        <div className="progress-title-row">
          <h1>Transcribing…</h1>
          <button
            className="btn-ghost danger"
            onClick={handleCancel}
            disabled={cancelling || job.status === 'complete' || job.status === 'failed'}
          >
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        </div>
        <div className="progress-meta">
          <span>Elapsed {fmtElapsed(elapsed)}</span>
          <span className="sep">·</span>
          <span>{Math.round(overallPercent)}%</span>
        </div>
      </div>
      <div className={'bar' + (stalled ? ' indeterminate' : '')}>
        <div style={{ width: `${overallPercent}%` }} />
      </div>
      <div className="stages">
        {STAGES.map((s, i) => {
          const cls = i < currentIdx ? 'done' : i === currentIdx ? 'active' : '';
          return (
            <span key={s} className={'stage-chip ' + cls}>
              {STAGE_LABELS[s]}
            </span>
          );
        })}
      </div>
      <div className="live-transcript">
        {job.lines.map((l, i) => (
          <div key={i} className="turn">
            <div className="ts">{fmtTimestamp(l.ts)}</div>
            <div className="spk">{l.speaker}</div>
            <p>{l.text}</p>
          </div>
        ))}
      </div>
      {job.status === 'failed' && job.error && job.error !== 'cancelled' && <div className="err">{job.error}</div>}
    </div>
  );
}
