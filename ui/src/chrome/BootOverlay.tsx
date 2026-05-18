import { useEffect, useState } from 'react';
import { useBackend } from '../stores/backend';
import './BootOverlay.css';

const EXTENDED_THRESHOLD_MS = 15_000;

export function BootOverlay() {
  const status = useBackend(s => s.status);
  const elapsedMs = useBackend(s => s.elapsedMs);
  const error = useBackend(s => s.error);
  const [isFirstLaunch] = useState(() => useBackend.getState().isFirstLaunch());

  useEffect(() => {
    if (status === 'ready') {
      useBackend.getState().markFirstLaunchDone();
    }
  }, [status]);

  if (status === 'ready') return null;

  return (
    <div className="boot-overlay" data-testid="boot-overlay" role="status" aria-atomic="true">
      <div className="boot-overlay__logo">LocalLexis</div>
      {status === 'starting' && <div className="boot-overlay__spinner" aria-hidden="true" />}
      <div className="boot-overlay__phase">
        {status === 'starting' ? 'Starting audio engine…' : 'Engine failed to start'}
      </div>
      {status === 'starting' && isFirstLaunch && (
        <div className="boot-overlay__extended">
          This is the first time you open LocalLexis. macOS is verifying the app — first launch
          usually takes 20-40 seconds. Subsequent launches start instantly.
        </div>
      )}
      {status === 'starting' && !isFirstLaunch && elapsedMs >= EXTENDED_THRESHOLD_MS && (
        <div className="boot-overlay__extended">
          Taking longer than usual. Try quitting and relaunching if this persists.
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
