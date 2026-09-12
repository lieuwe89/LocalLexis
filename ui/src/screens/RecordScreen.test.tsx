import { render, screen, fireEvent } from '@testing-library/react';
import { vi } from 'vitest';
import { RecordScreen } from './RecordScreen';

test('record button calls onStart when idle', () => {
  const onStart = vi.fn();
  render(
    <RecordScreen
      devices={[]} active={false} elapsed={0}
      outputPath="/tmp/r.wav" selectedDevice={null}
      onSelectDevice={() => {}} onStart={onStart} onStop={() => {}}
    />
  );
  fireEvent.click(screen.getByTitle('Start recording'));
  expect(onStart).toHaveBeenCalled();
});

test('timer renders mm:ss with tabular nums', () => {
  render(
    <RecordScreen
      devices={[]} active={true} elapsed={73.4}
      outputPath="/tmp/r.wav" selectedDevice={null}
      onSelectDevice={() => {}} onStart={() => {}} onStop={() => {}}
    />
  );
  expect(screen.getByText('01:13')).toBeInTheDocument();
});

test('record button calls onStop when active', () => {
  const onStop = vi.fn();
  render(
    <RecordScreen
      devices={[]} active={true} elapsed={5}
      outputPath="/tmp/r.wav" selectedDevice={null}
      onSelectDevice={() => {}} onStart={() => {}} onStop={onStop}
    />
  );
  fireEvent.click(screen.getByTitle('Stop'));
  expect(onStop).toHaveBeenCalled();
});

test('shows the sidecar error when the recording failed', () => {
  render(
    <RecordScreen
      devices={[]} active={false} elapsed={0} error="PortAudioError: no device"
      outputPath="/tmp/r.wav" selectedDevice={null}
      onSelectDevice={() => {}} onStart={() => {}} onStop={() => {}}
    />
  );
  expect(screen.getByRole('alert')).toHaveTextContent('PortAudioError: no device');
});
