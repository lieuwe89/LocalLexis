import type { PairingPayloadV1 } from './pairing';

export const RECORDER_PROVISIONING_PROTOCOL = 'locallexis.recorder.provision.v1';

export interface RecorderHello {
  protocol: typeof RECORDER_PROVISIONING_PROTOCOL;
  device_pubkey_b64: string;
  device_name?: string;
  firmware?: string;
}

export interface PairResponse {
  device_id: string;
  workspace_id: string;
  workspace_key_sealed_b64: string;
  lamport_observed: number;
}

export interface RecorderProvisioning {
  protocol: typeof RECORDER_PROVISIONING_PROTOCOL;
  hub_url: string;
  workspace_id: string;
  device_id: string;
  workspace_key_sealed_b64: string;
  lamport_observed: number;
  tls_spki_b64?: string;
}

interface BuildRecorderProvisioningArgs {
  pairingPayload: PairingPayloadV1;
  pairResponse: PairResponse;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function requiredString(
  record: Record<string, unknown>,
  key: string,
): string {
  const value = record[key];
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`recorder hello missing ${key}`);
  }
  return value;
}

export function parseRecorderHello(raw: string): RecorderHello {
  const parsed: unknown = JSON.parse(raw);
  if (!isRecord(parsed)) {
    throw new Error('recorder hello must be a JSON object');
  }
  const protocol = requiredString(parsed, 'protocol');
  if (protocol !== RECORDER_PROVISIONING_PROTOCOL) {
    throw new Error(`unsupported recorder protocol: ${protocol}`);
  }
  const device_pubkey_b64 = requiredString(parsed, 'device_pubkey_b64');
  return {
    protocol: RECORDER_PROVISIONING_PROTOCOL,
    device_pubkey_b64,
    device_name:
      typeof parsed.device_name === 'string' && parsed.device_name.trim()
        ? parsed.device_name
        : undefined,
    firmware:
      typeof parsed.firmware === 'string' && parsed.firmware.trim()
        ? parsed.firmware
        : undefined,
  };
}

export function buildRecorderProvisioning({
  pairingPayload,
  pairResponse,
}: BuildRecorderProvisioningArgs): RecorderProvisioning {
  if (pairingPayload.workspace_id !== pairResponse.workspace_id) {
    throw new Error(
      `workspace mismatch: pairing payload ${pairingPayload.workspace_id} ` +
      `but hub returned ${pairResponse.workspace_id}`,
    );
  }

  const response: RecorderProvisioning = {
    protocol: RECORDER_PROVISIONING_PROTOCOL,
    hub_url: pairingPayload.hub_url,
    workspace_id: pairResponse.workspace_id,
    device_id: pairResponse.device_id,
    workspace_key_sealed_b64: pairResponse.workspace_key_sealed_b64,
    lamport_observed: pairResponse.lamport_observed,
  };
  if (pairingPayload.tls_spki_b64) {
    response.tls_spki_b64 = pairingPayload.tls_spki_b64;
  }
  return response;
}
