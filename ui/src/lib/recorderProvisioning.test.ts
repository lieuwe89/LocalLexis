import { describe, expect, it } from 'vitest';
import {
  buildRecorderProvisioning,
  parseRecorderHello,
  RECORDER_PROVISIONING_PROTOCOL,
} from './recorderProvisioning';

describe('recorder BLE provisioning payloads', () => {
  it('parses a recorder hello with the ESP32 public key', () => {
    const hello = parseRecorderHello(JSON.stringify({
      protocol: RECORDER_PROVISIONING_PROTOCOL,
      device_pubkey_b64: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
      device_name: 'desk recorder',
      firmware: '0.1.0',
    }));

    expect(hello).toEqual({
      protocol: RECORDER_PROVISIONING_PROTOCOL,
      device_pubkey_b64: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
      device_name: 'desk recorder',
      firmware: '0.1.0',
    });
  });

  it('rejects hellos from another protocol', () => {
    expect(() => parseRecorderHello(JSON.stringify({
      protocol: 'other',
      device_pubkey_b64: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
    }))).toThrow(/unsupported recorder protocol/);
  });

  it('builds the sealed hub provisioning response without returning the token', () => {
    const response = buildRecorderProvisioning({
      pairingPayload: {
        hub_url: 'https://192.168.1.8:8765',
        workspace_id: 'ws_abc',
        token: 'single-use-token',
        tls_spki_b64: 'PIN=',
      },
      pairResponse: {
        device_id: 'dev-abc',
        workspace_id: 'ws_abc',
        workspace_key_sealed_b64: 'SEALED=',
        lamport_observed: 12,
      },
    });

    expect(response).toEqual({
      protocol: RECORDER_PROVISIONING_PROTOCOL,
      hub_url: 'https://192.168.1.8:8765',
      workspace_id: 'ws_abc',
      device_id: 'dev-abc',
      workspace_key_sealed_b64: 'SEALED=',
      lamport_observed: 12,
      tls_spki_b64: 'PIN=',
    });
    expect(JSON.stringify(response)).not.toContain('single-use-token');
  });

  it('rejects a pair response for the wrong workspace', () => {
    expect(() => buildRecorderProvisioning({
      pairingPayload: {
        hub_url: 'https://192.168.1.8:8765',
        workspace_id: 'ws_a',
        token: 't',
      },
      pairResponse: {
        device_id: 'dev-abc',
        workspace_id: 'ws_b',
        workspace_key_sealed_b64: 'SEALED=',
        lamport_observed: 0,
      },
    })).toThrow(/workspace mismatch/);
  });
});
