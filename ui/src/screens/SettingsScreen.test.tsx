import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
      summarize: {
        provider: 'lemonade',
        base_url: '',
        model: '',
        api_key_set: false,
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
    if (path === '/client/hub') {
      return Promise.resolve({ joined: false });
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
    if (path === '/client/hub') {
      return Promise.resolve({ joined: false });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  render(<SettingsScreen />);

  const mint = await screen.findByRole('button', { name: 'Generate pairing code' });
  fireEvent.click(mint);

  expect(await screen.findByLabelText('Pairing QR code')).toBeInTheDocument();
});

test('joins a hub from the pairing code + device name inputs', async () => {
  const joined = {
    joined: true,
    hub_url: 'https://hub.example',
    device_name: 'lieuwe-laptop',
  };
  let hasJoined = false;
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve(hasJoined ? joined : { joined: false });
    }
    if (path === '/client/hub/join') {
      hasJoined = true;
      return Promise.resolve(joined);
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  render(<SettingsScreen />);

  expect(await screen.findByText('Join a hub')).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('pairing code'), {
    target: { value: 'UGFpcg==' },
  });
  fireEvent.change(screen.getByLabelText('device name'), {
    target: { value: 'lieuwe-laptop' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Join' }));

  expect(await screen.findByText(/Connected to/)).toBeInTheDocument();
  expect(mocks.api).toHaveBeenCalledWith('/client/hub/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pairing_string: 'UGFpcg==',
      device_name: 'lieuwe-laptop',
    }),
  });
});

function mockJoined(migrated_at: number | null = null) {
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at,
      });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });
}

test('hides the migrate-to-hub card when not joined', async () => {
  render(<SettingsScreen />);

  await screen.findByText('Join a hub');
  expect(screen.queryByText('Migrate library to hub')).not.toBeInTheDocument();
});

test('shows the migrate button when joined and not yet migrated', async () => {
  mockJoined(null);
  render(<SettingsScreen />);

  expect(
    await screen.findByRole('button', { name: 'Migrate library to hub' }),
  ).toBeInTheDocument();
});

test('shows the migrated state instead of the button once migrated_at is set', async () => {
  mockJoined(1700000000);
  render(<SettingsScreen />);

  expect(await screen.findByText(/Library migrated/)).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Migrate library to hub' }),
  ).not.toBeInTheDocument();
});

test('runs a migration and reports the migrated count on completion', async () => {
  let polls = 0;
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at: null,
      });
    }
    if (path === '/client/hub/migrate') {
      return Promise.resolve({ job_id: 'job1' });
    }
    if (path === '/jobs/job1') {
      polls += 1;
      if (polls < 2) {
        return Promise.resolve({
          id: 'job1', kind: 'migrate', status: 'running', stage: 'migrate',
          percent: 0, error: null, transcript_id: null, audio_path: null, paths: {},
        });
      }
      return Promise.resolve({
        id: 'job1', kind: 'migrate', status: 'complete', stage: 'migrate',
        percent: 100, error: null, transcript_id: null, audio_path: null, paths: {},
        result: { migrated: ['a', 'b'], failed: [] },
      });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<SettingsScreen pollMs={1} />);

  const btn = await screen.findByRole('button', { name: 'Migrate library to hub' });
  fireEvent.click(btn);

  expect(confirmSpy).toHaveBeenCalled();
  expect(confirmSpy.mock.calls[0][0]).toContain('trash');
  expect(await screen.findByText('Migrating…')).toBeInTheDocument();
  expect(await screen.findByText('2 transcripts migrated')).toBeInTheDocument();
  expect(mocks.api).toHaveBeenCalledWith('/client/hub/migrate', { method: 'POST' });
  confirmSpy.mockRestore();
});

test('does not start a migration when the confirm is declined', async () => {
  mockJoined(null);
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
  render(<SettingsScreen />);

  fireEvent.click(await screen.findByRole('button', { name: 'Migrate library to hub' }));
  await new Promise(r => setTimeout(r, 0));

  expect(confirmSpy).toHaveBeenCalled();
  expect(mocks.api).not.toHaveBeenCalledWith('/client/hub/migrate', { method: 'POST' });
  confirmSpy.mockRestore();
});

test('shows a wrapped list of failures after migration completes', async () => {
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at: null,
      });
    }
    if (path === '/client/hub/migrate') {
      return Promise.resolve({ job_id: 'job1' });
    }
    if (path === '/jobs/job1') {
      return Promise.resolve({
        id: 'job1', kind: 'migrate', status: 'complete', stage: 'migrate',
        percent: 100, error: null, transcript_id: null, audio_path: null, paths: {},
        result: { migrated: ['a'], failed: [{ id: 'tid-x', error: 'upload timed out' }] },
      });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<SettingsScreen pollMs={1} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Migrate library to hub' }));

  expect(await screen.findByText(/tid-x/)).toBeInTheDocument();
  expect(screen.getByText(/upload timed out/)).toBeInTheDocument();
  confirmSpy.mockRestore();
});

test('shows the offline-capture control with the current mode selected when joined', async () => {
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at: null,
        offline_capture: 'local',
      });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  render(<SettingsScreen />);

  const select = await screen.findByLabelText('When offline');
  expect(select).toHaveValue('local');
});

test('changing the offline-capture mode POSTs and refreshes hub status', async () => {
  let mode = 'local';
  let refreshed = 0;
  mocks.api.mockImplementation((path: string, opts?: { method?: string; body?: string }) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      refreshed += 1;
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at: null,
        offline_capture: mode,
      });
    }
    if (path === '/client/hub/offline-capture') {
      mode = JSON.parse(opts?.body ?? '{}').mode;
      return Promise.resolve({ offline_capture: mode });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  render(<SettingsScreen />);

  const select = await screen.findByLabelText('When offline');
  const refreshesBefore = refreshed;
  fireEvent.change(select, { target: { value: 'queue' } });

  expect(mocks.api).toHaveBeenCalledWith('/client/hub/offline-capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'queue' }),
  });
  await waitFor(() => expect(select).toHaveValue('queue'));
  expect(refreshed).toBeGreaterThan(refreshesBefore);
});

test('shows an error and reverts the select when the offline-capture POST fails', async () => {
  let rejectPost: (e: Error) => void;
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at: null,
        offline_capture: 'local',
      });
    }
    if (path === '/client/hub/offline-capture') {
      return new Promise((_, reject) => { rejectPost = reject; });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  render(<SettingsScreen />);

  const select = await screen.findByLabelText('When offline');
  fireEvent.change(select, { target: { value: 'queue' } });

  // Disabled while the POST is in flight.
  await waitFor(() => expect(select).toBeDisabled());

  rejectPost!(new Error('hub unreachable'));

  expect(await screen.findByRole('alert')).toHaveTextContent('hub unreachable');
  expect(select).toHaveValue('local');
  expect(select).not.toBeDisabled();
});

test('hides the offline-capture control when not joined', async () => {
  render(<SettingsScreen />);

  await screen.findByText('Join a hub');
  expect(screen.queryByLabelText('When offline')).not.toBeInTheDocument();
});

test('surfaces a failed migration job error and re-enables the button', async () => {
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([{ name: 'base', status: 'bundled', size_mb: 140 }]);
    }
    if (path === '/devices/paired') {
      return Promise.resolve({ devices: [] });
    }
    if (path === '/client/hub') {
      return Promise.resolve({
        joined: true,
        hub_url: 'https://hub.example',
        device_name: 'lieuwe-laptop',
        migrated_at: null,
      });
    }
    if (path === '/client/hub/migrate') {
      return Promise.resolve({ job_id: 'job1' });
    }
    if (path === '/jobs/job1') {
      return Promise.resolve({
        id: 'job1', kind: 'migrate', status: 'failed', stage: 'migrate',
        percent: 0, error: 'hub unreachable', transcript_id: null, audio_path: null, paths: {},
      });
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });

  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<SettingsScreen pollMs={1} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Migrate library to hub' }));

  expect(await screen.findByText('hub unreachable')).toBeInTheDocument();
  expect(
    await screen.findByRole('button', { name: 'Migrate library to hub' }),
  ).not.toBeDisabled();
  confirmSpy.mockRestore();
});
