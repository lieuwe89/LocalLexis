import { useState } from 'react';
import { api } from '../api/client';
import type { AskResult, JobRecord } from '../api/types';
import { useTranscripts } from '../stores/transcripts';
import { usePendingFind } from '../stores/pendingFind';
import type { Route } from '../types/route';

interface Props {
  setRoute: (r: Route) => void;
  setTid: (id: string) => void;
  pollMs?: number;
}

function fmtTs(secs: number) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function AskPanel({ setRoute, setTid, pollMs = 1500 }: Props) {
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const load = useTranscripts(s => s.load);

  const ask = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const { job_id } = await api<{ job_id: string }>('/library/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      });
      for (;;) {
        const rec = await api<JobRecord>(`/jobs/${job_id}`);
        setStage(rec.stage ?? null);
        if (rec.status === 'complete') { setResult((rec.result as AskResult) ?? null); break; }
        if (rec.status === 'failed') { setError(rec.error ?? 'ask failed'); break; }
        await new Promise(r => setTimeout(r, pollMs));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false); setStage(null);
    }
  };

  return (
    <div className="ask-panel">
      <div className="ask-input">
        <input
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') void ask(); }}
          placeholder="Ask your library — e.g. “what did we agree about the deadline?”"
        />
        <button onClick={() => void ask()} disabled={busy || !question.trim()}>
          {busy ? 'Asking…' : 'Ask'}
        </button>
      </div>
      {busy && (
        <div className="ask-progress" role="status">
          <span className="ask-spinner" aria-hidden="true" />
          {stage === 'retrieve' ? 'Searching your library…'
            : stage === 'ask' || stage === 'ask@hub' ? 'Writing answer…'
            : 'Working…'}
        </div>
      )}
      {error && <div className="ask-error">{error}</div>}
      {result && (
        <div className="ask-result">
          <p className="ask-answer">{result.answer}</p>
          <div className="ask-sources">
            {result.sources.map((s, i) => (
              <button
                key={i}
                className="lib-hit"
                aria-label={`Jump to source at segment ${s.segment_index}`}
                onClick={async () => {
                  // Empty query → transcript view falls back to a plain
                  // segment scroll (same pattern as semantic library hits).
                  usePendingFind.getState().set({
                    tid: s.transcript_id,
                    query: '',
                    fuzzy: false,
                    segmentIndex: s.segment_index,
                  });
                  try { await load(s.transcript_id); setTid(s.transcript_id); setRoute('complete'); } catch {}
                }}
              >
                {/* [n] matches the excerpt numbering the LLM cites — same
                    array order as build_ask_messages (one chunks list feeds
                    both the prompt and this sources list). */}
                [{i + 1}]{s.start != null ? ` ${fmtTs(s.start)}` : ''}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
