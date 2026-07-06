import { useState } from 'react';
import './styles/global.css';
import { Window } from './chrome/Window';
import { LibraryScreen } from './screens/LibraryScreen';
import { CompleteScreen } from './screens/CompleteScreen';
import { WebSettingsScreen } from './screens/web/WebSettingsScreen';
import { LoginScreen } from './screens/web/LoginScreen';
import { getToken } from './lib/webAuth';
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
  const currentDoc = useTranscripts(s => (tid ? s.byId[tid] : undefined));
  const relabel = useTranscripts(s => s.relabel);

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
            onRelabel={async (m) => { await relabel(tid, m); }}
          />
        )}
        {route === 'settings' && <WebSettingsScreen />}
      </div>
    </Window>
  );
}
