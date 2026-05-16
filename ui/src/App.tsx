import { useState, useEffect } from 'react';
import { audioDir, join } from '@tauri-apps/api/path';
import './styles/global.css';
import { Window } from './chrome/Window';
import { Sidebar } from './chrome/Sidebar';
import { MainHeader } from './chrome/MainHeader';
import { IdleScreen } from './screens/IdleScreen';
import { ProgressScreen } from './screens/ProgressScreen';
import { CompleteScreen } from './screens/CompleteScreen';
import { RecordScreen } from './screens/RecordScreen';
import { LibraryScreen } from './screens/LibraryScreen';
import { WatchScreen } from './screens/WatchScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { useLibrary } from './stores/library';
import { useTranscripts } from './stores/transcripts';
import { startTranscribe, startRecord, stopRecord } from './stores/jobs';
import { useRecording } from './stores/recording';
import { api } from './api/client';
import { checkForUpdates } from './updater';
import type { AudioDeviceDto } from './api/types';
import type { Route } from './types/route';

export default function App() {
  const [route, setRoute] = useState<Route>('idle');
  const [tid, setTid] = useState<string | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [currentAudioPath, setCurrentAudioPath] = useState<string>('');
  const [devices, setDevices] = useState<AudioDeviceDto[]>([]);
  const refreshLibrary = useLibrary(s => s.refresh);
  const loadTranscript = useTranscripts(s => s.load);
  const recentItems = useLibrary(s => s.items.slice(0, 3));
  const currentDoc = useTranscripts(s => (tid ? s.byId[tid] : undefined));
  const relabel = useTranscripts(s => s.relabel);
  const recording = useRecording();

  useEffect(() => { refreshLibrary().catch(() => {}); }, [refreshLibrary]);
  useEffect(() => { api<AudioDeviceDto[]>('/devices').then(setDevices).catch(() => {}); }, []);
  useEffect(() => { checkForUpdates(true).catch(() => {}); }, []);
  useEffect(() => {
    if (!recording.active || recording.paused) return;
    const id = setInterval(() => useRecording.getState().tick(0.1), 100);
    return () => clearInterval(id);
  }, [recording.active, recording.paused]);

  return (
    <Window screenLabel={route}>
      <Sidebar route={route} setRoute={setRoute} currentTranscriptId={tid} setCurrentTranscriptId={setTid} />
      <div className="main">
        <MainHeader route={route} isLive={route === 'record' && recording.active} />
        <div className="main-body">
          {route === 'idle' && (
            <IdleScreen
              recentFiles={recentItems}
              onTranscribe={async (path) => {
                const id = await startTranscribe(path);
                setCurrentJobId(id);
                setCurrentAudioPath(path);
                setRoute('progress');
              }}
            />
          )}
          {route === 'progress' && currentJobId && (
            <ProgressScreen
              jobId={currentJobId}
              audioPath={currentAudioPath}
              onComplete={async (transcriptId) => {
                await loadTranscript(transcriptId).catch(() => {});
                setTid(transcriptId);
                setRoute('complete');
                refreshLibrary().catch(() => {});
              }}
            />
          )}
          {route === 'complete' && tid && currentDoc && (
            <CompleteScreen
              doc={currentDoc}
              onRelabel={async (m) => { await relabel(tid, m); }}
            />
          )}
          {route === 'record' && (
            <RecordScreen
              devices={devices}
              active={recording.active}
              paused={recording.paused}
              elapsed={recording.elapsed}
              outputPath={currentAudioPath}
              selectedDevice={recording.deviceId}
              onSelectDevice={(id) => useRecording.getState().setDevice(id)}
              onStart={async () => {
                const dir = await audioDir();
                const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
                const filename = `recording-${ts}.wav`;
                const fullPath = await join(dir, filename);
                useRecording.getState().reset();
                const id = await startRecord(fullPath, recording.deviceId ?? undefined);
                useRecording.getState().setJob(id);
                useRecording.getState().setActive(true);
                setCurrentAudioPath(fullPath);
              }}
              onStop={async () => {
                const jobId = useRecording.getState().jobId;
                if (!jobId) return;
                await stopRecord(jobId);
                useRecording.getState().setActive(false);
                const transcribeJobId = await startTranscribe(currentAudioPath);
                setCurrentJobId(transcribeJobId);
                setRoute('progress');
              }}
              onPause={() => useRecording.getState().setPaused(!recording.paused)}
              onDiscard={() => { useRecording.getState().reset(); }}
            />
          )}
          {route === 'library' && (
            <LibraryScreen setRoute={setRoute} setTid={setTid} />
          )}
          {route === 'watch' && (
            <WatchScreen />
          )}
          {route === 'settings' && (
            <SettingsScreen />
          )}
          {route !== 'idle' && route !== 'progress' && route !== 'complete' && route !== 'record' && route !== 'library' && route !== 'watch' && route !== 'settings' && (
            <pre>{route} (placeholder)</pre>
          )}
        </div>
      </div>
    </Window>
  );
}
