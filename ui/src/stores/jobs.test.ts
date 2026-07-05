import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobRecord } from '../api/types';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  subscribeJob: vi.fn(),
}));

vi.mock('../api/client', () => ({
  api: mocks.api,
}));

vi.mock('../api/sse', () => ({
  subscribeJob: mocks.subscribeJob,
}));

import { useJobs } from './jobs';

function rec(overrides: Partial<JobRecord>): JobRecord {
  return {
    id: 'job1',
    kind: 'transcribe',
    status: 'pending',
    stage: '',
    percent: 0,
    error: null,
    transcript_id: null,
    audio_path: null,
    paths: {},
    ...overrides,
  };
}

describe('useJobs hub_upload polling', () => {
  beforeEach(() => {
    useJobs.setState({ byId: {} });
    vi.useFakeTimers();
    mocks.api.mockReset();
    // SSE never delivers for hub_upload jobs (no runner stream); keep it pending.
    mocks.subscribeJob.mockReset().mockReturnValue(new Promise(() => {}));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('captures kind on an early tick before completion', async () => {
    mocks.api.mockResolvedValue(
      rec({ kind: 'hub_upload', status: 'running', stage: 'queued-for-hub' }),
    );

    useJobs.getState().start('job1');
    await vi.advanceTimersByTimeAsync(1500);

    expect(useJobs.getState().byId['job1'].kind).toBe('hub_upload');
  });

  it('carries kind atomically into the completion update', async () => {
    mocks.api.mockResolvedValue(
      rec({ kind: 'hub_upload', status: 'complete', stage: 'sent-to-hub', transcript_id: '' }),
    );

    useJobs.getState().start('job1');
    await vi.advanceTimersByTimeAsync(1500);

    const v = useJobs.getState().byId['job1'];
    expect(v.status).toBe('complete');
    expect(v.kind).toBe('hub_upload');
    expect(v.transcriptId).toBe('');
  });
});
