import { useBackend, type BackendStatus as Status } from '../stores/backend';

const LABEL: Record<Status, string> = {
  starting: 'Starting',
  ready: 'Ready',
  failed: 'Offline',
};

export function BackendStatus() {
  const status = useBackend(s => s.status);
  const error = useBackend(s => s.error);
  return (
    <span
      className="chip backend-status"
      data-status={status}
      data-testid="backend-status"
      title={status === 'failed' ? `Engine offline${error ? ` — ${error}` : ''}` : `Engine ${LABEL[status]}`}
    >
      <span className="backend-status__dot" aria-hidden="true" />
      {LABEL[status]}
    </span>
  );
}
