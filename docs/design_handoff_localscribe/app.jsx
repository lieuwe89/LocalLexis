// app.jsx — mount + window chrome + router + tweaks

function App() {
  const [t, setTweak] = useTweaks(window.__TWEAK_DEFAULTS);
  const [route, setRoute] = React.useState('idle');
  const [recording, setRecording] = React.useState(false);

  // header title per route
  const HEADER = {
    idle:     { crumb: 'New transcription', title: 'Transcribe' },
    record:   { crumb: 'Recording',         title: 'Record' },
    watch:    { crumb: 'Watch folder',      title: 'Watch folder' },
    library:  { crumb: 'Library',           title: 'All transcripts' },
    settings: { crumb: 'Settings',          title: 'Settings' },
    complete: { crumb: 'Transcript',        title: 'Meeting · privacy & the scribe metaphor' },
  };
  const h = HEADER[route] || HEADER.idle;

  return (
    <div className="stage">
      <div className={'window chrome-' + t.chrome} data-screen-label={route}>
        {t.chrome === 'macos' && (
          <div className="titlebar">
            <div className="tl">
              <span className="dot r" /><span className="dot y" /><span className="dot g" />
            </div>
            <div className="titlebar-title">LocalScribe</div>
          </div>
        )}
        <div className="app">
          <Sidebar route={route} setRoute={setRoute} isRecording={route === 'record'} />

          <div className="main">
            <div className="main-header">
              <span className="crumb">{h.crumb}</span>
              <span className="title">{h.title}</span>
              <span className="spacer" />
              {route === 'complete' && (
                <span className="chip">
                  <Icon name="check" size={11} stroke={2} /> Done in 4:12
                </span>
              )}
              {route === 'record' && (
                <span className="chip accent">
                  <span className="dot" /> Live
                </span>
              )}
              <span className="chip" title="No network calls. Models, audio, transcripts all stay on this machine.">
                <Icon name="lock" size={11} stroke={1.5} /> On-device
              </span>
            </div>

            <div className="main-body">
              {route === 'idle'     && <IdleScreen setRoute={setRoute} />}
              {route === 'record'   && <RecordScreen />}
              {route === 'complete' && <CompleteScreen tweaks={t} />}
              {route === 'library'  && <LibraryScreen setRoute={setRoute} />}
              {route === 'watch'    && <WatchScreen />}
              {route === 'settings' && <SettingsScreen />}
            </div>
          </div>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Window" />
        <TweakRadio
          label="Chrome"
          value={t.chrome}
          options={[{ value: 'macos', label: 'macOS' }, { value: 'plain', label: 'Plain' }]}
          onChange={(v) => setTweak('chrome', v)}
        />
        <TweakSection label="Transcript view" />
        <TweakRadio
          label="Layout"
          value={t.transcriptView}
          options={[{ value: 'margin', label: 'Margin ts' }, { value: 'inline', label: 'Inline ts' }]}
          onChange={(v) => setTweak('transcriptView', v)}
        />
        <TweakRadio
          label="Density"
          value={t.density}
          options={[{ value: 'compact', label: 'Compact' }, { value: 'comfy', label: 'Comfy' }]}
          onChange={(v) => setTweak('density', v)}
        />
        <TweakToggle
          label="Speaker colors"
          value={t.showSpeakerColors !== false}
          onChange={(v) => setTweak('showSpeakerColors', v)}
        />
        <TweakSection label="Jump to screen" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          {['idle','record','complete','library','watch','settings'].map(r => (
            <button key={r}
              onClick={() => setRoute(r)}
              style={{
                padding: '6px 8px',
                border: '0.5px solid rgba(0,0,0,0.12)',
                background: route === r ? '#29261b' : 'rgba(0,0,0,0.03)',
                color: route === r ? '#fff' : '#29261b',
                borderRadius: 6,
                fontSize: 11,
                cursor: 'default',
                textTransform: 'capitalize',
              }}
            >{r}</button>
          ))}
        </div>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
