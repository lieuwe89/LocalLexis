import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useConfig } from '../../stores/config';
import { Field } from './SettingsForm';
import type { ConfigDto } from '../../api/types';

const PRESETS: Record<string, string> = {
  lemonade: 'http://127.0.0.1:13305/api/v1',
  openrouter: 'https://openrouter.ai/api/v1',
};

type SummarizeDraft = Partial<ConfigDto['summarize']> & { api_key?: string };

export function SummarizeSettings() {
  const cfg = useConfig(s => s.cfg);
  const patch = useConfig(s => s.patch);
  const [draft, setDraft] = useState<SummarizeDraft>({});
  const [models, setModels] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ models: string[] }>('/summarize/models')
      .then(r => setModels(r.models))
      .catch(() => setModels(null)); // provider down → free-text model input
  }, [cfg?.summarize.base_url]);

  if (!cfg) return null;
  const s = cfg.summarize;
  const val = <K extends keyof SummarizeDraft>(k: K): string =>
    (draft[k] as string | undefined) ?? ((s as Record<string, unknown>)[k] as string | undefined) ?? '';
  const dirty = Object.keys(draft).length > 0;

  const setProvider = (p: string) => {
    setDraft(d => ({ ...d, provider: p as ConfigDto['summarize']['provider'], ...(PRESETS[p] ? { base_url: PRESETS[p] } : {}) }));
  };

  const save = async () => {
    setSaving(true);
    try { await patch({ summarize: draft }); setDraft({}); } catch {}
    setSaving(false);
  };

  return (
    <section className="summarize-settings" style={{ marginTop: '2rem', borderTop: '1px solid var(--rule)', paddingTop: '1.25rem' }}>
      <h2 style={{ margin: '0 0 0.5rem' }}>Summarization</h2>
      <p style={{ color: 'var(--ink-muted)', marginTop: 0 }}>
        LLM used for the Summarize button. Any OpenAI-compatible server works —
        Lemonade on this machine, OpenRouter, or a custom endpoint.
      </p>
      <Field label="Provider">
        <select value={val('provider')} onChange={e => setProvider(e.target.value)}>
          {['lemonade', 'openrouter', 'custom'].map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </Field>
      <Field label="Base URL">
        <input value={val('base_url')} onChange={e => setDraft(d => ({ ...d, base_url: e.target.value }))} />
      </Field>
      <Field label="Model">
        {models && models.length > 0 ? (
          <select value={val('model')} onChange={e => setDraft(d => ({ ...d, model: e.target.value }))}>
            {!models.includes(val('model')) && <option value={val('model')}>{val('model')}</option>}
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        ) : (
          <input value={val('model')} onChange={e => setDraft(d => ({ ...d, model: e.target.value }))} />
        )}
      </Field>
      <Field label="API key">
        <input type="password" placeholder={s.api_key_set ? '••••••••' : 'none (Lemonade default)'}
               value={draft.api_key ?? ''} onChange={e => setDraft(d => ({ ...d, api_key: e.target.value }))} />
      </Field>
      <div className="settings-actions">
        <button className="btn-apply" disabled={!dirty || saving} onClick={save}>
          {dirty ? (saving ? 'Saving…' : 'Save') : 'Saved'}
        </button>
      </div>
    </section>
  );
}
