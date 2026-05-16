import { Icon, type IconName } from '../primitives/Icon';
import { useLibrary } from '../stores/library';
import { useRecording } from '../stores/recording';
import { useTranscripts } from '../stores/transcripts';
import type { Route } from '../types/route';

const NAV: { id: Route; label: string; icon: IconName }[] = [
  { id: 'idle',     label: 'Transcribe',   icon: 'transcribe' },
  { id: 'record',   label: 'Record',       icon: 'mic' },
  { id: 'watch',    label: 'Watch folder', icon: 'eye' },
  { id: 'library',  label: 'Library',      icon: 'book' },
  { id: 'settings', label: 'Settings',     icon: 'gear' },
];

export function Sidebar({ route, setRoute, setCurrentTranscriptId }: {
  route: Route;
  setRoute: (r: Route) => void;
  currentTranscriptId: string | null;
  setCurrentTranscriptId: (id: string | null) => void;
}) {
  const recent = useLibrary(s => s.items.slice(0, 5));
  const recording = useRecording(s => s.active);
  const loadTranscript = useTranscripts(s => s.load);

  return (
    <div className="sidebar">
      <div className="brand">
        <div className="wordmark">LocalScribe</div>
        <div className="pron">/ˈloʊkəlˌskraɪb/ &nbsp;·&nbsp; v1.0</div>
      </div>
      <button className="new-btn" onClick={() => setRoute('idle')}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <Icon name="plus" size={13} stroke={1.8} /> New transcription
        </span>
        <span className="kbd">⌘N</span>
      </button>
      <div className="nav">
        {NAV.map(n => {
          const active = route === n.id || (n.id === 'idle' && (route === 'complete' || route === 'progress'));
          return (
            <div key={n.id} className={'nav-item' + (active ? ' active' : '')} onClick={() => setRoute(n.id)}>
              <span className="icon"><Icon name={n.icon} size={15} /></span>
              <span>{n.label}</span>
              {n.id === 'record' && recording ? <span className="live-dot" /> : null}
            </div>
          );
        })}
      </div>
      <div className="section-label">Recent</div>
      <div className="recent-list">
        {recent.map(r => (
          <div key={r.id} className="recent-item"
               onClick={async () => { await loadTranscript(r.id); setCurrentTranscriptId(r.id); setRoute('complete'); }}>
            <span>{r.audio_path?.split('/').pop() || r.id}</span>
            <span className="meta">
              <span>{r.duration_seconds ? fmt(r.duration_seconds) : '—'}</span>
            </span>
          </div>
        ))}
      </div>
      <div className="sidebar-footer">
        <span className="on-device">All processing on-device</span>
      </div>
    </div>
  );
}

function fmt(secs: number) {
  const m = Math.floor(secs / 60); const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}
