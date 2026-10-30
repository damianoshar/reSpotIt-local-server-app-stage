/**
 * Data-source mode: local on-device library (IndexedDB) vs network server.
 *
 * Mirrors `config/server.ts` in the sibling csharp frontend, persisted in
 * localStorage because this is a plain web app with no Capacitor Preferences.
 * The local layer is IndexedDB-backed — see services/localDatabase.js.
 *
 * NOTE the default is REMOTE here, unlike csharp/frontend which defaults to
 * local. This app's library has always been server-backed: the Spotify sync
 * pipeline runs on the server for every step (it needs credentials this app
 * never holds), so defaulting to local would show an empty library to every
 * existing user the moment they upgrade. The badge in the header makes the
 * active mode visible either way, and switching is one click.
 *
 * Remote API contract: API-PARITY-PLAN.md §1 (identical calls on every backend).
 */

export const DATA_SOURCE_PREFS_KEY = 'reSpotIt_data_source';

/** '' = same origin — nginx proxies /api/* to FastAPI, and vite does the same in dev. */
export const DEFAULT_SERVER_URL = '';

export const DEFAULT_DATA_SOURCE = { mode: 'remote', serverUrl: DEFAULT_SERVER_URL };

export function normalizeServerUrl(raw) {
  return String(raw ?? '').trim().replace(/\/+$/, '');
}

function read() {
  try {
    const raw = localStorage.getItem(DATA_SOURCE_PREFS_KEY);
    if (!raw) return DEFAULT_DATA_SOURCE;
    const parsed = JSON.parse(raw) || {};
    return {
      // Anything that is not an explicit 'local' stays remote: a corrupt or
      // half-written preference must not silently strand the user in an empty
      // local library.
      mode: parsed.mode === 'local' ? 'local' : 'remote',
      serverUrl: normalizeServerUrl(parsed.serverUrl) || DEFAULT_SERVER_URL,
    };
  } catch {
    return DEFAULT_DATA_SOURCE;
  }
}

function write(next) {
  try {
    localStorage.setItem(DATA_SOURCE_PREFS_KEY, JSON.stringify(next));
  } catch {
    // Private mode / quota: in-memory state still works for this session.
  }
}

export function loadDataSourceSettings() {
  return read();
}

export function saveDataSourceSettings(next) {
  write(next);
}
