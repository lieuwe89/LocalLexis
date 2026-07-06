import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getToken, setToken, clearToken, verifyToken } from './webAuth';

beforeEach(() => localStorage.clear());

describe('webAuth', () => {
  it('stores and clears the token', () => {
    setToken('abc');
    expect(getToken()).toBe('abc');
    clearToken();
    expect(getToken()).toBeNull();
  });

  it('verifyToken returns true on 200 and stores it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
    expect(await verifyToken('good')).toBe(true);
    expect(getToken()).toBe('good');
  });

  it('verifyToken returns false on 401 and does not store', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401 })));
    expect(await verifyToken('bad')).toBe(false);
    expect(getToken()).toBeNull();
  });
});
