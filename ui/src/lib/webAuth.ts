const KEY = 'locallexis_admin_token';

export function getToken(): string | null {
  return localStorage.getItem(KEY);
}
export function setToken(t: string): void {
  localStorage.setItem(KEY, t);
}
export function clearToken(): void {
  localStorage.removeItem(KEY);
}

// Verify a candidate token against an authed /health on this origin. Stores
// it on success so subsequent api() calls pick it up; leaves storage untouched
// on failure.
export async function verifyToken(token: string): Promise<boolean> {
  try {
    const r = await fetch(window.location.origin + '/health', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (r.ok) {
      setToken(token);
      return true;
    }
  } catch {}
  return false;
}
