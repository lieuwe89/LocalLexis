import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { api, resetSidecarInfo } from '../api/client';
import { buildPairingPayload, type HubInfo, type PairingPayloadV1 } from '../lib/pairing';
import {
  buildRecorderProvisioning,
  type PairResponse,
  type RecorderHello,
  type RecorderProvisioning,
} from '../lib/recorderProvisioning';
import { QRCodeSVG } from 'qrcode.react';
import { hubStatus, joinHub, leaveHub, setOfflineCapture, startMigration, type HubClientStatus } from '../lib/hubClient';
import { SettingsForm, Field } from './settings/SettingsForm';
import { SummarizeSettings } from './settings/SummarizeSettings';
import { TrashSection } from './settings/TrashSection';
import type { JobRecord, MigrateResult } from '../api/types';

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

export function SettingsScreen({ pollMs = 1500 }: { pollMs?: number } = {}) {
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
  const [clientHub, setClientHub] = useState<HubClientStatus | null>(null);
  const [pairingString, setPairingString] = useState('');
  const [joinDeviceName, setJoinDeviceName] = useState('');
  const [joinBusy, setJoinBusy] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [migrateBusy, setMigrateBusy] = useState(false);
  const [migrateError, setMigrateError] = useState<string | null>(null);
  const [migrateResult, setMigrateResult] = useState<MigrateResult | null>(null);
  const [offlineCaptureBusy, setOfflineCaptureBusy] = useState(false);
  const [offlineCaptureError, setOfflineCaptureError] = useState<string | null>(null);

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
  // Load client-hub status once on mount. Failure is silent — older
  // sidecars without the /client/hub route leave `clientHub` null and the
  // card just shows the "not joined" state.
  useEffect(() => {
    hubStatus().then(setClientHub).catch(() => setClientHub(null));
  }, []);

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

  const doJoinHub = async () => {
    setJoinBusy(true);
    setJoinError(null);
    try {
      await joinHub(pairingString.trim(), joinDeviceName.trim() || 'desktop');
      setClientHub(await hubStatus());
      setPairingString('');
    } catch (e) {
      setJoinError(`join failed: ${e}`);
    } finally {
      setJoinBusy(false);
    }
  };

  const doLeaveHub = async () => {
    setJoinBusy(true);
    try {
      await leaveHub();
      setClientHub(await hubStatus());
    } finally {
      setJoinBusy(false);
    }
  };

  const doMigrate = async () => {
    const ok = window.confirm(
      'Migrate all local transcripts to the hub and move the originals to trash?\n\n' +
      'You can restore them from Settings → Trash.',
    );
    if (!ok) return;
    setMigrateBusy(true);
    setMigrateError(null);
    setMigrateResult(null);
    try {
      const { job_id } = await startMigration();
      for (;;) {
        const rec = await api<JobRecord>(`/jobs/${job_id}`);
        if (rec.status === 'complete') { setMigrateResult((rec.result as MigrateResult) ?? null); break; }
        if (rec.status === 'failed') { setMigrateError(rec.error ?? 'migration failed'); break; }
        await new Promise(r => setTimeout(r, pollMs));
      }
      setClientHub(await hubStatus());
    } catch (e) {
      setMigrateError(e instanceof Error ? e.message : String(e));
    } finally {
      setMigrateBusy(false);
    }
  };

  const changeOfflineCapture = async (mode: 'local' | 'queue') => {
    setOfflineCaptureBusy(true);
    setOfflineCaptureError(null);
    try {
      await setOfflineCapture(mode);
      setClientHub(await hubStatus());
    } catch (e) {
      setOfflineCaptureError(e instanceof Error ? e.message : String(e));
    } finally {
      setOfflineCaptureBusy(false);
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

  const unpairDevice = async (d: PairedDevice) => {
    const ok = window.confirm(
      `Unpair "${d.name}"?\n\nThe device will lose sync access immediately. ` +
      `It can re-pair by scanning a new pairing code.`,
    );
    if (!ok) return;
    try {
      await api(`/devices/paired/${encodeURIComponent(d.device_id)}`, {
        method: 'DELETE',
      });
      setDevices((cur) => cur.filter((x) => x.device_id !== d.device_id));
    } catch (e) {
      window.alert(`Failed to unpair: ${e}`);
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
        expectedName: recorder.name,
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
        expectedName: recorder.name,
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

  return (
    <div className="settings">
      <SettingsForm />
      <SummarizeSettings />
      <TrashSection />

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
                <li
                  key={d.device_id}
                  style={{
                    padding: '0.5rem 0',
                    borderBottom: '1px solid var(--rule, #e5e0d3)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div><strong>{d.name}</strong> <code style={{ fontSize: '0.85em', color: 'var(--ink-muted)' }}>{d.device_id}</code></div>
                    <div style={{ fontSize: '0.85em', color: 'var(--ink-muted)' }}>
                      paired {d.paired_at.slice(0, 16).replace('T', ' ')}
                      {' · '}
                      {d.last_seen
                        ? `last seen ${d.last_seen.slice(0, 16).replace('T', ' ')}`
                        : 'never seen'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => unpairDevice(d)}
                    aria-label={`Unpair ${d.name}`}
                  >
                    Unpair
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="join-hub" style={{ marginTop: '2rem', borderTop: '1px solid var(--rule)', paddingTop: '1.25rem' }}>
        <h2 style={{ margin: '0 0 0.5rem' }}>Join a hub</h2>
        {clientHub?.joined ? (
          <div>
            <p style={{ color: 'var(--ink-muted)', marginTop: 0 }}>
              Connected to <code>{clientHub.hub_url}</code> as{' '}
              <code>{clientHub.device_name}</code>
            </p>
            <p style={{ color: 'var(--ink-muted)' }}>
              {clientHub.pending_uploads
                ? `${clientHub.pending_uploads} recording(s) waiting for hub`
                : 'All uploads sent'}
              {clientHub.last_error ? ` — ${clientHub.last_error}` : ''}
            </p>
            <button type="button" onClick={doLeaveHub} disabled={joinBusy}>
              Leave hub
            </button>

            <div className="hub-offline-capture" style={{ marginTop: '1.25rem' }}>
              <Field label="When offline">
                <select
                  value={clientHub.offline_capture ?? 'local'}
                  disabled={offlineCaptureBusy}
                  onChange={(e) => changeOfflineCapture(e.target.value as 'local' | 'queue')}
                >
                  <option value="local">Transcribe locally</option>
                  <option value="queue">Wait for hub</option>
                </select>
              </Field>
              <p style={{ color: 'var(--ink-muted)', marginTop: 0, fontSize: '0.9em' }}>
                What captures do when the hub is unreachable.
              </p>
              {offlineCaptureError && (
                <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{offlineCaptureError}</p>
              )}
            </div>

            <div className="hub-migrate" style={{ marginTop: '1.25rem' }}>
              <h3 style={{ margin: '0 0 0.25rem' }}>Migrate library to hub</h3>
              {clientHub.migrated_at ? (
                <p style={{ color: 'var(--ink-muted)' }}>
                  Library migrated on{' '}
                  {new Date(clientHub.migrated_at * 1000).toLocaleDateString()}
                </p>
              ) : (
                <>
                  <p style={{ color: 'var(--ink-muted)', marginTop: 0 }}>
                    Send all locally recorded transcripts to the hub, one time.
                    Originals are archived to trash after the hub copy is verified.
                  </p>
                  <button type="button" onClick={doMigrate} disabled={migrateBusy}>
                    {migrateBusy ? 'Migrating…' : 'Migrate library to hub'}
                  </button>
                  {migrateError && (
                    <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{migrateError}</p>
                  )}
                  {migrateResult && (
                    <div style={{ marginTop: '0.5rem' }}>
                      <p>{migrateResult.migrated.length} transcripts migrated</p>
                      {migrateResult.failed.length > 0 && (
                        <ul style={{ listStyle: 'none', padding: 0 }}>
                          {migrateResult.failed.map((f) => (
                            <li
                              key={f.id}
                              style={{ whiteSpace: 'normal', overflowWrap: 'break-word' }}
                            >
                              {f.id}: {f.error}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ) : (
          <div>
            <p style={{ color: 'var(--ink-muted)', marginTop: 0 }}>
              Paste a pairing code from the hub (run{' '}
              <code>locallexis-hub pair</code> on the server) to send
              recordings here for processing and sync transcripts back.
            </p>
            <input
              aria-label="pairing code"
              value={pairingString}
              onChange={(e) => setPairingString(e.target.value)}
              placeholder="pairing code"
              style={{ display: 'block', marginBottom: '0.5rem' }}
            />
            <input
              aria-label="device name"
              value={joinDeviceName}
              onChange={(e) => setJoinDeviceName(e.target.value)}
              placeholder="device name (e.g. lieuwe-laptop)"
              style={{ display: 'block', marginBottom: '0.5rem' }}
            />
            <button
              type="button"
              onClick={doJoinHub}
              disabled={joinBusy || !pairingString.trim()}
            >
              Join
            </button>
            {joinError && (
              <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{joinError}</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
