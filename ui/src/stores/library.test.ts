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
});
