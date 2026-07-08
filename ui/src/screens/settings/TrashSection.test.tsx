import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { TrashSection } from './TrashSection';
import type { TrashItem } from '../../api/types';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: mocks.api,
}));

const ITEM: TrashItem = {
  tid: 'a',
  title: 'Old',
  deleted_at: '2026-07-07T10:00:00Z',
  size_bytes: 1024,
};

beforeEach(() => {
  mocks.api.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

test('lists trash items with title and date', async () => {
  mocks.api.mockResolvedValue([ITEM]);

  render(<TrashSection />);

  expect(await screen.findByText('Old')).toBeInTheDocument();
  // formatted date string should appear somewhere (locale date/time format)
  expect(screen.getByText(/2026/)).toBeInTheDocument();
});

test('restore calls POST /trash/{tid}/restore and refreshes', async () => {
  mocks.api.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/trash' && (!init || !init.method)) return Promise.resolve([ITEM]);
    if (path === '/trash/a/restore') return Promise.resolve({ ok: true });
    return Promise.reject(new Error(`unexpected: ${path}`));
  });

  render(<TrashSection />);
  await screen.findByText('Old');

  fireEvent.click(screen.getByRole('button', { name: 'Restore' }));

  await waitFor(() =>
    expect(mocks.api).toHaveBeenCalledWith('/trash/a/restore', { method: 'POST' }),
  );
  // refetch after restore
  await waitFor(() => {
    const trashCalls = mocks.api.mock.calls.filter((c) => c[0] === '/trash' && !c[1]);
    expect(trashCalls.length).toBeGreaterThanOrEqual(2);
  });
});

test('empty trash confirms with cannot-be-undone wording then DELETE /trash', async () => {
  mocks.api.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/trash' && init?.method === 'DELETE') return Promise.resolve({ ok: true, purged: 1 });
    if (path === '/trash') return Promise.resolve([ITEM]);
    return Promise.reject(new Error(`unexpected: ${path}`));
  });
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(<TrashSection />);
  await screen.findByText('Old');

  fireEvent.click(screen.getByRole('button', { name: 'Empty trash' }));

  expect(confirmSpy).toHaveBeenCalled();
  expect(confirmSpy.mock.calls[0][0]).toMatch(/cannot be undone/);

  await waitFor(() =>
    expect(mocks.api).toHaveBeenCalledWith('/trash', { method: 'DELETE' }),
  );
});

test('restore conflict (409) surfaces an error message', async () => {
  mocks.api.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/trash' && (!init || !init.method)) return Promise.resolve([ITEM]);
    if (path === '/trash/a/restore') return Promise.reject(new Error('409 /trash/a/restore: conflict'));
    return Promise.reject(new Error(`unexpected: ${path}`));
  });

  render(<TrashSection />);
  await screen.findByText('Old');

  fireEvent.click(screen.getByRole('button', { name: 'Restore' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(/409/);
});
