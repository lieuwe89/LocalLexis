import { it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ActivityChip } from './ActivityChip';

vi.mock('../api/client', () => ({ api: vi.fn() }));
import { api } from '../api/client';

beforeEach(() => { vi.useFakeTimers(); vi.mocked(api).mockReset(); });
afterEach(() => { vi.useRealTimers(); });

const job = (over = {}) => ({
  id: 'j1', kind: 'transcribe', status: 'running', stage: 'asr',
  percent: 0.42, error: null, transcript_id: null,
  audio_path: '/x/standup.wav', paths: {}, ...over,
});

it('renders nothing when no active jobs', async () => {
  vi.mocked(api).mockResolvedValue([]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  expect(screen.queryByRole('status')).toBeNull();
});

it('shows job name and percent while active', async () => {
  vi.mocked(api).mockResolvedValue([job()]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  const chip = screen.getByRole('status');
  expect(chip.textContent).toContain('standup');
  expect(chip.textContent).toContain('42%');
  expect(vi.mocked(api)).toHaveBeenCalledWith('/jobs?active=true');
});

it('polls on an interval and clears when jobs finish', async () => {
  vi.mocked(api).mockResolvedValueOnce([job()]).mockResolvedValue([]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  expect(screen.getByRole('status')).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(3100));
  expect(screen.queryByRole('status')).toBeNull();
});

it('labels summarize jobs', async () => {
  vi.mocked(api).mockResolvedValue([job({ kind: 'summarize', audio_path: null, percent: 0 })]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  expect(screen.getByRole('status').textContent).toMatch(/Summarizing/);
});
