import { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { api } from '../../api/client';
import { buildWebPairingPayload } from '../../lib/pairing';
import type { PairingPayloadV1, MintedToken } from '../../lib/pairing';

// Matches the shape returned by GET /devices/paired (see native
// SettingsScreen.tsx's PairedDevice interface) — kept narrow to just the
// fields this screen renders.
interface PairedDevice {
  device_id: string;
  name: string;
  paired_at: string;
}

export function WebSettingsScreen() {
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const [payload, setPayload] = useState<PairingPayloadV1 | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDevices = () =>
    api<{ devices: PairedDevice[] }>('/devices/paired')
      .then(r => setDevices(r.devices))
      .catch(() => setDevices([]));

  useEffect(() => { loadDevices(); }, []);

  const mint = async () => {
    setError(null);
    try {
      // /pair/tokens actually returns {token, expires_at, workspace_id,
      // ttl_seconds} (see native SettingsScreen's PairingToken), but this
      // screen only needs the fields declared on MintedToken.
      const token = await api<MintedToken>('/pair/tokens', { method: 'POST' });
      setPayload(buildWebPairingPayload(window.location.origin, token));
    } catch (e) {
      setError(`Failed to mint pairing code: ${e}`);
    }
  };

  const unpair = async (d: PairedDevice) => {
    if (!window.confirm(`Unpair "${d.name}"?`)) return;
    await api(`/devices/paired/${encodeURIComponent(d.device_id)}`, { method: 'DELETE' });
    loadDevices();
  };

  return (
    <div className="web-settings">
      <section>
        <h2>Pair a device</h2>
        <button onClick={mint}>Mint pairing code</button>
        {error && <p role="alert">{error}</p>}
        {payload && (
          <div className="pairing-block">
            <QRCodeSVG value={JSON.stringify(payload)} size={220} aria-label="Pairing QR code" />
            <textarea readOnly value={JSON.stringify(payload)} rows={4} />
          </div>
        )}
      </section>
      <section>
        <h2>Paired devices</h2>
        <ul>
          {devices.map(d => (
            <li key={d.device_id}>
              {d.name} <button onClick={() => unpair(d)}>Unpair</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
