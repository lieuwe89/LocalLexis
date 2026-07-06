import { useState } from 'react';
import { verifyToken } from '../../lib/webAuth';

export function LoginScreen({ onAuthed }: { onAuthed: () => void }) {
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const ok = await verifyToken(token.trim());
    setBusy(false);
    if (ok) onAuthed();
    else setError('Invalid admin token.');
  };

  return (
    <div className="login-screen">
      <form onSubmit={submit}>
        <h1>LocalLexis Hub</h1>
        <label htmlFor="admin-token">Admin token</label>
        <input
          id="admin-token"
          type="password"
          value={token}
          onChange={e => setToken(e.target.value)}
          autoFocus
        />
        {error && <p role="alert" className="login-error">{error}</p>}
        <button type="submit" disabled={busy || !token.trim()}>
          {busy ? 'Checking…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
