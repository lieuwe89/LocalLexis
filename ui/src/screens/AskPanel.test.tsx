import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { AskPanel } from './AskPanel';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../api/client', () => ({ api: mocks.api }));

beforeEach(() => {
  mocks.api.mockReset();
});

describe('AskPanel', () => {
  it('submits a question, polls the job, renders answer and sources', async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({ job_id: 'j1' }) // POST /library/ask
      .mockResolvedValueOnce({
        id: 'j1', status: 'complete',
        result: {
          answer: 'Het antwoord is 42.',
          sources: [
            { transcript_id: 't1', segment_index: 3, start: 61 },
            { transcript_id: 't2', segment_index: 5, start: null },
          ],
        },
      });
    render(<AskPanel setRoute={() => {}} setTid={() => {}} pollMs={1} />);
    fireEvent.change(screen.getByPlaceholderText(/ask your library/i), { target: { value: 'wat is het antwoord?' } });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    await waitFor(() => expect(screen.getByText('Het antwoord is 42.')).toBeInTheDocument());
    // aria-label is the accessible name; visible text carries the [n] footnote
    // number matching the citation the LLM cites, plus the timestamp.
    const src = screen.getByRole('button', { name: /Jump to source at segment 3/ });
    expect(src).toHaveTextContent('[1] 1:01');
    const src2 = screen.getByRole('button', { name: /Jump to source at segment 5/ });
    expect(src2).toHaveTextContent('[2]');
    expect(src2).not.toHaveTextContent(':');
  });

  it('shows the job error on failure', async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({ job_id: 'j1' })
      .mockResolvedValueOnce({ id: 'j1', status: 'failed', error: 'no provider' });
    render(<AskPanel setRoute={() => {}} setTid={() => {}} pollMs={1} />);
    fireEvent.change(screen.getByPlaceholderText(/ask your library/i), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    await waitFor(() => expect(screen.getByText(/no provider/)).toBeInTheDocument());
  });
});
