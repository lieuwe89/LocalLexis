import { useEffect, useRef, useState } from 'react';
import { Icon } from '../primitives/Icon';
import { open } from '@tauri-apps/plugin-dialog';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import type { TranscriptListItem } from '../api/types';

export interface TranscribeOpts {
  language?: string;
  num_speakers?: number;
  backend?: string;
}

interface Props {
  onTranscribe: (path: string, opts: TranscribeOpts) => void;
  recentFiles: TranscriptListItem[];
}

const ACCEPTED_EXTS = ['mp3', 'm4a', 'wav', 'ogg', 'flac', 'webm'];

const LANGUAGES: { code: string; label: string }[] = [
  { code: 'auto', label: 'Auto-detect' },
  { code: 'en',   label: 'English' },
  { code: 'nl',   label: 'Dutch' },
  { code: 'de',   label: 'German' },
  { code: 'fr',   label: 'French' },
  { code: 'es',   label: 'Spanish' },
  { code: 'it',   label: 'Italian' },
  { code: 'pt',   label: 'Portuguese' },
  { code: 'sv',   label: 'Swedish' },
  { code: 'no',   label: 'Norwegian' },
  { code: 'da',   label: 'Danish' },
  { code: 'fi',   label: 'Finnish' },
  { code: 'pl',   label: 'Polish' },
  { code: 'ru',   label: 'Russian' },
  { code: 'zh',   label: 'Chinese' },
  { code: 'ja',   label: 'Japanese' },
  { code: 'ko',   label: 'Korean' },
  { code: 'ar',   label: 'Arabic' },
];

const SPEAKERS: { value: number | undefined; label: string }[] = [
  { value: undefined, label: 'Auto' },
  { value: 1, label: '1' },
  { value: 2, label: '2' },
  { value: 3, label: '3' },
  { value: 4, label: '4' },
  { value: 5, label: '5' },
  { value: 6, label: '6' },
  { value: 8, label: '8' },
];

const BACKENDS: { value: string; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'cpu',  label: 'CPU' },
  { value: 'cuda', label: 'CUDA (NVIDIA)' },
  { value: 'mps',  label: 'MPS (Apple)' },
];

export function IdleScreen({ onTranscribe, recentFiles }: Props) {
  const [drag, setDrag] = useState(false);
  const [language, setLanguage] = useState<string>('auto');
  const [numSpeakers, setNumSpeakers] = useState<number | undefined>(undefined);
  const [backend, setBackend] = useState<string>('auto');

  const opts: TranscribeOpts = {
    language,
    num_speakers: numSpeakers,
    backend,
  };

  useEffect(() => {
    const unlistenPromise = getCurrentWebview().onDragDropEvent(event => {
      if (event.payload.type === 'over' || event.payload.type === 'enter') {
        setDrag(true);
      } else if (event.payload.type === 'leave') {
        setDrag(false);
      } else if (event.payload.type === 'drop') {
        setDrag(false);
        const path = event.payload.paths?.[0];
        if (path) onTranscribe(path, opts);
      }
    });
    return () => { unlistenPromise.then(fn => fn()).catch(() => {}); };
  }, [onTranscribe, language, numSpeakers, backend]);

  const handleBrowse = async () => {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [{ name: 'Audio', extensions: ACCEPTED_EXTS }],
    });
    if (typeof selected === 'string') {
      onTranscribe(selected, opts);
    }
  };

  const langLabel = LANGUAGES.find(l => l.code === language)?.label ?? 'Auto-detect';
  const spkLabel = SPEAKERS.find(s => s.value === numSpeakers)?.label ?? 'Auto';
  const backendLabel = BACKENDS.find(b => b.value === backend)?.label ?? 'Auto';

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

      <div className={'drop' + (drag ? ' active' : '')}>
        <div className="glyph">
          <Icon name="upload" size={40} />
        </div>
        <h2>Drag an audio file here</h2>
        <div className="sub">.mp3 · .m4a · .wav · .ogg · .flac · .webm</div>
        <div className="or">or</div>
        <button className="btn-ghost" onClick={handleBrowse}>Browse files…</button>
      </div>

      <div className="options-row">
        <OptionSelect
          label="Language"
          value={langLabel}
          options={LANGUAGES.map(l => ({ key: l.code, label: l.label, selected: l.code === language }))}
          onSelect={(k) => setLanguage(k)}
        />
        <OptionSelect
          label="Speakers"
          value={spkLabel}
          options={SPEAKERS.map(s => ({ key: s.value === undefined ? 'auto' : String(s.value), label: s.label, selected: s.value === numSpeakers }))}
          onSelect={(k) => setNumSpeakers(k === 'auto' ? undefined : Number(k))}
        />
        <OptionSelect
          label="Backend"
          value={backendLabel}
          options={BACKENDS.map(b => ({ key: b.value, label: b.label, selected: b.value === backend }))}
          onSelect={(k) => setBackend(k)}
        />
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
        <div className="head"><b>lexis</b><span>/ˈlɛksɪs/ &nbsp;·&nbsp; <em>noun</em></span></div>
        <div className="body">
          the full stock of words in a language. <em>From Greek</em> <b style={{fontWeight:500}}>λέξις</b>, <em>word, speech</em>. Yours, kept on your own machine.
        </div>
      </div>
    </div>
  );
}

interface OptionItem { key: string; label: string; selected: boolean }

function OptionSelect({ label, value, options, onSelect }: {
  label: string;
  value: string;
  options: OptionItem[];
  onSelect: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);
  return (
    <div className="option" ref={ref} onClick={() => setOpen(o => !o)} style={{ cursor: 'default', position: 'relative' }}>
      <div className="opt-label">{label}</div>
      <div className="opt-value">{value} <span className="chev"><Icon name="chev" size={12} /></span></div>
      {open && (
        <div className="opt-menu" onClick={e => e.stopPropagation()}>
          {options.map(o => (
            <div
              key={o.key}
              className={'opt-menu-item' + (o.selected ? ' selected' : '')}
              onClick={() => { onSelect(o.key); setOpen(false); }}
            >
              {o.label}
              {o.selected && <span className="check"><Icon name="check" size={12} /></span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
