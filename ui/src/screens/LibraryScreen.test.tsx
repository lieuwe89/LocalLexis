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
