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
});
