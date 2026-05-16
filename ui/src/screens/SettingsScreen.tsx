import { useEffect, useRef, useState } from 'react';
import { useConfig } from '../stores/config';
import type { ConfigDto } from '../api/types';

type Draft = Partial<ConfigDto> & { hf_token?: string };

const INFO: Record<string, string> = {
  backend:
    'Compute backend used by the ASR + diarization models. ' +
    '"auto" picks the best available on this machine. ' +
    '"cpu" works everywhere but is slowest. "cuda" requires an NVIDIA GPU. ' +
    '"mps" uses Apple Silicon GPU (partial — falls back to CPU for ASR).',
  asr_model:
    'Whisper model used for transcription. Larger = more accurate, slower, more memory.\n\n' +
    'Sizes & first-run download:\n' +
    '• tiny / tiny.en — ~75 MB\n' +
    '• base / base.en — ~140 MB (bundled, no download)\n' +
    '• small / small.en — ~470 MB\n' +
    '• medium / medium.en — ~1.5 GB\n' +
    '• large-v3 — ~3 GB (several minutes on a typical connection)\n\n' +
    'Anything other than the bundled default downloads to the cache dir on first use, with no visible progress until it finishes. The .en variants are English-only and a bit faster.',
  hf_token:
    'Hugging Face access token, required by pyannote diarization to download the speaker model. ' +
    'Create one at huggingface.co/settings/tokens and accept the pyannote/speaker-diarization-3.1 license.',
  model_cache_dir:
    'Directory where downloaded ASR and diarization models are stored. ' +
    'Models can be several GB. Point this at a fast SSD with enough free space.',
  default_out_dir:
    'Where transcript .txt and .json files are saved. ' +
    'Leave blank to write next to the source audio file.',
  watch_recursive:
    'When watching a folder, also include audio inside subdirectories. ' +
    'Turn off if you only want to process the top level.',
  watch_debounce:
    'How long to wait after a file appears or stops growing before transcribing it (seconds). ' +
    'Higher values are safer for large files being copied in.',
  watch_extensions:
    'File extensions the watcher will pick up. Comma-separated, no dots. ' +
    'Anything else in the folder is ignored.',
};

export function SettingsScreen() {
  const cfg = useConfig(s => s.cfg);
  const load = useConfig(s => s.load);
  const patch = useConfig(s => s.patch);
  const [draft, setDraft] = useState<Draft>({});
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => { load(); }, [load]);
  if (!cfg) return <div className="settings"><p style={{ color: 'var(--ink-muted)' }}>Loading…</p></div>;

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft(d => ({ ...d, [k]: v }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try { await patch(draft); setDraft({}); setDirty(false); } catch {}
    setSaving(false);
  };

  const watchVal = (draft.watch ?? cfg.watch) as ConfigDto['watch'];
  const showHfBanner = !cfg.hf_token_set && !draft.hf_token;

  return (
    <div className="settings">
      {showHfBanner && (
        <div className="banner warn">
          Hugging Face token not set — diarization will fail without it.
        </div>
      )}
      <Field label="Backend" info={INFO.backend}>
        <select value={draft.backend ?? cfg.backend} onChange={e => set('backend', e.target.value as ConfigDto['backend'])}>
          {(['auto','cpu','cuda','mps'] as const).map(b => <option key={b} value={b}>{b}</option>)}
        </select>
      </Field>
      <Field label="ASR model" info={INFO.asr_model}>
        <input value={draft.asr_model ?? cfg.asr_model} onChange={e => set('asr_model', e.target.value)} />
      </Field>
      <Field label="Hugging Face token" info={INFO.hf_token}>
        <input
          type="password"
          placeholder={cfg.hf_token_set ? '••••••••' : 'hf_…'}
          value={draft.hf_token ?? ''}
          onChange={e => set('hf_token', e.target.value)}
        />
      </Field>
      <Field label="Model cache dir" info={INFO.model_cache_dir}>
        <input value={draft.model_cache_dir ?? cfg.model_cache_dir} onChange={e => set('model_cache_dir', e.target.value)} />
      </Field>
      <Field label="Default out dir" info={INFO.default_out_dir}>
        <input
          value={draft.default_out_dir ?? cfg.default_out_dir ?? ''}
          onChange={e => set('default_out_dir', e.target.value || null)}
        />
      </Field>
      <Field label="Watch recursive" info={INFO.watch_recursive}>
        <input type="checkbox" checked={watchVal.recursive} onChange={e => set('watch', { ...watchVal, recursive: e.target.checked })} />
      </Field>
      <Field label="Watch debounce (s)" info={INFO.watch_debounce}>
        <input type="number" min={0} value={watchVal.debounce_seconds} onChange={e => set('watch', { ...watchVal, debounce_seconds: Number(e.target.value) })} />
      </Field>
      <Field label="Watch extensions" info={INFO.watch_extensions}>
        <input
          value={watchVal.extensions.join(', ')}
          onChange={e => set('watch', { ...watchVal, extensions: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
        />
      </Field>
      <div className="settings-actions">
        <button className="btn-apply" disabled={!dirty || saving} onClick={save}>
          {dirty ? (saving ? 'Saving…' : 'Save') : 'Saved'}
        </button>
      </div>
    </div>
  );
}

function Field({ label, info, children }: { label: string; info?: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="lbl">
        <span className="lbl-row">
          {label}
          {info && <InfoButton text={info} />}
        </span>
      </span>
      {children}
    </label>
  );
}

function InfoButton({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return (
    <span ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        className="info-btn"
        aria-label="More info"
        onClick={(e) => { e.preventDefault(); setOpen(o => !o); }}
      >i</button>
      {open && <div className="info-popover" onClick={e => e.stopPropagation()}>{text}</div>}
    </span>
  );
}
