// sidebar.jsx — nav, recent, on-device footer

function Sidebar({ route, setRoute, isRecording, recordElapsed }) {
  const nav = [
    { id: 'idle',     label: 'Transcribe',  icon: 'transcribe' },
    { id: 'record',   label: 'Record',      icon: 'mic' },
    { id: 'watch',    label: 'Watch folder',icon: 'eye' },
    { id: 'library',  label: 'Library',     icon: 'book',  badge: '47' },
    { id: 'settings', label: 'Settings',    icon: 'gear' },
  ];

  const recent = [
    { id: 'r1', name: 'Field notes — Groningen',   meta: '23:14 · today' },
    { id: 'r2', name: 'Standup 05-14',             meta: '12:02 · yesterday' },
    { id: 'r3', name: 'Interview · sandalmaking',  meta: '1:04:31 · Mon' },
    { id: 'r4', name: 'Voice memo 19',             meta: '4:48 · Mon' },
    { id: 'r5', name: 'Permaculture talk',         meta: '52:10 · Apr 28' },
  ];

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
        {nav.map(n => (
          <div
            key={n.id}
            className={'nav-item' + (route === n.id || (n.id === 'idle' && route === 'complete') ? ' active' : '')}
            onClick={() => setRoute(n.id)}
          >
            <span className="icon"><Icon name={n.icon} size={15} /></span>
            <span>{n.label}</span>
            {n.id === 'record' && isRecording ? (
              <span className="live-dot" title={'Recording · ' + recordElapsed} />
            ) : n.badge ? (
              <span className="badge">{n.badge}</span>
            ) : null}
          </div>
        ))}
      </div>

      <div className="section-label">Recent</div>
      <div className="recent-list">
        {recent.map(r => (
          <div
            key={r.id}
            className="recent-item"
            onClick={() => setRoute('complete')}
            title="Open transcript"
          >
            <span>{r.name}</span>
            <span className="meta"><span>{r.meta}</span></span>
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <span className="on-device">All processing on-device</span>
      </div>
    </div>
  );
}

Object.assign(window, { Sidebar });
