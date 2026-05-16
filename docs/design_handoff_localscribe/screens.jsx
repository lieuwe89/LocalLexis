// screens.jsx — Idle, Record, Complete + stubs

// ─────────────────────────────────────────────────────────────
// IDLE — drop zone + options + recent
// ─────────────────────────────────────────────────────────────
function IdleScreen({ setRoute }) {
  const [drag, setDrag] = React.useState(false);
  const recent = [
    { name: 'meeting-2026-05-14.m4a', dur: '38:21', spk: '3 speakers', when: 'yesterday' },
    { name: 'voice-memo-019.wav',     dur: '04:48', spk: '1 speaker',  when: 'Mon' },
    { name: 'interview-vh-25.mp3',    dur: '1:04:31', spk: '2 speakers', when: 'Apr 28' },
  ];

  return (
    <div className="idle">
      <div className="hero">
        <h1>What did you <em>say</em>?</h1>
        <p>
          Drop an audio file to transcribe it on this machine. Nothing
          leaves your device — models, audio and transcripts all live in
          your filesystem.
        </p>
      </div>

      <div
        className={'drop' + (drag ? ' active' : '')}
        onDragEnter={(e) => { e.preventDefault(); setDrag(true); }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); setRoute('complete'); }}
      >
        <div className="glyph">
          <Icon name="upload" size={40} />
        </div>
        <h2>Drag an audio file here</h2>
        <div className="sub">.mp3 · .m4a · .wav · .ogg · .flac · .webm</div>
        <div className="or">or</div>
        <button className="btn-ghost" onClick={() => setRoute('complete')}>Browse files…</button>
      </div>

      <div className="options-row">
        <div className="option">
          <div className="opt-label">Language</div>
          <div className="opt-value">Auto-detect <span className="chev"><Icon name="chev" size={12} /></span></div>
        </div>
        <div className="option">
          <div className="opt-label">Speakers</div>
          <div className="opt-value">Auto <span className="chev"><Icon name="chev" size={12} /></span></div>
        </div>
        <div className="option">
          <div className="opt-label">Backend</div>
          <div className="opt-value">faster-whisper <span className="chev"><Icon name="chev" size={12} /></span></div>
        </div>
      </div>

      <div className="recent-files">
        <h3>Recent files</h3>
        {recent.map((r, i) => (
          <div key={i} className="rfile" onClick={() => setRoute('complete')}>
            <span className="ico"><Icon name="doc" size={14} /></span>
            <span className="name">{r.name}</span>
            <span className="dur">{r.dur}</span>
            <span className="spk">{r.spk}</span>
            <span className="when">{r.when}</span>
          </div>
        ))}
      </div>

      <div className="etymology" style={{ marginTop: 8 }}>
        <div className="head"><b>scribe</b><span>/skraɪb/ &nbsp;·&nbsp; <em>noun</em></span></div>
        <div className="body">
          a person who copies out documents. <em>From Latin</em> <b style={{fontWeight:500}}>scrībere</b>, <em>to write</em>. Privately, by hand, on your own page.
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// RECORD — device, animated waveform, big timer, controls
// ─────────────────────────────────────────────────────────────
function Waveform({ recording }) {
  // SVG seismograph-style ink trace
  const svgRef = React.useRef(null);
  const [phase, setPhase] = React.useState(0);

  React.useEffect(() => {
    if (!recording) return;
    let raf;
    const tick = () => {
      setPhase(p => (p + 0.05) % 1000);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [recording]);

  // generate baseline ink trace
  const W = 1000;
  const H = 220;
  const bars = 140;
  // deterministic noise based on index + phase
  const rand = (i) => {
    const x = Math.sin(i * 12.9898 + phase * 0.7) * 43758.5453;
    return x - Math.floor(x);
  };

  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
         style={{ width: '100%', height: '100%', display: 'block', color: 'var(--accent)' }}>
      <defs>
        <linearGradient id="ink-fade" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%"  stopColor="currentColor" stopOpacity="0.0"/>
          <stop offset="15%" stopColor="currentColor" stopOpacity="0.4"/>
          <stop offset="85%" stopColor="currentColor" stopOpacity="0.9"/>
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.0"/>
        </linearGradient>
      </defs>

      {/* baseline */}
      <line x1="32" y1={H/2} x2={W-32} y2={H/2} stroke="var(--line-strong)" strokeWidth="0.5"/>

      {/* bars — left half historical (low), right half live (taller, ~currentMoment) */}
      {Array.from({ length: bars }).map((_, i) => {
        const x = 32 + (i / (bars - 1)) * (W - 64);
        const live = recording ? 1 : 0;
        // amplitude profile: louder near current playhead, decays into the past
        const distFromHead = (bars - 1 - i) / (bars - 1);
        const envelope = 0.25 + 0.75 * Math.pow(1 - distFromHead, 1.6);
        const noise = rand(i) * 0.7 + 0.3;
        const wob = recording ? (0.7 + 0.3 * Math.sin((phase * 8) + i * 0.4)) : 0.55;
        const h = (12 + noise * envelope * wob * 80 * (0.4 + live * 0.6));
        const op = 0.25 + envelope * 0.7;
        const isHead = i >= bars - 3;
        return (
          <line key={i} x1={x} y1={H/2 - h/2} x2={x} y2={H/2 + h/2}
                stroke="currentColor"
                strokeOpacity={op * (isHead && recording ? 1.15 : 1)}
                strokeWidth={isHead && recording ? 2 : 1.2}
                strokeLinecap="round" />
        );
      })}

      {/* playhead line */}
      <line x1={W-34} y1="20" x2={W-34} y2={H-20} stroke="currentColor" strokeOpacity={recording ? 0.5 : 0.15} strokeWidth="0.5" strokeDasharray="2 3"/>
    </svg>
  );
}

function RecordScreen() {
  const [recording, setRecording] = React.useState(true);
  const [paused, setPaused] = React.useState(false);
  const [elapsed, setElapsed] = React.useState(73.4); // seconds

  React.useEffect(() => {
    if (!recording || paused) return;
    const t = setInterval(() => setElapsed(e => e + 0.1), 100);
    return () => clearInterval(t);
  }, [recording, paused]);

  const mm = Math.floor(elapsed / 60).toString().padStart(2, '0');
  const ss = Math.floor(elapsed % 60).toString().padStart(2, '0');
  const ms = Math.floor((elapsed % 1) * 10);

  const statusClass = !recording ? 'idle' : paused ? 'paused' : '';
  const statusLabel = !recording ? 'Ready' : paused ? 'Paused' : 'Recording';

  return (
    <div className="record">
      <div className="device-bar">
        <span className="lbl">Input</span>
        <select defaultValue="macbook">
          <option value="macbook">MacBook Pro Microphone</option>
          <option value="airpods">AirPods Pro</option>
          <option value="usb">Shure SM7B (USB)</option>
        </select>
        <span style={{ color: 'var(--ink-faint)' }}>·</span>
        <span style={{ color: 'var(--ink-dim)' }}>48 kHz · mono</span>
      </div>

      <div className="scribe-canvas">
        <Waveform recording={recording && !paused} />
        <div className="time-marks">
          <span>−60s</span><span>−45s</span><span>−30s</span><span>−15s</span><span>now</span>
        </div>
      </div>

      <div className="timer">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
          <div className={'label ' + statusClass}>{statusLabel}</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="big">{mm}:{ss}</span>
            <span className="ms">.{ms}</span>
          </div>
        </div>
      </div>

      <div className="record-controls">
        <button className="btn-secondary" onClick={() => setPaused(p => !p)} disabled={!recording}>
          <Icon name="pause" size={13} /> {paused ? 'Resume' : 'Pause'}
        </button>
        <button
          className={'btn-record' + (recording ? ' is-recording' : '')}
          onClick={() => { setRecording(r => !r); setPaused(false); if (!recording) setElapsed(0); }}
          title={recording ? 'Stop' : 'Start recording'}
        >
          <span className="inner" />
        </button>
        <button className="btn-secondary danger" onClick={() => { setRecording(false); setElapsed(0); }}>
          Discard
        </button>
      </div>

      <div className="privacy-note">
        <Icon name="lock" size={11} stroke={1.4} />
        Audio is captured to disk · <code style={{ fontFamily: 'var(--mono)', color: 'var(--ink-muted)' }}>~/Recordings/voice-memo-020.wav</code> · never sent over the network.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// COMPLETE — relabel + manuscript-style transcript
// ─────────────────────────────────────────────────────────────
const SAMPLE_TURNS = [
  { spk: 0, ts: '00:00:04', text: 'Okay, so we\'re recording. The whole point of this thing is that nothing leaves your machine — no API calls, no telemetry, no model weights talking home. It just runs.' },
  { spk: 1, ts: '00:00:18', text: 'Right. And the bar is that it should feel like a real native app, not a wrapper around a CLI. A first-class library, drag-and-drop, the speaker relabel thing inline.' },
  { spk: 0, ts: '00:00:32', text: 'The sidecar JSON is still the source of truth though. We don\'t want a separate index, no SQLite. If you delete the file from disk, it\'s gone — that\'s the contract.' },
  { spk: 1, ts: '00:00:47', text: 'Agreed. The UI is a view over the filesystem. That keeps the whole privacy story coherent: there is no second copy, no cloud cache, no secret database somewhere in Application Support.' },
  { spk: 2, ts: '00:01:05', text: 'Do we want to surface the model that ran? Like, a little chip saying "whisper-large-v3, faster-whisper backend, ran for 4 minutes." For trust.' },
  { spk: 0, ts: '00:01:17', text: 'Yeah, in the file meta. Subtle. Not a hero element, more of a footnote — but legible.' },
  { spk: 1, ts: '00:01:29', text: 'And the recording UI. I keep wanting it to look like a wax cylinder or a seismograph, not like Voice Memos. Something that says: this is being inscribed, not streamed.' },
];

function CompleteScreen({ tweaks }) {
  const [labels, setLabels] = React.useState({ 0: 'Alice', 1: 'Bob', 2: 'Carol' });
  const [applied, setApplied] = React.useState(true);

  return (
    <div className="complete">
      <div className="doc-head">
        <div className="title-stack">
          <div className="file-meta">
            <span>~/Audio/meeting-2026-05-14.m4a</span>
            <span style={{ color: 'var(--ink-faint)' }}>·</span>
            <span>local</span>
          </div>
          <h1>Meeting · privacy &amp; the scribe metaphor</h1>
          <div className="subline">
            <span>38:21</span><span className="sep">·</span>
            <span>3 speakers</span><span className="sep">·</span>
            <span>en</span><span className="sep">·</span>
            <span>whisper-large-v3</span><span className="sep">·</span>
            <span>14 May 2026</span>
          </div>
        </div>
        <div className="actions">
          <button className="icon-btn" title="Copy transcript"><Icon name="copy" size={15} /></button>
          <button className="icon-btn" title="Open .txt"><Icon name="doc" size={15} /></button>
          <button className="icon-btn" title="Open .json"><Icon name="braces" size={15} /></button>
        </div>
      </div>

      <div className="relabel">
        <div className="relabel-head">
          <span className="lbl">Speakers · 3 detected</span>
          <button className="btn-apply" disabled={applied} onClick={() => setApplied(true)}>
            {applied ? <span style={{ display:'inline-flex', alignItems:'center', gap:6 }}><Icon name="check" size={11} stroke={2}/> Applied</span> : 'Apply'}
          </button>
        </div>
        <div className="relabel-grid">
          {[0, 1, 2].map(i => (
            <div key={i} className="relabel-row">
              <span className="swatch" style={{ background: SPEAKER_COLORS[i] }} />
              <span className="src">SPEAKER_0{i}</span>
              <span className="arrow">→</span>
              <input
                value={labels[i]}
                placeholder="Name…"
                onChange={(e) => { setLabels(l => ({ ...l, [i]: e.target.value })); setApplied(false); }}
              />
            </div>
          ))}
        </div>
      </div>

      <div className={'transcript view-' + tweaks.transcriptView + ' density-' + tweaks.density}>
        {SAMPLE_TURNS.map((t, i) => (
          <div key={i} className="turn">
            <div className="ts">{t.ts}</div>
            <div className="spk" data-ts={t.ts}>
              {tweaks.showSpeakerColors !== false && <span className="dot" style={{ background: SPEAKER_COLORS[t.spk] }} />}
              {labels[t.spk] || `Speaker ${t.spk}`}
            </div>
            <p>{t.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// STUBS — Library / Watch / Settings
// ─────────────────────────────────────────────────────────────
function StubScreen({ title, body, iconName }) {
  return (
    <div className="stub">
      <div className="glyph"><Icon name={iconName} size={36} stroke={1.2} /></div>
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

function LibraryScreen({ setRoute }) {
  return (
    <StubScreen title="Library" iconName="book"
      body="Every .json sidecar this app has seen, indexed in memory. Search, filter by speaker, jump back into any transcript. Stub for this prototype — open a recent transcript from the sidebar." />
  );
}

function WatchScreen() {
  return (
    <StubScreen title="Watch folder" iconName="folder"
      body="Point this at a folder and any new audio that lands in it gets transcribed automatically. Recent events stream into a log. Stub for now." />
  );
}

function SettingsScreen() {
  return (
    <StubScreen title="Settings" iconName="gear"
      body="config.toml as a form: backend, ASR model, model cache directory, watch debounce, Hugging Face token. Stub for now." />
  );
}

Object.assign(window, { IdleScreen, RecordScreen, CompleteScreen, LibraryScreen, WatchScreen, SettingsScreen });
