import { render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ProgressScreen } from './ProgressScreen';

type JobView = {
  id: string;
  kind?: string;
  status: 'pending' | 'running' | 'complete' | 'failed';
  stage: string;
  percent: number;
  lines: { speaker: string; ts: number; text: string }[];
  error: string | null;
  paths: Record<string, string>;
  transcriptId: string | null;
  startedAt: number;
};

const mocks = vi.hoisted(() => ({
  job: null as JobView | null,
  cancelTranscribe: vi.fn(),
}));

vi.mock('../stores/jobs', () => ({
  useJobs: (selector: (state: { byId: Record<string, JobView> }) => unknown) =>
    selector({ byId: mocks.job ? { [mocks.job.id]: mocks.job } : {} }),
  cancelTranscribe: mocks.cancelTranscribe,
}));

function makeJob(overrides: Partial<JobView>): JobView {
  return {
    id: 'job1',
    status: 'running',
    stage: '',
    percent: 0,
    lines: [],
    error: null,
    paths: {},
    transcriptId: null,
    startedAt: Date.now(),
    ...overrides,
  };
}

beforeEach(() => {
  mocks.job = null;
  mocks.cancelTranscribe.mockReset().mockResolvedValue(undefined);
});

test('hub_upload job renders the hub copy and no local stage chips', () => {
  mocks.job = makeJob({ kind: 'hub_upload', status: 'running', stage: 'queued-for-hub' });

  render(
    <ProgressScreen
      jobId="job1"
      audioPath="/Audio/clip.mp3"
      onComplete={vi.fn()}
      onCancelled={vi.fn()}
      onSentToHub={vi.fn()}
    />,
  );

  expect(screen.getByRole('heading', { name: /hub/i })).toBeInTheDocument();
  expect(screen.getByText(/library once it's done/i)).toBeInTheDocument();
  // Local stage chips must not render for hub uploads.
  expect(screen.queryByText('transcribe')).toBeNull();
  expect(screen.queryByText('diarize')).toBeNull();
});

test('completed hub_upload job calls onSentToHub and not onComplete', () => {
  mocks.job = makeJob({ kind: 'hub_upload', status: 'complete', transcriptId: '' });
  const onComplete = vi.fn();
  const onSentToHub = vi.fn();

  render(
    <ProgressScreen
      jobId="job1"
      audioPath="/Audio/clip.mp3"
      onComplete={onComplete}
      onCancelled={vi.fn()}
      onSentToHub={onSentToHub}
    />,
  );

  expect(onSentToHub).toHaveBeenCalledTimes(1);
  expect(onComplete).not.toHaveBeenCalled();
});

test('completed local job calls onComplete with the transcript id', () => {
  mocks.job = makeJob({ kind: 'transcribe', status: 'complete', transcriptId: 'tid-42' });
  const onComplete = vi.fn();
  const onSentToHub = vi.fn();

  render(
    <ProgressScreen
      jobId="job1"
      audioPath="/Audio/clip.mp3"
      onComplete={onComplete}
      onCancelled={vi.fn()}
      onSentToHub={onSentToHub}
    />,
  );

  expect(onComplete).toHaveBeenCalledWith('tid-42');
  expect(onSentToHub).not.toHaveBeenCalled();
});
