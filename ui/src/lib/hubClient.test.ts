import { describe, expect, it, vi } from 'vitest';

import { hubStatus, joinHub, leaveHub } from './hubClient';

vi.mock('../api/client', () => ({
  api: vi.fn(),
}));

import { api } from '../api/client';

describe('hubClient', () => {
  it('hubStatus GETs /client/hub', async () => {
    (api as any).mockResolvedValue({ joined: false });
    expect(await hubStatus()).toEqual({ joined: false });
    expect(api).toHaveBeenCalledWith('/client/hub');
  });

  it('joinHub POSTs pairing string and device name', async () => {
    (api as any).mockResolvedValue({ joined: true, device_id: 'dev-1' });
    await joinHub('UGFpcg==', 'my-laptop');
    expect(api).toHaveBeenCalledWith('/client/hub/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pairing_string: 'UGFpcg==',
        device_name: 'my-laptop',
      }),
    });
  });

  it('leaveHub POSTs /client/hub/leave', async () => {
    (api as any).mockResolvedValue({ joined: false });
    await leaveHub();
    expect(api).toHaveBeenCalledWith('/client/hub/leave', { method: 'POST' });
  });
});
