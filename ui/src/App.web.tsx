import { useState, useEffect } from 'react';
import './styles/global.css';
import { Window } from './chrome/Window';
import { LibraryScreen } from './screens/LibraryScreen';
import { CompleteScreen } from './screens/CompleteScreen';
import { WebSettingsScreen } from './screens/web/WebSettingsScreen';
import { LoginScreen } from './screens/web/LoginScreen';
import { getToken } from './lib/webAuth';
import { resetSidecarInfo, setUnauthorizedHandler } from './api/client';
import { useLibrary } from './stores/library';
import { useTranscripts } from './stores/transcripts';
import type { Route } from './types/route';

// The web (hub) shell only ever routes between these three screens — a
// narrower surface than the native app's full Route union, which also
// covers idle/progress/record/watch (capture flows the browser build never
// mounts). We keep `Route` as the shared type rather than declaring a new
// one so LibraryScreen's `setRoute: (r: Route) => void` and CompleteScreen's
// props line up without casts.
type WebRoute = Extract<Route, 'library' | 'complete' | 'settings'>;

export default function App() {
  const [authed, setAuthed] = useState<boolean>(() => getToken() !== null);
  const [route, setRoute] = useState<WebRoute>('library');
  const [tid, setTid] = useState<string | null>(null);
  const refreshLibrary = useLibrary(s => s.refresh);
  const removeTranscript = useLibrary(s => s.remove);
  const currentDoc = useTranscripts(s => (tid ? s.byId[tid] : undefined));
  const relabel = useTranscripts(s => s.relabel);
  const renameTranscript = useTranscripts(s => s.rename);
  const editSegment = useTranscripts(s => s.editSegment);

  // A rejected admin token (e.g. the hub rotated LOCALLEXIS_API_TOKEN or
  // restarted) makes every api() call 401. Clear the stored token and drop
  // back to the login screen rather than stranding the user on an empty UI.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      resetSidecarInfo();
      setAuthed(false);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  if (!authed) {
    return (
      <LoginScreen
        onAuthed={() => {
          setAuthed(true);
          refreshLibrary().catch(() => {});
        }}
      />
    );
  }

  return (
    <Window screenLabel={route}>
      <nav className="web-sidebar">
        <button aria-current={route === 'library'} onClick={() => setRoute('library')}>Library</button>
        <button aria-current={route === 'settings'} onClick={() => setRoute('settings')}>Settings</button>
      </nav>
      <div className="main">
        {/* .main-body owns the scroll (overflow: auto). The native App.tsx
            wraps its screens the same way; without it, content taller than the
            fixed-height window chrome is clipped with no way to scroll. */}
        <div className="main-body">
          {route === 'library' && (
            <LibraryScreen
              setRoute={(r) => setRoute(r as WebRoute)}
              setTid={setTid}
            />
          )}
          {route === 'complete' && currentDoc && tid && (
            <CompleteScreen
              key={tid}
              doc={currentDoc}
              txtPath={currentDoc.paths?.txt}
              jsonPath={currentDoc.paths?.json}
              tid={tid}
              onRelabel={async (m) => { await relabel(tid, m); }}
              onRename={async (t) => { await renameTranscript(tid, t); }}
              onDelete={async () => { await removeTranscript(tid); setRoute('library'); }}
              onEditSegment={async (i, t) => { await editSegment(tid, i, t); }}
            />
          )}
          {route === 'settings' && <WebSettingsScreen />}
        </div>
      </div>
    </Window>
  );
}
