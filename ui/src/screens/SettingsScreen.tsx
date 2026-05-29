import { useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useConfig } from '../stores/config';
import { api, resetSidecarInfo } from '../api/client';
import type { ConfigDto } from '../api/types';
import { buildPairingPayload, type HubInfo, type PairingPayloadV1 } from '../lib/pairing';
import {
  buildRecorderProvisioning,
  type PairResponse,
  type RecorderHello,
  type RecorderProvisioning,
} from '../lib/recorderProvisioning';
import { QRCodeSVG } from 'qrcode.react';

interface HubState {
  enabled: boolean;
  port: number;
}

interface PairedDevice {
  device_id: string;
  name: string;
  paired_at: string;
  last_seen: string | null;
}

interface PairingToken {
  token: string;
  expires_at: number;
  workspace_id: string;
  ttl_seconds: number;
}

interface RecorderBleDevice {
  id: string;
  name: string | null;
  rssi: number | null;
}

type Draft = Partial<ConfigDto> & { hf_token?: string };

interface ModelStatus {
  name: string;
  status: 'bundled' | 'cached' | 'not_downloaded';
  size_mb: number;
}

function formatSize(mb: number): string {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`;
}

function statusLabel(s: ModelStatus): string {
  const base = `${s.name} · ${formatSize(s.size_mb)}`;
  switch (s.status) {
    case 'bundled':         return `${base} · ready (bundled)`;
    case 'cached':          return `${base} · ready (downloaded)`;
    case 'not_downloaded':  return `${base} · downloads on first use`;
  }
}

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
  const [models, setModels] = useState<ModelStatus[] | null>(null);
  const [hub, setHub] = useState<HubState | null>(null);
  const [hubBusy, setHubBusy] = useState(false);
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const [pairingPayload, setPairingPayload] = useState<PairingPayloadV1 | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  // Kept so the user can re-target the pairing URL at a different network
  // interface (e.g. when the first discovered address is a VPN/virtual one).
  const [hubInfo, setHubInfo] = useState<HubInfo | null>(null);
  const [mintedToken, setMintedToken] = useState<PairingToken | null>(null);
  const [selectedAddress, setSelectedAddress] = useState<string | null>(null);
  const [recorders, setRecorders] = useState<RecorderBleDevice[]>([]);
  const [bleBusy, setBleBusy] = useState(false);
  const [bleError, setBleError] = useState<string | null>(null);
  const [bleStatus, setBleStatus] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api<ModelStatus[]>('/models/whisper').then(setModels).catch(() => setModels([]));
  }, []);
  // Load hub state once on mount. Failure is silent — older sidecars
  // without the hub_state command leave `hub` null and the UI hides
  // the section.
  useEffect(() => {
    invoke<HubState>('get_hub_state').then(setHub).catch(() => setHub(null));
  }, []);
  // Refresh paired devices whenever hub mode flips, so the list shown
  // matches the current mode (and so toggling off then on doesn't
  // leave stale entries on screen).
  useEffect(() => {
    if (!hub) return;
    api<{ devices: PairedDevice[] }>('/devices/paired')
      .then(r => setDevices(r.devices))
      .catch(() => setDevices([]));
  }, [hub?.enabled]);
  if (!cfg) return <div className="settings"><p style={{ color: 'var(--ink-muted)' }}>Loading…</p></div>;

  const toggleHub = async (enabled: boolean) => {
    if (!hub) return;
    setHubBusy(true);
    setPairingPayload(null);
    setPairingError(null);
    setHubInfo(null);
    setMintedToken(null);
    setSelectedAddress(null);
    setRecorders([]);
    setBleError(null);
    setBleStatus(null);
    try {
      const updated = await invoke<HubState>('set_hub_state', { enabled, port: hub.port });
      // The sidecar just respawned on a fresh loopback port + token; drop the
      // stale connection cache so subsequent api() calls re-discover it.
      resetSidecarInfo();
      setHub(updated);
    } catch (e) {
      setPairingError(`failed to ${enabled ? 'enable' : 'disable'} hub: ${e}`);
    } finally {
      setHubBusy(false);
    }
  };

  const mintPairingToken = async () => {
    setPairingError(null);
    if (!hub) return;
    try {
      const minted = await api<PairingToken>('/pair/tokens', { method: 'POST' });
      const info = await api<HubInfo>('/hub/info');
      const addr = info.lan_addresses[0];
      const payload = buildPairingPayload(info, minted, hub.port, addr);
      setHubInfo(info);
      setMintedToken(minted);
      setSelectedAddress(addr ?? null);
      setPairingPayload(payload);
    } catch (e) {
      setPairingError(String(e));
    }
  };

  const chooseAddress = (addr: string) => {
    if (!hub || !hubInfo || !mintedToken) return;
    setSelectedAddress(addr);
    setPairingPayload(buildPairingPayload(hubInfo, mintedToken, hub.port, addr));
  };

  const copyPairingCode = async () => {
    if (!pairingPayload) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(pairingPayload));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable; the raw code is shown below for manual copy */
    }
  };

  const refreshDevices = async () => {
    try {
      const r = await api<{ devices: PairedDevice[] }>('/devices/paired');
      setDevices(r.devices);
    } catch {
      /* swallow; sticky list rather than blanking */
    }
  };

  const scanRecorders = async () => {
    setBleBusy(true);
    setBleError(null);
    setBleStatus('Scanning for LocalLexis recorders…');
    try {
      const found = await invoke<RecorderBleDevice[]>('ble_scan_recorders');
      setRecorders(found);
      setBleStatus(found.length ? `Found ${found.length} recorder(s).` : 'No recorders found.');
    } catch (e) {
      setBleError(String(e));
      setBleStatus(null);
    } finally {
      setBleBusy(false);
    }
  };

  const pairRecorderOverBle = async (recorder: RecorderBleDevice) => {
    if (!hub) return;
    setBleBusy(true);
    setBleError(null);
    setBleStatus(`Connecting to ${recorder.name ?? 'recorder'}…`);
    try {
      const hello = await invoke<RecorderHello>('ble_read_recorder_hello', {
        peripheralId: recorder.id,
      });
      const minted = await api<PairingToken>('/pair/tokens', { method: 'POST' });
      const info = await api<HubInfo>('/hub/info');
      const addr = selectedAddress ?? info.lan_addresses[0];
      const payload = buildPairingPayload(info, minted, hub.port, addr);
      const pairResponse = await api<PairResponse>('/pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: payload.token,
          device_pubkey_b64: hello.device_pubkey_b64,
          device_name: hello.device_name ?? recorder.name ?? 'LocalLexis Recorder',
        }),
      });
      const provisioning: RecorderProvisioning = buildRecorderProvisioning({
        pairingPayload: payload,
        pairResponse,
      });
      await invoke('ble_send_recorder_provisioning', {
        peripheralId: recorder.id,
        provisioning,
      });
      setHubInfo(info);
      setMintedToken(minted);
      setSelectedAddress(addr ?? null);
      setPairingPayload(payload);
      setBleStatus(`Provisioned ${hello.device_name ?? recorder.name ?? pairResponse.device_id}.`);
      await refreshDevices();
    } catch (e) {
      setBleError(String(e));
      setBleStatus(null);
    } finally {
      setBleBusy(false);
    }
  };

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
        <div className="model-field">
          <select value={draft.asr_model ?? cfg.asr_model} onChange={e => set('asr_model', e.target.value)}>
            {(models ?? []).map(m => (
              <option key={m.name} value={m.name}>{statusLabel(m)}</option>
            ))}
          </select>
          {(() => {
            const selected = (draft.asr_model ?? cfg.asr_model);
            const s = models?.find(m => m.name === selected);
            if (!s) return null;
            const cls = s.status === 'not_downloaded' ? 'warn' : 'ok';
            const label = s.status === 'bundled' ? 'Bundled with app'
              : s.status === 'cached' ? 'Downloaded'
              : `Not yet downloaded (~${formatSize(s.size_mb)})`;
            return <span className={`model-status model-status-${cls}`}>{label}</span>;
          })()}
        </div>
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

      {hub && (
        <section className="hub-mode" style={{ marginTop: '2rem', borderTop: '1px solid var(--rule)', paddingTop: '1.25rem' }}>
          <h2 style={{ margin: '0 0 0.5rem' }}>Hub mode</h2>
          <p style={{ color: 'var(--ink-muted)', marginTop: 0 }}>
            Expose this app's API on the local network so paired phones,
            tablets, or other LocalLexis installs can sync transcripts.
            Off by default — only turn it on if you actually want remote
            devices to reach this machine.
          </p>
          <Field label={`Hub mode ${hub.enabled ? `on (port ${hub.port})` : 'off'}`}>
            <input
              type="checkbox"
              checked={hub.enabled}
              disabled={hubBusy}
              onChange={(e) => toggleHub(e.target.checked)}
            />
          </Field>

          {hub.enabled && (
            <>
              <h3 style={{ marginBottom: '0.25rem' }}>Pair a new device</h3>
              <p style={{ color: 'var(--ink-muted)', marginTop: 0, fontSize: '0.9em' }}>
                Mint a single-use pairing code (5 minute TTL), then scan the QR
                with the LocalLexis app on your phone (Pair tab).
              </p>
              <button type="button" onClick={mintPairingToken} disabled={hubBusy}>
                Generate pairing code
              </button>
              {hubInfo && hubInfo.lan_addresses.length > 1 && (
                <label style={{ display: 'block', marginTop: '0.5rem', fontSize: '0.9em' }}>
                  Network address:{' '}
                  <select
                    value={selectedAddress ?? ''}
                    onChange={(e) => chooseAddress(e.target.value)}
                  >
                    {hubInfo.lan_addresses.map((a) => (
                      <option key={a} value={a}>{a}</option>
                    ))}
                  </select>
                </label>
              )}
              {pairingPayload && (
                <div style={{ marginTop: '0.75rem' }}>
                  <div
                    role="img"
                    aria-label="Pairing QR code"
                    style={{
                      display: 'inline-block',
                      background: '#ffffff',
                      padding: '12px',
                      borderRadius: '8px',
                    }}
                  >
                    <QRCodeSVG
                      value={JSON.stringify(pairingPayload)}
                      size={224}
                      level="M"
                      marginSize={2}
                      title="LocalLexis pairing code"
                    />
                  </div>
                  <details style={{ marginTop: '0.5rem' }}>
                    <summary
                      style={{
                        cursor: 'pointer',
                        fontSize: '0.85em',
                        color: 'var(--ink-muted)',
                      }}
                    >
                      Can't scan? Enter the code manually
                    </summary>
                    <button
                      type="button"
                      onClick={copyPairingCode}
                      style={{ marginTop: '0.5rem' }}
                    >
                      {copied ? 'Copied' : 'Copy code'}
                    </button>
                    <pre
                      style={{
                        background: 'var(--bg-muted, #f5f3ec)',
                        padding: '0.75rem',
                        marginTop: '0.5rem',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.85em',
                        overflowX: 'auto',
                      }}
                    >
                      {JSON.stringify(pairingPayload, null, 2)}
                    </pre>
                  </details>
                </div>
              )}
              {pairingError && (
                <p style={{ color: 'var(--ink-error, crimson)' }}>{pairingError}</p>
              )}
            </>
          )}

          <h3 style={{ margin: '1.25rem 0 0.25rem' }}>
            Bluetooth recorder setup
          </h3>
          <button type="button" onClick={scanRecorders} disabled={bleBusy}>
            {bleBusy ? 'Working…' : 'Scan for Bluetooth recorders'}
          </button>
          {bleStatus && (
            <p style={{ color: 'var(--ink-muted)' }}>{bleStatus}</p>
          )}
          {bleError && (
            <p style={{ color: 'var(--ink-error, crimson)' }}>{bleError}</p>
          )}
          {!hub.enabled && (
            <p style={{ color: 'var(--ink-muted)', marginTop: '0.5rem', fontSize: '0.9em' }}>
              Hub mode must be on before pairing.
            </p>
          )}
          {recorders.length > 0 && (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {recorders.map((recorder) => (
                <li
                  key={recorder.id}
                  style={{
                    padding: '0.5rem 0',
                    borderBottom: '1px solid var(--rule, #e5e0d3)',
                  }}
                >
                  <div>
                    <strong>{recorder.name ?? 'LocalLexis Recorder'}</strong>
                    {recorder.rssi !== null && (
                      <span style={{ color: 'var(--ink-muted)' }}>
                        {' '}· RSSI {recorder.rssi}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => pairRecorderOverBle(recorder)}
                    disabled={bleBusy || !hub.enabled}
                  >
                    Pair over Bluetooth
                  </button>
                </li>
              ))}
            </ul>
          )}

          <h3 style={{ margin: '1.25rem 0 0.25rem' }}>
            Paired devices ({devices.length})
          </h3>
          <button type="button" onClick={refreshDevices}>
            Refresh
          </button>
          {devices.length === 0 ? (
            <p style={{ color: 'var(--ink-muted)' }}>
              No devices paired yet.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {devices.map((d) => (
                <li key={d.device_id} style={{ padding: '0.5rem 0', borderBottom: '1px solid var(--rule, #e5e0d3)' }}>
                  <div><strong>{d.name}</strong> <code style={{ fontSize: '0.85em', color: 'var(--ink-muted)' }}>{d.device_id}</code></div>
                  <div style={{ fontSize: '0.85em', color: 'var(--ink-muted)' }}>
                    paired {d.paired_at.slice(0, 16).replace('T', ' ')}
                    {' · '}
                    {d.last_seen
                      ? `last seen ${d.last_seen.slice(0, 16).replace('T', ' ')}`
                      : 'never seen'}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
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
