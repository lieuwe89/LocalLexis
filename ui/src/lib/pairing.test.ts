import { describe, expect, it } from 'vitest';
import { buildPairingPayload } from './pairing';

const token = { token: 'tok_abc', workspace_id: 'ws_42' };

describe('buildPairingPayload', () => {
  it('builds an https payload with the SPKI pin', () => {
    const p = buildPairingPayload(
      { lan_addresses: ['192.168.1.50'], tls_enabled: true, tls_spki_b64: 'PIN==' },
      token,
      8765,
    );
    expect(p).toEqual({
      hub_url: 'https://192.168.1.50:8765',
      workspace_id: 'ws_42',
      token: 'tok_abc',
      tls_spki_b64: 'PIN==',
    });
  });

  it('uses http and omits the pin when TLS is off', () => {
    const p = buildPairingPayload(
      { lan_addresses: ['10.0.0.2'], tls_enabled: false, tls_spki_b64: null },
      token,
      9000,
    );
    expect(p.hub_url).toBe('http://10.0.0.2:9000');
    expect(p.tls_spki_b64).toBeUndefined();
  });

  it('picks the first LAN address when several are present', () => {
    const p = buildPairingPayload(
      { lan_addresses: ['192.168.1.50', '10.8.0.3'], tls_enabled: true, tls_spki_b64: 'X' },
      token,
      8765,
    );
    expect(p.hub_url).toBe('https://192.168.1.50:8765');
  });

  it('throws when no LAN address is available', () => {
    expect(() =>
      buildPairingPayload(
        { lan_addresses: [], tls_enabled: true, tls_spki_b64: 'x' },
        token,
        8765,
      ),
    ).toThrow(/LAN address/);
  });
});
