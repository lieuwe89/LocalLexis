import { Icon } from '../primitives/Icon';
import { useTheme } from '../stores/theme';
import type { Route } from '../types/route';
import { BackendStatus } from './BackendStatus';

const HEADERS: Record<Route, { crumb: string; title: string }> = {
  idle:     { crumb: 'New transcription', title: 'Transcribe' },
  progress: { crumb: 'Transcribing',      title: 'Transcribe' },
  complete: { crumb: 'Transcript',        title: 'Transcript' },
  record:   { crumb: 'Recording',         title: 'Record' },
  library:  { crumb: 'Library',           title: 'All transcripts' },
  watch:    { crumb: 'Watch folder',      title: 'Watch folder' },
  settings: { crumb: 'Settings',          title: 'Settings' },
};

export function MainHeader({ route, doneLabel, isLive }: { route: Route; doneLabel?: string; isLive?: boolean }) {
  const h = HEADERS[route];
  const theme = useTheme(s => s.theme);
  const toggleTheme = useTheme(s => s.toggle);
  return (
    <div className="main-header">
      <span className="crumb">{h.crumb}</span>
      <span className="title">{h.title}</span>
      <span className="spacer" />
      {route === 'complete' && doneLabel && (
        <span className="chip"><Icon name="check" size={11} stroke={2} /> {doneLabel}</span>
      )}
      {route === 'record' && isLive && (
        <span className="chip accent"><span className="dot" /> Live</span>
      )}
      <button
        className="theme-toggle"
        onClick={toggleTheme}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        aria-label="Toggle theme"
      >
        <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={13} stroke={1.6} />
      </button>
      <BackendStatus />
      <span className="chip"><Icon name="lock" size={11} stroke={1.5} /> On-device</span>
    </div>
  );
}
