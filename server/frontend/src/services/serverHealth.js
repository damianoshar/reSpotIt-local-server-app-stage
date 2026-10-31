/**
 * Server reachability probe for the Test-connection button.
 *
 * Tries the contract health path (`/api/v1/health`) first, then the bare
 * `/health` some deployments expose, so one button works against every backend.
 * Both paths are asserted by every backend's smoke suite.
 */
export async function checkServerHealth(serverUrl) {
  const base = String(serverUrl ?? '').trim().replace(/\/+$/, '');
  if (!base) {
    throw new Error('Enter a server URL first.');
  }

  let lastError;
  for (const path of ['/api/v1/health', '/health']) {
    try {
      const res = await fetch(base + path);
      if (res.ok) return;
      lastError = new Error(`Server replied ${res.status} on ${path}`);
    } catch (e) {
      lastError = e;
    }
  }

  throw new Error(
    `Cannot reach ${base} — is the server running?` +
    (lastError instanceof Error && lastError.message ? ` (${lastError.message})` : ''),
  );
}
