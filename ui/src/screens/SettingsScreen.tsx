import { useEffect, useState } from 'react';
import { useConfig } from '../stores/config';
import type { ConfigDto } from '../api/types';

type Draft = Partial<ConfigDto> & { hf_token?: string };

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
      <Field label="Backend">
        <select value={draft.backend ?? cfg.backend} onChange={e => set('backend', e.target.value as ConfigDto['backend'])}>
          {(['auto','cpu','cuda','mps'] as const).map(b => <option key={b} value={b}>{b}</option>)}
        </select>
      </Field>
      <Field label="ASR model">
        <input value={draft.asr_model ?? cfg.asr_model} onChange={e => set('asr_model', e.target.value)} />
      </Field>
      <Field label="Hugging Face token">
        <input
          type="password"
          placeholder={cfg.hf_token_set ? '••••••••' : 'hf_…'}
          value={draft.hf_token ?? ''}
          onChange={e => set('hf_token', e.target.value)}
        />
      </Field>
      <Field label="Model cache dir">
        <input value={draft.model_cache_dir ?? cfg.model_cache_dir} onChange={e => set('model_cache_dir', e.target.value)} />
      </Field>
      <Field label="Default out dir">
        <input
          value={draft.default_out_dir ?? cfg.default_out_dir ?? ''}
          onChange={e => set('default_out_dir', e.target.value || null)}
        />
      </Field>
      <Field label="Watch recursive">
        <input type="checkbox" checked={watchVal.recursive} onChange={e => set('watch', { ...watchVal, recursive: e.target.checked })} />
      </Field>
      <Field label="Watch debounce (s)">
        <input type="number" min={0} value={watchVal.debounce_seconds} onChange={e => set('watch', { ...watchVal, debounce_seconds: Number(e.target.value) })} />
      </Field>
      <Field label="Watch extensions">
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="lbl">{label}</span>
      {children}
    </label>
  );
}
