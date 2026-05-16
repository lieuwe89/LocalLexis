import { render, screen, fireEvent } from '@testing-library/react';
import { CompleteScreen } from './CompleteScreen';
import { vi } from 'vitest';
import type { TranscriptDoc } from '../api/types';

vi.mock('@tauri-apps/plugin-shell', () => ({ open: vi.fn() }));

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
