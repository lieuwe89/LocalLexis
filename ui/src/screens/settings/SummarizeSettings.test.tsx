import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { SummarizeSettings } from './SummarizeSettings';
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
      watch: { recursive: true, debounce_seconds: 2, extensions: ['wav'] },
      summarize: {
        provider: 'lemonade',
        base_url: 'http://127.0.0.1:13305/api/v1',
        model: 'm1',
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
  mocks.configState.patch.mockReset();
  mocks.configState.patch.mockResolvedValue(undefined);
});

test('loads models from /summarize/models into a select', async () => {
  mocks.api.mockResolvedValue({ models: ['m1', 'm2'] });

  render(<SummarizeSettings />);

  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/summarize/models'));
  expect(await screen.findByRole('option', { name: 'm1' })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: 'm2' })).toBeInTheDocument();
});

test('falls back to free-text model input when models fetch fails', async () => {
  mocks.api.mockRejectedValue(new Error('provider down'));

  render(<SummarizeSettings />);

  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/summarize/models'));
  const modelInput = await screen.findByDisplayValue('m1');
  expect(modelInput.tagName).toBe('INPUT');
});

test('saves provider/base_url/model/api_key via config patch', async () => {
  mocks.api.mockResolvedValue({ models: ['m1', 'm2'] });

  render(<SummarizeSettings />);

  await screen.findByRole('option', { name: 'm1' });

  const modelSelect = screen.getByDisplayValue('m1') as HTMLSelectElement;
  fireEvent.change(modelSelect, { target: { value: 'm2' } });

  const saveBtn = screen.getByRole('button', { name: 'Save' });
  fireEvent.click(saveBtn);

  await waitFor(() =>
    expect(mocks.configState.patch).toHaveBeenCalledWith({ summarize: { model: 'm2' } }),
  );
});

test('provider preset buttons fill base_url', async () => {
  mocks.api.mockResolvedValue({ models: ['m1'] });

  render(<SummarizeSettings />);

  const providerSelect = await screen.findByDisplayValue('lemonade');
  fireEvent.change(providerSelect, { target: { value: 'openrouter' } });

  const baseUrlInput = screen.getByDisplayValue('https://openrouter.ai/api/v1');
  expect(baseUrlInput).toBeInTheDocument();
});
