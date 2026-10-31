import { useState, useEffect, useCallback } from 'react'

export const SYNC_PHOTOS_KEY = 'reSpotIt_sync_photos';

export function readSyncPhotos() {
  try {
    const v = localStorage.getItem(SYNC_PHOTOS_KEY)
    return v === null ? true : v === '1'
  } catch {
    return true
  }
}

export function writeSyncPhotos(enabled) {
  try { localStorage.setItem(SYNC_PHOTOS_KEY, enabled ? '1' : '0') } catch {}
  window.dispatchEvent(new Event('reSpotIt:syncPhotos'))
}

export function useSyncPhotos() {
  const [enabled, setEnabled] = useState(readSyncPhotos())

  useEffect(() => {
    const update = () => setEnabled(readSyncPhotos())
    window.addEventListener('reSpotIt:syncPhotos', update)
    return () => window.removeEventListener('reSpotIt:syncPhotos', update)
  }, [])

  const toggle = useCallback((value) => {
    writeSyncPhotos(value)
    setEnabled(value)
  }, [])

  return [enabled, toggle]
}
