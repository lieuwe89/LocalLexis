import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LoginScreen } from './LoginScreen';

vi.mock('../../lib/webAuth', () => ({
  verifyToken: vi.fn(async (t: string) => t === 'good'),
}));

describe('LoginScreen', () => {
  it('calls onAuthed on a valid token', async () => {
    const onAuthed = vi.fn();
    render(<LoginScreen onAuthed={onAuthed} />);
    fireEvent.change(screen.getByLabelText(/admin token/i), { target: { value: 'good' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(onAuthed).toHaveBeenCalled());
  });

  it('shows an error on a bad token', async () => {
    const onAuthed = vi.fn();
    render(<LoginScreen onAuthed={onAuthed} />);
    fireEvent.change(screen.getByLabelText(/admin token/i), { target: { value: 'bad' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(onAuthed).not.toHaveBeenCalled();
  });
});
