// Sidecar hub-client controls (join/leave/status). These talk to the
// LOCAL sidecar's loopback API, which in turn talks to the remote hub.
import { api } from '../api/client';

export interface HubClientStatus {
  joined: boolean;
  hub_url?: string;
  workspace_id?: string;
  device_id?: string;
  device_name?: string;
  cursor?: number;
  pending_uploads?: number;
  last_error?: string | null;
  last_sync_at?: number | null;
  migrated_at?: number | null;
  offline_capture?: string;
}

export async function hubStatus(): Promise<HubClientStatus> {
  return api<HubClientStatus>('/client/hub');
}

export async function joinHub(
  pairingString: string,
  deviceName: string,
): Promise<HubClientStatus> {
  return api<HubClientStatus>('/client/hub/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pairing_string: pairingString,
      device_name: deviceName,
    }),
  });
}

export async function leaveHub(): Promise<HubClientStatus> {
  return api<HubClientStatus>('/client/hub/leave', { method: 'POST' });
}

export async function startMigration(): Promise<{ job_id: string }> {
  return api<{ job_id: string }>('/client/hub/migrate', { method: 'POST' });
}
