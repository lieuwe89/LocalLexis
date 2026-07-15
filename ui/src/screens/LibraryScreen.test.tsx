import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, test, vi } from 'vitest';
import { LibraryScreen } from './LibraryScreen';
import { useLibrary } from '../stores/library';
import { useTranscripts } from '../stores/transcripts';
import { usePendingFind } from '../stores/pendingFind';
import type { TranscriptListItem } from '../api/types';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../api/client', () => ({ api: mocks.api }));

// Real stores are used (not mocked as a module) so the new tests can assert
// against `useLibrary.getState()` / `usePendingFind.getState()` directly.
// `refresh` (mount effect) and `search` (200ms debounce effect) are spied
// to no-ops in every test so they can't race assertions or clobber
// manually-seeded `items`/`all`; individual tests re-spy `rename`/`remove`
// where they want to assert call args instead of exercising the real
// api-backed implementation.
let refreshSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  mocks.api.mockReset().mockResolvedValue([]);
  useLibrary.setState({
    items: [], all: [], query: '', searching: false, fuzzy: false, sort: 'relevance',
  });
  useTranscripts.setState({ byId: {} });
  usePendingFind.setState({ pending: null });
  refreshSpy = vi.spyOn(useLibrary.getState(), 'refresh').mockResolvedValue(undefined);
  vi.spyOn(useLibrary.getState(), 'search').mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

test('shows the hub badge only on rows whose origin is hub', () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/Audio/from-hub.mp3', origin: 'hub' },
    { id: 'b', path: '/x/b.json', audio_path: '/Audio/local.mp3', origin: 'local' },
  ];
  useLibrary.setState({ items, all: items });

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
  useLibrary.setState({ items, all: items });

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
  useLibrary.setState({ items, all: items });

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  expect(screen.getByText('Renamed Recording')).toBeTruthy();
  expect(screen.queryByText('original-name.mp3')).toBeNull();
});

test('renames a row inline', async () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/x/rec.wav', title: null as unknown as string },
  ];
  useLibrary.setState({ items, all: items });
  const renameSpy = vi.spyOn(useTranscripts.getState(), 'rename').mockResolvedValue(undefined);

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  fireEvent.click(screen.getByLabelText('Rename rec.wav'));
  const input = screen.getByDisplayValue('rec.wav');
  fireEvent.change(input, { target: { value: 'Better name' } });
  fireEvent.keyDown(input, { key: 'Enter' });

  await new Promise(r => setTimeout(r, 0));

  expect(renameSpy).toHaveBeenCalledWith('a', 'Better name');
  expect(refreshSpy).toHaveBeenCalled();
});

test('delete asks confirmation then calls remove', async () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/x/rec.wav' },
  ];
  useLibrary.setState({ items, all: items });
  const removeSpy = vi.spyOn(useLibrary.getState(), 'remove').mockResolvedValue(undefined);
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  fireEvent.click(screen.getByLabelText('Delete rec.wav'));
  await new Promise(r => setTimeout(r, 0));

  expect(confirmSpy).toHaveBeenCalled();
  const message = confirmSpy.mock.calls[0][0] as string;
  expect(message).toContain('Move');
  expect(message).toContain('rec.wav');
  expect(message).toContain('trash');
  expect(removeSpy).toHaveBeenCalledWith('a');

  confirmSpy.mockRestore();
});

test('delete aborted when confirm declined', async () => {
  const items: TranscriptListItem[] = [
    { id: 'a', path: '/x/a.json', audio_path: '/x/rec.wav' },
  ];
  useLibrary.setState({ items, all: items });
  const removeSpy = vi.spyOn(useLibrary.getState(), 'remove').mockResolvedValue(undefined);
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

  render(<LibraryScreen setRoute={vi.fn()} setTid={vi.fn()} />);

  fireEvent.click(screen.getByLabelText('Delete rec.wav'));
  await new Promise(r => setTimeout(r, 0));

  expect(confirmSpy).toHaveBeenCalled();
  expect(removeSpy).not.toHaveBeenCalled();

  confirmSpy.mockRestore();
});

const hitItem = {
  id: 't1',
  path: '/lib/t1.json',
  audio_path: '/lib/meeting.mp3',
  duration_seconds: 60,
  speakers: 1,
  created_at: '2026-07-01T10:00:00Z',
  total_hits: 5,
  hits: [
    { segment_index: 2, start: 12, score: -2.0,
      snippet_parts: [{ text: 'about the ', match: false }, { text: 'budget', match: true }] },
    { segment_index: 7, start: 90, score: -1.5,
      snippet_parts: [{ text: 'budget', match: true }, { text: ' again', match: false }] },
    { segment_index: 9, start: 120, score: -1.2,
      snippet_parts: [{ text: 'more ', match: false }, { text: 'budget', match: true }] },
    { segment_index: 11, start: 150, score: -1.0,
      snippet_parts: [{ text: 'final ', match: false }, { text: 'budget', match: true }] },
  ],
};

describe('library segment hits', () => {
  it('renders up to 3 hit lines with a +N more expander', () => {
    useLibrary.setState({ items: [hitItem], all: [hitItem], query: 'budget' });
    render(<LibraryScreen setRoute={() => {}} setTid={() => {}} />);
    expect(screen.getAllByText('budget', { selector: 'mark' })).toHaveLength(3);
    const more = screen.getByRole('button', { name: '+2 more' }); // total_hits 5 − 3 shown
    fireEvent.click(more);
    expect(screen.getAllByText('budget', { selector: 'mark' })).toHaveLength(4);
  });

  it('clicking a hit sets pendingFind and opens the transcript', async () => {
    const setRoute = vi.fn();
    const setTid = vi.fn();
    useLibrary.setState({ items: [hitItem], all: [hitItem], query: 'budget', fuzzy: true });
    render(<LibraryScreen setRoute={setRoute} setTid={setTid} />);
    fireEvent.change(screen.getByPlaceholderText(/Search transcripts/), { target: { value: 'budget' } });
    fireEvent.click(screen.getAllByRole('button', { name: /Jump to match/ })[0]);
    await waitFor(() => expect(setTid).toHaveBeenCalledWith('t1'));
    expect(setRoute).toHaveBeenCalledWith('complete');
    expect(usePendingFind.getState().pending).toMatchObject({
      tid: 't1', query: 'budget', fuzzy: true, segmentIndex: 2,
    });
  });

  it('fuzzy toggle is wired to the store', () => {
    useLibrary.setState({ items: [], all: [], fuzzy: false });
    render(<LibraryScreen setRoute={() => {}} setTid={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Fuzzy matching' }));
    expect(useLibrary.getState().fuzzy).toBe(true);
  });
});
