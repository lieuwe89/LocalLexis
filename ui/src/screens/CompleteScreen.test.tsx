import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CompleteScreen } from './CompleteScreen';
import { vi } from 'vitest';
import type { TranscriptDoc } from '../api/types';
import { usePendingFind } from '../stores/pendingFind';

Element.prototype.scrollIntoView = vi.fn();

const mockSeek = vi.fn();
vi.mock('./AudioPanel', () => ({
  AudioPanel: ({ onReady }: { onReady?: (seek: (secs: number) => void) => void }) => {
    onReady?.(mockSeek);
    return null;
  },
}));

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

const findDoc: TranscriptDoc = {
  ...doc,
  segments: [
    { start: 0, end: 5, speaker: 'SPEAKER_00', text: 'hello world' },
    { start: 5, end: 10, speaker: 'SPEAKER_01', text: 'the world turns' },
    { start: 10, end: 15, speaker: 'SPEAKER_00', text: 'goodbye' },
  ],
};

test('search highlights matches and shows the count', () => {
  render(<CompleteScreen doc={findDoc} onRelabel={async () => {}} />);
  const input = screen.getByLabelText('Search in transcript');
  fireEvent.change(input, { target: { value: 'world' } });

  const marks = document.querySelectorAll('mark');
  expect(marks.length).toBe(2);
  marks.forEach(m => expect(m.textContent).toBe('world'));

  expect(screen.getByText('1 / 2')).toBeInTheDocument();
});

test('next/prev cycle wraps around matches', () => {
  render(<CompleteScreen doc={findDoc} onRelabel={async () => {}} />);
  const input = screen.getByLabelText('Search in transcript');
  fireEvent.change(input, { target: { value: 'world' } });

  expect(screen.getByText('1 / 2')).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText('Next match'));
  expect(screen.getByText('2 / 2')).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText('Next match'));
  expect(screen.getByText('1 / 2')).toBeInTheDocument();
});

test('no matches shows 0 / 0 and no marks', () => {
  render(<CompleteScreen doc={findDoc} onRelabel={async () => {}} />);
  const input = screen.getByLabelText('Search in transcript');
  fireEvent.change(input, { target: { value: 'zzzznotfound' } });

  expect(screen.getByText('0 / 0')).toBeInTheDocument();
  expect(document.querySelectorAll('mark').length).toBe(0);
});

test('clicking a segment timestamp seeks the audio panel to that segment start', () => {
  mockSeek.mockClear();
  const { container } = render(<CompleteScreen doc={doc} onRelabel={async () => {}} tid="t1" />);

  const tsCells = container.querySelectorAll('.ts-seek');
  expect(tsCells.length).toBeGreaterThan(0);
  expect(tsCells[0].getAttribute('role')).toBe('button');
  fireEvent.click(tsCells[0]);

  expect(mockSeek).toHaveBeenCalledWith(doc.segments[0].start);
});

test('renders stored summary and meta', () => {
  const summarizedDoc: TranscriptDoc = {
    ...doc,
    summary: '## Key points\n- ship',
    summary_meta: { provider: 'lemonade', model: 'Qwen3-30B', created_at: '2026-07-07T10:00:00Z' },
  };
  render(<CompleteScreen doc={summarizedDoc} onRelabel={async () => {}} />);

  expect(screen.getByText(/Key points/)).toBeInTheDocument();
  expect(screen.getByText(/ship/)).toBeInTheDocument();
  expect(screen.getByText(/Qwen3-30B/)).toBeInTheDocument();
});

test('summarize button triggers onSummarize and shows busy state', async () => {
  let resolveFn: () => void = () => {};
  const onSummarize = vi.fn(() => new Promise<void>(resolve => { resolveFn = resolve; }));
  render(<CompleteScreen doc={doc} onRelabel={async () => {}} onSummarize={onSummarize} />);

  const btn = screen.getByLabelText('Summarize transcript');
  // Carries a visible text label (not just an icon + hover tooltip).
  expect(btn.textContent).toContain('Summarize');
  fireEvent.click(btn);

  expect(onSummarize).toHaveBeenCalled();
  await new Promise(r => setTimeout(r, 0));
  expect(btn).toBeDisabled();
  expect(btn.textContent).toContain('Summarizing');

  resolveFn();
  await new Promise(r => setTimeout(r, 0));
});

test('summarize error is shown inline as an alert', async () => {
  const onSummarize = vi.fn().mockRejectedValue(new Error('cannot reach provider'));
  render(<CompleteScreen doc={doc} onRelabel={async () => {}} onSummarize={onSummarize} />);

  fireEvent.click(screen.getByLabelText('Summarize transcript'));
  await new Promise(r => setTimeout(r, 0));

  expect(screen.getByRole('alert')).toHaveTextContent('cannot reach provider');
});

const inTranscriptFindDoc = {
  version: 1,
  audio_path: '/x/a.mp3',
  duration_seconds: 10,
  language: 'en',
  speakers: { SPEAKER_00: 'Alice' },
  segments: [
    { start: 0, end: 2, speaker: 'SPEAKER_00', text: 'the cat sat on the cat mat' },
    { start: 2, end: 4, speaker: 'SPEAKER_00', text: 'nothing here' },
    { start: 4, end: 6, speaker: 'SPEAKER_00', text: 'Kaitlyn presented the plan' },
  ],
  models: {},
  created_at: '2026-07-15T10:00:00Z',
} as TranscriptDoc;

describe('in-transcript find', () => {
  beforeEach(() => {
    usePendingFind.setState({ pending: null });
    (Element.prototype.scrollIntoView as ReturnType<typeof vi.fn>).mockClear();
  });

  it('counts occurrences, not segments', async () => {
    render(<CompleteScreen doc={inTranscriptFindDoc} onRelabel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Search in transcript'), { target: { value: 'cat' } });
    expect(await screen.findByText('1 / 2')).toBeInTheDocument();
  });

  it('fuzzy toggle finds phonetic matches and marks them', async () => {
    render(<CompleteScreen doc={inTranscriptFindDoc} onRelabel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Search in transcript'), { target: { value: 'Catelin' } });
    expect(await screen.findByText('0 / 0')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Fuzzy matching'));
    expect(await screen.findByText('1 / 1')).toBeInTheDocument();
    expect(screen.getByText('Kaitlyn').tagName).toBe('MARK');
  });

  it('marks the current occurrence with the current class', async () => {
    render(<CompleteScreen doc={inTranscriptFindDoc} onRelabel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Search in transcript'), { target: { value: 'cat' } });
    await screen.findByText('1 / 2');
    const marks = screen.getAllByText('cat', { selector: 'mark' });
    expect(marks).toHaveLength(2);
    expect(marks[0].className).toContain('current');
    fireEvent.click(screen.getByLabelText('Next match'));
    expect(await screen.findByText('2 / 2')).toBeInTheDocument();
    expect(screen.getAllByText('cat', { selector: 'mark' })[1].className).toContain('current');
  });

  it('consumes pendingFind: pre-fills query and jumps to the segment', async () => {
    usePendingFind.getState().set({ tid: 'T1', query: 'Kaitlyn', fuzzy: false, segmentIndex: 2 });
    render(<CompleteScreen doc={inTranscriptFindDoc} tid="T1" onRelabel={() => {}} />);
    const input = screen.getByLabelText('Search in transcript') as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe('Kaitlyn'));
    expect(await screen.findByText('1 / 1')).toBeInTheDocument();
    expect(usePendingFind.getState().pending).toBeNull();
  });

  it('pendingFind with no client match still scrolls to the clicked segment', async () => {
    // Server search (porter stemming / phonetic codes) can match where the
    // client engine does not — the segment jump must still happen.
    usePendingFind.getState().set({ tid: 'T1', query: 'zzz-not-in-doc', fuzzy: false, segmentIndex: 2 });
    render(<CompleteScreen doc={inTranscriptFindDoc} tid="T1" onRelabel={() => {}} />);
    const input = screen.getByLabelText('Search in transcript') as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe('zzz-not-in-doc'));
    expect(await screen.findByText('0 / 0')).toBeInTheDocument();
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
    expect(usePendingFind.getState().pending).toBeNull();
  });

  it('escape clears the query', async () => {
    render(<CompleteScreen doc={inTranscriptFindDoc} onRelabel={() => {}} />);
    const input = screen.getByLabelText('Search in transcript') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'cat' } });
    await screen.findByText('1 / 2');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input.value).toBe('');
  });
});
