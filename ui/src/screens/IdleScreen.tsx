import { useState } from 'react';
import { Icon } from '../primitives/Icon';
import { open } from '@tauri-apps/plugin-dialog';
import type { TranscriptListItem } from '../api/types';

interface Props {
  onTranscribe: (path: string) => void;
  recentFiles: TranscriptListItem[];
}

const ACCEPTED_EXTS = ['mp3', 'm4a', 'wav', 'ogg', 'flac', 'webm'];

export function IdleScreen({ onTranscribe, recentFiles }: Props) {
  const [drag, setDrag] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      const path = (file as any).path ?? file.name;
      onTranscribe(path);
    }
  };

  const handleBrowse = async () => {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [{ name: 'Audio', extensions: ACCEPTED_EXTS }],
    });
    if (typeof selected === 'string') {
      onTranscribe(selected);
    }
  };

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
        onDrop={handleDrop}
      >
        <div className="glyph">
          <Icon name="upload" size={40} />
        </div>
        <h2>Drag an audio file here</h2>
        <div className="sub">.mp3 · .m4a · .wav · .ogg · .flac · .webm</div>
        <div className="or">or</div>
        <button className="btn-ghost" onClick={handleBrowse}>Browse files…</button>
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

      {recentFiles.length > 0 && (
        <div className="recent-files">
          <h3>Recent files</h3>
          {recentFiles.map(r => {
            const name = (r.audio_path || r.id).split('/').pop() || r.id;
            const dur = r.duration_seconds
              ? `${Math.floor(r.duration_seconds / 60)}:${(Math.floor(r.duration_seconds % 60)).toString().padStart(2, '0')}`
              : '—';
            const spk = r.speakers ? `${r.speakers} speaker${r.speakers === 1 ? '' : 's'}` : '—';
            return (
              <div key={r.id} className="rfile">
                <span className="ico"><Icon name="doc" size={14} /></span>
                <span className="name">{name}</span>
                <span className="dur">{dur}</span>
                <span className="spk">{spk}</span>
                <span className="when">{r.created_at?.slice(0, 10) || '—'}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="etymology" style={{ marginTop: 8 }}>
        <div className="head"><b>scribe</b><span>/skraɪb/ &nbsp;·&nbsp; <em>noun</em></span></div>
        <div className="body">
          a person who copies out documents. <em>From Latin</em> <b style={{fontWeight:500}}>scrībere</b>, <em>to write</em>. Privately, by hand, on your own page.
        </div>
      </div>
    </div>
  );
}
