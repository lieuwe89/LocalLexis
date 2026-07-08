import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { SettingsForm } from './SettingsForm';
import type { ConfigDto } from '../../api/types';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
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

vi.mock('../../api/client', () => ({
  api: mocks.api,
}));

vi.mock('../../stores/config', () => ({
  useConfig: (selector: (state: typeof mocks.configState) => unknown) =>
    selector(mocks.configState),
}));

beforeEach(() => {
  mocks.api.mockReset();
  mocks.configState.load.mockReset();
  mocks.configState.patch.mockReset();
  mocks.configState.load.mockResolvedValue(undefined);
  mocks.configState.patch.mockResolvedValue(undefined);
  mocks.api.mockImplementation((path: string) => {
    if (path === '/models/whisper') {
      return Promise.resolve([
        { name: 'base', status: 'bundled', size_mb: 140 },
        { name: 'small', status: 'not_downloaded', size_mb: 470 },
      ]);
    }
    return Promise.reject(new Error(`unexpected api: ${path}`));
  });
});

test('renders config fields from the store and saves a patch', async () => {
  render(<SettingsForm />);

  expect(await screen.findByText('Backend')).toBeInTheDocument();
  expect(screen.getByText('ASR model')).toBeInTheDocument();

  const backendSelect = screen.getByDisplayValue('auto') as HTMLSelectElement;
  fireEvent.change(backendSelect, { target: { value: 'cpu' } });

  const saveBtn = screen.getByRole('button', { name: 'Save' });
  fireEvent.click(saveBtn);

  expect(mocks.configState.patch).toHaveBeenCalledWith({ backend: 'cpu' });
});

test('renders watch extensions as comma list', async () => {
  render(<SettingsForm />);

  const extensionsInput = await screen.findByDisplayValue('wav, mp3');
  expect(extensionsInput).toBeInTheDocument();
});
