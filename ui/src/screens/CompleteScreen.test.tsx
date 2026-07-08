import { render, screen, fireEvent } from '@testing-library/react';
import { CompleteScreen } from './CompleteScreen';
import { vi } from 'vitest';
import type { TranscriptDoc } from '../api/types';

vi.mock('@/platform', () => ({
  platform: {
    sidecarAuth: vi.fn(async () => ({ url: 'http://127.0.0.1:8010', token: 't' })),
    resetSidecarAuth: vi.fn(),
    appVersion: vi.fn(async () => '1.0.0'),
    openPath: vi.fn(async () => {}),
    openFileDialog: vi.fn(async () => null),
    audioDir: vi.fn(async () => '/audio'),
    pathJoin: vi.fn(async (...p: string[]) => p.join('/')),
    onFileDrop: vi.fn(async () => () => {}),
    checkForUpdates: vi.fn(async () => {}),
    relabelTranscript: vi.fn(async () => {}),
  },
}));

const doc: TranscriptDoc = {
  version: 1,
  audio_path: '/Audio/meet.mp3',
  duration_seconds: 60,
  language: 'en',
  speakers: { SPEAKER_00: 'Alice', SPEAKER_01: 'Bob' },
  segments: [
    { start: 0, end: 5, speaker: 'SPEAKER_00', text: 'hi' },
    { start: 5, end: 10, speaker: 'SPEAKER_01', text: 'hey' },
  ],
  models: { asr: 'faster-whisper:large-v3' },
  created_at: '2026-05-15T10:00:00Z',
};

const segDoc: TranscriptDoc = {
  ...doc,
  segments: [
    { start: 0, end: 5, speaker: 'SPEAKER_00', text: 'hello' },
    { start: 5, end: 10, speaker: 'SPEAKER_01', text: 'world' },
  ],
};

test('renders all segments with speaker labels', () => {
  render(<CompleteScreen doc={doc} onRelabel={async () => {}} />);
  expect(screen.getByText('hi')).toBeInTheDocument();
  expect(screen.getByText('hey')).toBeInTheDocument();
  // both labels exist somewhere (speaker label + relabel input)
  expect(screen.getAllByText('Alice').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Bob').length).toBeGreaterThan(0);
});

test('editing a relabel input enables Apply and calls onRelabel with changed map', async () => {
  const onRelabel = vi.fn().mockResolvedValue(undefined);
  render(<CompleteScreen doc={doc} onRelabel={onRelabel} />);
  const aliceInput = screen.getAllByDisplayValue('Alice')[0] as HTMLInputElement;
  fireEvent.change(aliceInput, { target: { value: 'Carol' } });
  const apply = screen.getByText('Apply');
  fireEvent.click(apply);
  // Wait a tick for the async handler
  await new Promise(r => setTimeout(r, 0));
  expect(onRelabel).toHaveBeenCalledWith({ SPEAKER_00: 'Carol' });
});

test('title edit calls onRename', async () => {
  const onRename = vi.fn().mockResolvedValue(undefined);
  render(<CompleteScreen doc={doc} onRelabel={async () => {}} onRename={onRename} />);

  fireEvent.click(screen.getByLabelText('Rename transcript'));
  const input = screen.getByDisplayValue('meet');
  fireEvent.change(input, { target: { value: '' } });
  fireEvent.change(input, { target: { value: 'New title' } });
  fireEvent.keyDown(input, { key: 'Enter' });

  await new Promise(r => setTimeout(r, 0));

  expect(onRename).toHaveBeenCalledWith('New title');
});

test('shows doc.title over filename when set', () => {
  const titledDoc = { ...doc, title: 'Custom' };
  render(<CompleteScreen doc={titledDoc} onRelabel={async () => {}} />);
  expect(screen.getByText('Custom')).toBeInTheDocument();
  expect(screen.queryByText('meet')).toBeNull();
});

test('delete button confirms then calls onDelete', async () => {
  const onDelete = vi.fn().mockResolvedValue(undefined);
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<CompleteScreen doc={doc} onRelabel={async () => {}} onDelete={onDelete} />);

  fireEvent.click(screen.getByLabelText('Delete transcript'));
  await new Promise(r => setTimeout(r, 0));

  expect(confirmSpy).toHaveBeenCalled();
  expect(onDelete).toHaveBeenCalled();

  confirmSpy.mockRestore();
});

test('editing a segment line calls onEditSegment with index and new text', async () => {
  const onEditSegment = vi.fn().mockResolvedValue(undefined);
  render(<CompleteScreen doc={segDoc} onRelabel={async () => {}} onEditSegment={onEditSegment} />);

  fireEvent.click(screen.getByLabelText('Edit line 2'));
  const textarea = screen.getByDisplayValue('world') as HTMLTextAreaElement;
  fireEvent.change(textarea, { target: { value: 'corrected text' } });
  fireEvent.keyDown(textarea, { key: 'Enter' });

  await new Promise(r => setTimeout(r, 0));

  expect(onEditSegment).toHaveBeenCalledWith(1, 'corrected text');
});

test('escape cancels segment edit without calling onEditSegment', async () => {
  const onEditSegment = vi.fn().mockResolvedValue(undefined);
  render(<CompleteScreen doc={segDoc} onRelabel={async () => {}} onEditSegment={onEditSegment} />);

  fireEvent.click(screen.getByLabelText('Edit line 2'));
  const textarea = screen.getByDisplayValue('world') as HTMLTextAreaElement;
  fireEvent.change(textarea, { target: { value: 'corrected text' } });
  fireEvent.keyDown(textarea, { key: 'Escape' });

  await new Promise(r => setTimeout(r, 0));

  expect(onEditSegment).not.toHaveBeenCalled();
  expect(screen.getByText('world')).toBeInTheDocument();
  expect(screen.queryByDisplayValue('corrected text')).toBeNull();
});

test('no edit buttons when onEditSegment is not provided', () => {
  render(<CompleteScreen doc={segDoc} onRelabel={async () => {}} />);
  expect(screen.queryByLabelText('Edit line 1')).toBeNull();
  expect(screen.queryByLabelText('Edit line 2')).toBeNull();
});
