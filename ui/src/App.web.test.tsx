import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AppWeb from './App.web';

vi.mock('./lib/webAuth', () => ({
  getToken: vi.fn(() => null),
  clearToken: vi.fn(),
  verifyToken: vi.fn(),
}));

// App.web eagerly imports CompleteScreen, which imports '@/platform'. Under
// plain `vitest` (non `--mode hub`), that alias resolves to platform/tauri.ts,
// which pulls in real @tauri-apps/* packages at module-eval time. Mock it the
// same way CompleteScreen.test.tsx does so importing App.web is safe here —
// this test only asserts the (unauthed) login screen renders, so none of
// these calls actually fire.
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

describe('App.web', () => {
  it('renders the login screen when no token is stored', () => {
    render(<AppWeb />);
    expect(screen.getByLabelText(/admin token/i)).toBeInTheDocument();
  });
});
