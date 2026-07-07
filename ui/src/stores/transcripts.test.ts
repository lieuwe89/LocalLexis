import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useTranscripts } from './transcripts';

vi.mock('../api/client', () => ({ api: vi.fn() }));
import { api } from '../api/client';

describe('patchOp', () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useTranscripts.setState({ byId: {} });
  });

  it('sends the op with lamport_observed from cached clocks and reloads', async () => {
    useTranscripts.setState({
      byId: {
        t1: { _clocks: { title: { device: 'a', lamport: 7, ts: '' } } } as any,
      },
    });
    vi.mocked(api).mockResolvedValue({} as any);
    await useTranscripts.getState().patchOp('t1', 'set_title', 'title', 'New');
    const [path, init] = vi.mocked(api).mock.calls[0];
    expect(path).toBe('/transcripts/t1');
    expect(init!.method).toBe('PATCH');
    expect(JSON.parse(init!.body as string)).toEqual({
      op: 'set_title', key: 'title', value: 'New', lamport_observed: 7,
    });
    expect(vi.mocked(api).mock.calls[1][0]).toBe('/transcripts/t1'); // reload GET
  });

  it('defaults lamport_observed to 0 when doc not cached', async () => {
    vi.mocked(api).mockResolvedValue({} as any);
    await useTranscripts.getState().patchOp('t2', 'set_title', 'title', 'X');
    expect(JSON.parse(vi.mocked(api).mock.calls[0][1]!.body as string).lamport_observed).toBe(0);
  });

  it('rename and editSegment delegate to patchOp with the right op/key', async () => {
    vi.mocked(api).mockResolvedValue({} as any);
    await useTranscripts.getState().rename('t1', 'Title');
    expect(JSON.parse(vi.mocked(api).mock.calls[0][1]!.body as string))
      .toMatchObject({ op: 'set_title', key: 'title', value: 'Title' });
    vi.mocked(api).mockClear();
    await useTranscripts.getState().editSegment('t1', 2, 'fixed');
    expect(JSON.parse(vi.mocked(api).mock.calls[0][1]!.body as string))
      .toMatchObject({ op: 'edit_segment', key: 'segments.2.text', value: 'fixed' });
  });
});
