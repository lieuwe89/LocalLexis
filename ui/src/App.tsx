import { useState, useEffect } from 'react';
import './styles/global.css';
import { Window } from './chrome/Window';
import { Sidebar } from './chrome/Sidebar';
import { MainHeader } from './chrome/MainHeader';
import { IdleScreen } from './screens/IdleScreen';
import { useLibrary } from './stores/library';
import { startTranscribe } from './stores/jobs';
import type { Route } from './types/route';

export default function App() {
  const [route, setRoute] = useState<Route>('idle');
  const [tid, setTid] = useState<string | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const refreshLibrary = useLibrary(s => s.refresh);
  const recentItems = useLibrary(s => s.items.slice(0, 3));

  useEffect(() => { refreshLibrary().catch(() => {}); }, [refreshLibrary]);

  return (
    <Window screenLabel={route}>
      <Sidebar route={route} setRoute={setRoute} currentTranscriptId={tid} setCurrentTranscriptId={setTid} />
      <div className="main">
        <MainHeader route={route} />
        <div className="main-body">
          {route === 'idle' && (
            <IdleScreen
              recentFiles={recentItems}
              onTranscribe={async (path) => {
                const id = await startTranscribe(path);
                setCurrentJobId(id);
                setRoute('progress');
              }}
            />
          )}
          {route !== 'idle' && <pre>{route} (placeholder — current job: {currentJobId ?? 'none'})</pre>}
        </div>
      </div>
    </Window>
  );
}
