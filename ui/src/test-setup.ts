import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Node 25 ships a global `localStorage` that is a no-op stub (requires
// --localstorage-file) and completely shadows jsdom's implementation. Replace
// it with a plain in-memory store so all tests get a working WebStorage API.
const _store: Record<string, string> = {};
const localStorageMock: Storage = {
  length: 0,
  getItem: (key: string) => _store[key] ?? null,
  setItem: (key: string, value: string) => { _store[key] = String(value); },
  removeItem: (key: string) => { delete _store[key]; },
  clear: () => { Object.keys(_store).forEach(k => delete _store[k]); },
  key: (index: number) => Object.keys(_store)[index] ?? null,
};
vi.stubGlobal('localStorage', localStorageMock);
