import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../api/client', () => ({ api: mocks.api }));

import { useLibrary } from './library';

describe('useLibrary search params', () => {
  beforeEach(() => {
    mocks.api.mockReset();
    mocks.api.mockResolvedValue([]);
    useLibrary.setState({ items: [], all: [], query: '', searching: false, fuzzy: false, sort: 'relevance' });
  });

  it('passes fuzzy and sort as query params', async () => {
    useLibrary.setState({ fuzzy: true, sort: 'date' });
    await useLibrary.getState().search('hello world');
    expect(mocks.api).toHaveBeenCalledWith('/transcripts?q=hello%20world&fuzzy=1&sort=date');
  });

  it('omits default params', async () => {
    await useLibrary.getState().search('hello');
    expect(mocks.api).toHaveBeenCalledWith('/transcripts?q=hello');
  });

  it('setFuzzy re-runs the active search', async () => {
    await useLibrary.getState().search('hello');
    mocks.api.mockClear();
    useLibrary.getState().setFuzzy(true);
    await vi.waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/transcripts?q=hello&fuzzy=1'));
  });

  it('setSort with no active query does not call the api', () => {
    useLibrary.getState().setSort('date');
    expect(mocks.api).not.toHaveBeenCalled();
  });

  it('setSemantic re-runs the current search with semantic=1', async () => {
    await useLibrary.getState().search('begroeting');
    mocks.api.mockClear();
    useLibrary.getState().setSemantic(true);
    await vi.waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/transcripts?q=begroeting&semantic=1'));
  });

  it('search omits semantic param when toggle is off', async () => {
    useLibrary.setState({ semantic: false });
    await useLibrary.getState().search('hallo');
    expect(mocks.api).toHaveBeenCalledWith('/transcripts?q=hallo');
  });

  it('a stale response cannot overwrite a newer re-search with the same query text', async () => {
    // Two requests share the query text 'hello' (fuzzy toggle re-searches),
    // so only a request-generation guard can tell them apart.
    const staleRows = [{ id: 'stale', path: 'stale.json' }];
    const freshRows = [{ id: 'fresh', path: 'fresh.json' }];
    const deferred: { resolve: (rows: unknown) => void }[] = [];
    mocks.api.mockImplementation(
      () => new Promise(resolve => deferred.push({ resolve })),
    );

    const first = useLibrary.getState().search('hello'); // fuzzy=false
    useLibrary.getState().setFuzzy(true); // re-search, same text, fuzzy=1
    await vi.waitFor(() => expect(deferred).toHaveLength(2));

    deferred[1].resolve(freshRows); // newer request resolves first...
    await vi.waitFor(() =>
      expect(useLibrary.getState().items).toEqual(freshRows),
    );

    deferred[0].resolve(staleRows); // ...then the stale one arrives late
    await first;
    expect(useLibrary.getState().items).toEqual(freshRows);
    expect(useLibrary.getState().searching).toBe(false);
  });

  it('sets searchError when the api call rejects, and clears it on the next successful search', async () => {
    mocks.api.mockRejectedValueOnce(new Error('503 /transcripts: embedding model unavailable'));
    await useLibrary.getState().search('x');
    expect(useLibrary.getState().searchError).toBe('503 /transcripts: embedding model unavailable');
    expect(useLibrary.getState().searching).toBe(false);

    mocks.api.mockResolvedValueOnce([]);
    await useLibrary.getState().search('y');
    expect(useLibrary.getState().searchError).toBeNull();
  });
});
