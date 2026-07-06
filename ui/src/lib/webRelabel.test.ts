import { describe, it, expect, vi } from 'vitest';
import { webRelabel } from './webRelabel';

describe('webRelabel', () => {
  it('seeds observed lamport from _clocks and chains assigned', async () => {
    const calls: any[] = [];
    const api = vi.fn(async (_path: string, init?: any) => {
      if (init?.method === 'PATCH') {
        calls.push(JSON.parse(init.body));
        return { lamport_assigned: (calls.length) + 5 };
      }
      // GET transcript
      return { _clocks: { 'speakers.SPEAKER_00': { lamport: 3 } } };
    });
    await webRelabel(api as any, 't1', { SPEAKER_00: 'Alice', SPEAKER_01: 'Bob' });
    expect(calls[0]).toMatchObject({ op: 'relabel', key: 'speakers.SPEAKER_00', value: 'Alice', lamport_observed: 3 });
    // second op observes the first assigned (6)
    expect(calls[1].lamport_observed).toBeGreaterThanOrEqual(6);
  });
});
