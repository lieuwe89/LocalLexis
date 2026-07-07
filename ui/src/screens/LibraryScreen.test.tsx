import { render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { LibraryScreen } from './LibraryScreen';
import type { TranscriptListItem } from '../api/types';

const mocks = vi.hoisted(() => ({
  libraryState: {
    items: [] as TranscriptListItem[],
    all: [] as TranscriptListItem[],
    refresh: vi.fn(),
    search: vi.fn(),
    searching: false,
  },
  transcriptsState: {
    load: vi.fn(),
  },
}));

vi.mock('../stores/library', () => ({
  useLibrary: (selector: (state: typeof mocks.libraryState) => unknown) =>
    selector(mocks.libraryState),
}));

vi.mock('../stores/transcripts', () => ({
  useTranscripts: (selector: (state: typeof mocks.transcriptsState) => unknown) =>
    selector(mocks.transcriptsState),
}));

beforeEach(() => {
  mocks.libraryState.refresh.mockReset().mockResolvedValue(undefined);
  mocks.libraryState.search.mockReset().mockResolvedValue(undefined);
  mocks.transcriptsState.load.mockReset().mockResolvedValue(undefined);
});

test('shows the hub badge only on rows whose origin is hub', () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/Audio/from-hub.mp3', origin: 'hub' },
    { id: 'b', path: '/x/b.json', audio_path: '/Audio/local.mp3', origin: 'local' },
  ];
  mocks.libraryState.items = items;
  mocks.libraryState.all = items;

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  const badges = screen.getAllByText('hub');
  expect(badges).toHaveLength(1);

  const hubRow = screen.getByText('from-hub.mp3').closest('.lib-row')!;
  expect(hubRow.querySelector('.origin-badge')).not.toBeNull();

  const localRow = screen.getByText('local.mp3').closest('.lib-row')!;
  expect(localRow.querySelector('.origin-badge')).toBeNull();
});

test('renders both date and time for created_at', () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/Audio/a.mp3', created_at: '2026-07-07T14:32:00+00:00' },
  ];
  mocks.libraryState.items = items;
  mocks.libraryState.all = items;

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  const expected = new Date('2026-07-07T14:32:00+00:00').toLocaleString([], {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
  expect(screen.getByText(expected)).toBeTruthy();
});

test('prefers title over filename for the row name', () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/Audio/original-name.mp3', title: 'Renamed Recording' },
  ];
  mocks.libraryState.items = items;
  mocks.libraryState.all = items;

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  expect(screen.getByText('Renamed Recording')).toBeTruthy();
  expect(screen.queryByText('original-name.mp3')).toBeNull();
});
