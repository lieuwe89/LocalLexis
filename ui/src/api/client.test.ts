import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Hoisted so the vi.mock factory below can reference it.
const { sidecarAuthMock, resetSidecarAuthMock } = vi.hoisted(() => ({
  sidecarAuthMock: vi.fn(),
  resetSidecarAuthMock: vi.fn(),
}));
vi.mock('@/platform', () => ({
  platform: {
    sidecarAuth: sidecarAuthMock,
    resetSidecarAuth: resetSidecarAuthMock,
  },
}));

function stubOk(body: unknown) {
  return { ok: true, status: 200, json: async () => body, text: async () => '' };
}

describe('api retry policy', () => {
  beforeEach(() => {
    // Reset client.ts's module-level sidecar cache between tests.
    vi.resetModules();
    sidecarAuthMock.mockReset();
    resetSidecarAuthMock.mockReset();
    sidecarAuthMock.mockResolvedValue({ url: 'http://hub.test', token: 'tok' });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('retries an idempotent GET after a network error', async () => {
    const counts: Record<string, number> = {};
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const u = String(input);
        counts[u] = (counts[u] ?? 0) + 1;
        if (u.endsWith('/health')) return stubOk({});
        if (counts[u] < 3) throw new TypeError('Failed to fetch');
        return stubOk({ ok: true });
      }),
    );

    const { api } = await import('./client');
    const res = await api('/transcripts'); // method defaults to GET
    expect(res).toEqual({ ok: true });
    expect(counts['http://hub.test/transcripts']).toBe(3);
  });

  it('does not retry a non-idempotent POST after a network error', async () => {
    const counts: Record<string, number> = {};
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const u = String(input);
        counts[u] = (counts[u] ?? 0) + 1;
        if (u.endsWith('/health')) return stubOk({});
        throw new TypeError('Failed to fetch');
      }),
    );

    const { api } = await import('./client');
    await expect(
      api('/jobs/transcribe', { method: 'POST' }),
    ).rejects.toThrow();
    expect(counts['http://hub.test/jobs/transcribe']).toBe(1);
  });

  it('fires the unauthorized handler on a 401 then throws', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}), text: async () => 'unauthorized' })),
    );

    const { api, setUnauthorizedHandler } = await import('./client');
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    await expect(api('/transcripts')).rejects.toThrow(/401/);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    setUnauthorizedHandler(null);
  });

  it('does not fire the unauthorized handler on a 500', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}), text: async () => 'boom' })),
    );

    const { api, setUnauthorizedHandler } = await import('./client');
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    await expect(api('/transcripts')).rejects.toThrow(/500/);
    expect(onUnauthorized).not.toHaveBeenCalled();
    setUnauthorizedHandler(null);
  });
});

describe('apiBlob', () => {
  beforeEach(() => {
    vi.resetModules();
    sidecarAuthMock.mockReset();
    resetSidecarAuthMock.mockReset();
    sidecarAuthMock.mockResolvedValue({ url: 'http://hub.test', token: 'tok' });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends a bearer token and returns the Blob from the response', async () => {
    const fetchMock = vi.fn(async (_input: unknown, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      blob: async () => new Blob([new Uint8Array([1, 2, 3])]),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiBlob } = await import('./client');
    const blob = await apiBlob('/transcripts/x/audio');
    expect(blob.size).toBe(3);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://hub.test/transcripts/x/audio');
    const headers = new Headers(init?.headers);
    expect(headers.get('Authorization')).toBe('Bearer tok');
  });

  it('rejects with the status code on a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404, text: async () => 'nope' })),
    );

    const { apiBlob } = await import('./client');
    await expect(apiBlob('/transcripts/x/audio')).rejects.toThrow(/404/);
  });
});
