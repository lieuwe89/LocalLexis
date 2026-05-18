import { useBackend } from '../stores/backend';
import './BootOverlay.css';

const EXTENDED_THRESHOLD_MS = 15_000;

export function BootOverlay() {
  const status = useBackend(s => s.status);
  const elapsedMs = useBackend(s => s.elapsedMs);
  const error = useBackend(s => s.error);

  if (status === 'ready') return null;

  return (
    <div className="boot-overlay" data-testid="boot-overlay" role="status" aria-atomic="true">
      <div className="boot-overlay__logo">LocalLexis</div>
      {status === 'starting' && <div className="boot-overlay__spinner" aria-hidden="true" />}
      <div className="boot-overlay__phase">
        {status === 'starting' ? 'Starting audio engine…' : 'Engine failed to start'}
      </div>
      {status === 'starting' && elapsedMs >= EXTENDED_THRESHOLD_MS && (
        <div className="boot-overlay__extended">
          Taking longer than usual. On first launch macOS verifies the app — this usually
          finishes within 30 seconds.
        </div>
      )}
      {status === 'failed' && (
        <div className="boot-overlay__error">
          Couldn't start the audio engine. {error ?? ''}
        </div>
      )}
    </div>
  );
}
