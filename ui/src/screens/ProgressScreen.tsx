import { useEffect } from 'react';
import { useJobs } from '../stores/jobs';

const STAGES = ['ingest', 'asr', 'diarize', 'merge', 'write'] as const;

function fmtTimestamp(secs: number) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

interface Props {
  jobId: string;
  audioPath: string;
  onComplete: (transcriptId: string) => void;
}

export function ProgressScreen({ jobId, audioPath, onComplete }: Props) {
  const job = useJobs(s => s.byId[jobId]);

  useEffect(() => {
    if (job?.status === 'complete') {
      const transcriptId = job.transcriptId ?? jobId;
      onComplete(transcriptId);
    }
  }, [job?.status, job?.transcriptId, jobId, onComplete]);

  if (!job) return null;

  const currentIdx = STAGES.indexOf(job.stage as typeof STAGES[number]);
  const overallPercent = currentIdx < 0
    ? 0
    : ((currentIdx + job.percent) / STAGES.length) * 100;

  return (
    <div className="progress">
      <div className="doc-head">
        <div className="file-meta">{audioPath}</div>
        <h1>Transcribing…</h1>
      </div>
      <div className="bar"><div style={{ width: `${overallPercent}%` }} /></div>
      <div className="stages">
        {STAGES.map((s, i) => {
          const cls = i < currentIdx ? 'done' : i === currentIdx ? 'active' : '';
          return (
            <span key={s} className={'stage-chip ' + cls}>
              {s}{i === currentIdx ? ` ${Math.round(job.percent * 100)}%` : ''}
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
      {job.status === 'failed' && job.error && <div className="err">{job.error}</div>}
    </div>
  );
}
