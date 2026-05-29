import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { SettingsScreen } from './SettingsScreen';
import type { ConfigDto } from '../api/types';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  invoke: vi.fn(),
  resetSidecarInfo: vi.fn(),
  configState: {
    cfg: {
      backend: 'auto',
      asr_model: 'base',
      hf_token_set: true,
      model_cache_dir: '/Users/test/.cache/locallexis',
      default_out_dir: null,
      watch: {
        recursive: true,
        debounce_seconds: 2,
        extensions: ['wav', 'mp3'],
      },
    } satisfies ConfigDto,
    load: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: mocks.invoke,
}));

vi.mock('../api/client', () => ({
  api: mocks.api,
  resetSidecarInfo: mocks.resetSidecarInfo,
}));

vi.mock('../stores/config', () => ({
  useConfig: (selector: (state: typeof mocks.configState) => unknown) =>
    selector(mocks.configState),
}));

beforeEach(() => {
  mocks.api.mockReset();
  mocks.invoke.mockReset();
  mocks.resetSidecarInfo.mockReset();
  mocks.configState.load.mockReset();
  mocks.configState.patch.mockReset();
  mocks.configState.load.mockResolvedValue(undefined);
  mocks.configState.patch.mockResolvedValue(undefined);
  mocks.invoke.mockImplementation((command: string) => {
    if (command === 'get_hub_state') {
      return Promise.resolve({ enabled: false, port: 8765 });
    }
    return Promise.reject(new Error(`unexpected invoke: ${command}`));
  });
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([
        { name: 'base', status: 'bundled', size_mb: 140 },
      ]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });
});

test('shows Bluetooth recorder scanning when hub mode is off', async () => {
  render(<SettingsScreen />);

  expect(await screen.findByText('Hub mode')).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Scan for Bluetooth recorders' }),
  ).toBeInTheDocument();
});

test('renders a scannable QR after minting a pairing code', async () => {
  mocks.invoke.mockImplementation((command: string) => {
    if (command === 'get_hub_state') {
      return Promise.resolve({ enabled: true, port: 8765 });
    }
    return Promise.reject(new Error(`unexpected invoke: ${command}`));
  });
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/pair/tokens') {
      return Promise.resolve({
        token: 'tok_abc',
        expires_at: 0,
        workspace_id: 'ws_a',
        ttl_seconds: 300,
      });
    }
    if (path === '/hub/info') {
      return Promise.resolve({
        lan_addresses: ['192.168.1.50'],
        tls_enabled: true,
        tls_spki_b64: 'PIN==',
      });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  render(<SettingsScreen />);

  const mint = await screen.findByRole('button', { name: 'Generate pairing code' });
  fireEvent.click(mint);

  expect(await screen.findByLabelText('Pairing QR code')).toBeInTheDocument();
});
