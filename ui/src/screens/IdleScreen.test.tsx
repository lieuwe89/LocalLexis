import { render, screen, fireEvent } from '@testing-library/react';
import { IdleScreen } from './IdleScreen';
import { vi } from 'vitest';

vi.mock('@tauri-apps/plugin-dialog', () => ({
  open: vi.fn(),
}));

test('renders hero and drop zone', () => {
  render(<IdleScreen onTranscribe={() => {}} recentFiles={[]} />);
  expect(screen.getByText(/Drag an audio file here/)).toBeInTheDocument();
});

test('drag-over toggles active class', () => {
  render(<IdleScreen onTranscribe={() => {}} recentFiles={[]} />);
  const drop = screen.getByText(/Drag an audio file here/).closest('.drop') as HTMLElement;
  fireEvent.dragEnter(drop);
  expect(drop.classList.contains('active')).toBe(true);
  fireEvent.dragLeave(drop);
  expect(drop.classList.contains('active')).toBe(false);
});

test('dropping a file calls onTranscribe with path', () => {
  const onTranscribe = vi.fn();
  render(<IdleScreen onTranscribe={onTranscribe} recentFiles={[]} />);
  const drop = screen.getByText(/Drag an audio file here/).closest('.drop')!;
  const file = new File(['x'], 'meet.mp3', { type: 'audio/mpeg' });
  Object.defineProperty(file, 'path', { value: '/tmp/meet.mp3' });
  fireEvent.drop(drop, { dataTransfer: { files: [file] } });
  expect(onTranscribe).toHaveBeenCalledWith('/tmp/meet.mp3');
});
