import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BackendStatus } from './BackendStatus';
import { useBackend } from '../stores/backend';

describe('BackendStatus', () => {
  beforeEach(() => {
    useBackend.getState()._resetForTests();
    useBackend.setState({ status: 'starting', elapsedMs: 0, error: null });
  });

  it('renders "Starting" pill when status is "starting"', () => {
    render(<BackendStatus />);
    expect(screen.getByText(/starting/i)).toBeInTheDocument();
  });

  it('renders "Ready" pill when status is "ready"', () => {
    useBackend.setState({ status: 'ready' });
    render(<BackendStatus />);
    expect(screen.getByText(/ready/i)).toBeInTheDocument();
  });

  it('renders "Offline" pill when status is "failed"', () => {
    useBackend.setState({ status: 'failed', error: 'boom' });
    render(<BackendStatus />);
    expect(screen.getByText(/offline/i)).toBeInTheDocument();
  });

  it('exposes status via data attribute for styling', () => {
    render(<BackendStatus />);
    expect(screen.getByTestId('backend-status').getAttribute('data-status')).toBe('starting');
  });
});
