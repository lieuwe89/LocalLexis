// Composes the PairingPayloadV1 that the mobile app scans from the QR.
// The desktop UI knows the hub port (from hub state) and mints the token;
// the LAN address + TLS pin come from GET /hub/info. Kept pure so it can
// be unit-tested without the Tauri/api layer.

export interface HubInfo {
  lan_addresses: string[];
  tls_enabled: boolean;
  tls_spki_b64: string | null;
}

export interface MintedToken {
  token: string;
  workspace_id: string;
}

export interface PairingPayloadV1 {
  hub_url: string;
  workspace_id: string;
  token: string;
  tls_spki_b64?: string;
}

/**
 * Build the PairingPayloadV1 from hub info, a freshly minted token, and the
 * hub port the UI already knows. Throws if the host has no usable LAN
 * address (offline / loopback-only), since a localhost URL is useless to a
 * phone.
 */
export function buildPairingPayload(
  info: HubInfo,
  token: MintedToken,
  port: number,
): PairingPayloadV1 {
  const ip = info.lan_addresses[0];
  if (!ip) {
    throw new Error(
      'No LAN address found for this machine — connect it to a network and try again.',
    );
  }
  const scheme = info.tls_enabled ? 'https' : 'http';
  const payload: PairingPayloadV1 = {
    hub_url: `${scheme}://${ip}:${port}`,
    workspace_id: token.workspace_id,
    token: token.token,
  };
  if (info.tls_spki_b64) {
    payload.tls_spki_b64 = info.tls_spki_b64;
  }
  return payload;
}
