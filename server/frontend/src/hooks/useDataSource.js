/**
 * Data source — local on-device library vs network server.
 *
 * Same shape as the sibling apps' `useDataSource`, backed by localStorage
 * because this build has no Capacitor Preferences. Switching modes is applied
 * immediately (the library hooks re-query) and persisted for the next visit.
 */
import { useState, useCallback } from 'react'
import { loadDataSourceSettings, saveDataSourceSettings, normalizeServerUrl } from '../config/server'
import { checkServerHealth } from '../services/serverHealth'

export function useDataSource() {
  // Read synchronously: there is no async preferences bridge here, so there is
  // no "loading" state to render around.
  const [settings, setSettings] = useState(() => loadDataSourceSettings())
  const [testing, setTesting]       = useState(false)
  const [testResult, setTestResult] = useState(null)
  // Bumped whenever the local library changes (CSV import / clear) so views
  // that aggregate over it — stats, the artist datalist — re-read.
  const [libraryVersion, setLibraryVersion] = useState(0)

  const notifyLibraryChanged = useCallback(() => setLibraryVersion((v) => v + 1), [])

  const apply = useCallback((patch) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch }
      saveDataSourceSettings(next)
      return next
    })
    // A stale "connected" badge next to a changed URL would be a lie.
    setTestResult(null)
  }, [])

  const setMode = useCallback(
    (mode) => apply({ mode: mode === 'local' ? 'local' : 'remote' }),
    [apply],
  )

  const setServerUrl = useCallback(
    (serverUrl) => apply({ serverUrl: normalizeServerUrl(serverUrl) }),
    [apply],
  )

  const testConnection = useCallback(async () => {
    setTesting(true)
    try {
      await checkServerHealth(settings.serverUrl)
      setTestResult({ ok: true, message: 'Server reachable' })
      return true
    } catch (e) {
      setTestResult({ ok: false, message: e?.message || 'Connection failed' })
      return false
    } finally {
      setTesting(false)
    }
  }, [settings.serverUrl])

  return {
    settings,
    mode: settings.mode,
    serverUrl: settings.serverUrl,
    isLocal: settings.mode === 'local',
    testing,
    testResult,
    setMode,
    setServerUrl,
    testConnection,
    apply,
    libraryVersion,
    notifyLibraryChanged,
  }
}
