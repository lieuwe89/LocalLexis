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
 *
 * ``address`` selects which LAN interface to advertise; it defaults to the
 * first discovered address. A host with several interfaces (Ethernet, Wi-Fi,
 * VPN, docker0) may list a virtual/unreachable address first, so the UI lets
 * the user choose and passes the choice here.
 */
export function buildPairingPayload(
  info: HubInfo,
  token: MintedToken,
  port: number,
  address?: string,
): PairingPayloadV1 {
  const ip = address ?? info.lan_addresses[0];
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

// The web pairing page knows the hub's reachable address from the browser
// (window.location.origin), so it skips the LAN-address guesswork that
// buildPairingPayload does for the desktop app.
export function buildWebPairingPayload(
  origin: string,
  token: MintedToken,
): PairingPayloadV1 {
  return { hub_url: origin, workspace_id: token.workspace_id, token: token.token };
}
