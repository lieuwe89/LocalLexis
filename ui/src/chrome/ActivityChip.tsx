import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { JobRecord } from '../api/types';

const POLL_MS = 3000;

const KIND_LABEL: Record<string, string> = {
  transcribe: 'Transcribing',
  hub_upload: 'Transcribing',
  record: 'Recording',
  summarize: 'Summarizing',
};

function jobLabel(j: JobRecord): string {
  const verb = KIND_LABEL[j.kind] ?? 'Working';
  const name = j.audio_path?.split('/').pop()?.replace(/\.[^.]+$/, '');
  const pct = j.percent > 0 ? ` — ${Math.round(j.percent * 100)}%` : '';
  return name ? `${verb} ${name}${pct}` : `${verb}${pct}`;
}

export function ActivityChip() {
  const [jobs, setJobs] = useState<JobRecord[]>([]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      if (document.visibilityState !== 'hidden') {
        try {
          setJobs(await api<JobRecord[]>('/jobs?active=true'));
        } catch {
          /* transient failures keep last state; next tick retries */
        }
      }
      timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, []);

  if (jobs.length === 0) return null;
  const first = jobs[0];
  return (
    <div className="activity-chip" role="status">
      <span className="activity-spinner" aria-hidden="true" />
      <span>{jobLabel(first)}</span>
      {jobs.length > 1 && <span className="activity-more">+{jobs.length - 1}</span>}
    </div>
  );
}
