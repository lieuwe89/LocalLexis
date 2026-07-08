import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { LibraryScreen } from './LibraryScreen';
import type { TranscriptListItem } from '../api/types';

const mocks = vi.hoisted(() => ({
  libraryState: {
    items: [] as TranscriptListItem[],
    all: [] as TranscriptListItem[],
    refresh: vi.fn(),
    search: vi.fn(),
    remove: vi.fn(),
    searching: false,
  },
  transcriptsState: {
    load: vi.fn(),
    rename: vi.fn(),
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
  mocks.libraryState.remove.mockReset().mockResolvedValue(undefined);
  mocks.transcriptsState.load.mockReset().mockResolvedValue(undefined);
  mocks.transcriptsState.rename.mockReset().mockResolvedValue(undefined);
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

test('renames a row inline', async () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/x/rec.wav', title: null as unknown as string },
  ];
  mocks.libraryState.items = items;
  mocks.libraryState.all = items;

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  fireEvent.click(screen.getByLabelText('Rename rec.wav'));
  const input = screen.getByDisplayValue('rec.wav');
  fireEvent.change(input, { target: { value: 'Better name' } });
  fireEvent.keyDown(input, { key: 'Enter' });

  await new Promise(r => setTimeout(r, 0));

  expect(mocks.transcriptsState.rename).toHaveBeenCalledWith('a', 'Better name');
  expect(mocks.libraryState.refresh).toHaveBeenCalled();
});

test('delete asks confirmation then calls remove', async () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/x/rec.wav' },
  ];
  mocks.libraryState.items = items;
  mocks.libraryState.all = items;
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  fireEvent.click(screen.getByLabelText('Delete rec.wav'));
  await new Promise(r => setTimeout(r, 0));

  expect(confirmSpy).toHaveBeenCalled();
  const message = confirmSpy.mock.calls[0][0] as string;
  expect(message).toContain('Move');
  expect(message).toContain('rec.wav');
  expect(message).toContain('trash');
  expect(mocks.libraryState.remove).toHaveBeenCalledWith('a');

  confirmSpy.mockRestore();
});

test('delete aborted when confirm declined', async () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/x/rec.wav' },
  ];
  mocks.libraryState.items = items;
  mocks.libraryState.all = items;
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  fireEvent.click(screen.getByLabelText('Delete rec.wav'));
  await new Promise(r => setTimeout(r, 0));

  expect(confirmSpy).toHaveBeenCalled();
  expect(mocks.libraryState.remove).not.toHaveBeenCalled();

  confirmSpy.mockRestore();
});
