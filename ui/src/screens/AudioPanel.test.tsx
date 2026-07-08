import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AudioPanel } from './AudioPanel';

vi.mock('../api/client', () => ({ apiBlob: vi.fn() }));
import { apiBlob } from '../api/client';

beforeEach(() => {
  vi.mocked(apiBlob).mockReset();
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

it('loads audio blob and renders a player + download link', async () => {
  vi.mocked(apiBlob).mockResolvedValue(new Blob([new Uint8Array(4)], { type: 'audio/wav' }));
  render(<AudioPanel tid="t1" filename="rec.wav" />);
  await waitFor(() => expect(screen.getByLabelText('Transcript audio')).toBeInTheDocument());
  expect(apiBlob).toHaveBeenCalledWith('/transcripts/t1/audio');
  const dl = screen.getByLabelText('Download audio') as HTMLAnchorElement;
  expect(dl.getAttribute('download')).toBe('rec.wav');
  expect(dl.getAttribute('href')).toBe('blob:mock');
});

it('shows unavailable state on fetch failure', async () => {
  vi.mocked(apiBlob).mockRejectedValue(new Error('404 audio'));
  render(<AudioPanel tid="t1" filename="rec.wav" />);
  await waitFor(() => expect(screen.getByText(/audio unavailable/i)).toBeInTheDocument());
});
