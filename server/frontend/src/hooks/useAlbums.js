import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'
import { queryAlbums } from '../services/localDatabase'
import { getHiddenDuplicateIds } from '../utils/duplicateBlocklist'

const PAGE_SIZE = 48

function useDebounce(value, ms) {
  const [d, setD] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setD(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return d
}

/**
 * One paged query, whatever the data source.
 *
 * `source` is the `useDataSource()` result; local mode answers the same
 * `{items,total}` envelope out of IndexedDB, so nothing below this hook has to
 * know which one it is talking to.
 *
 * `sessionKey` is the signed-in user's id ('anon' while somebody is not
 * signed in). Remote data is per-user since Phase 2, so fetching before the
 * login gate fires a pointless 401 (and its result would be stale account
 * data anyway) — the query waits for the account and re-runs when it changes.
 */
export function useAlbums(filters, page, source, sessionKey) {
  const [albums, setAlbums]   = useState([])
  const [total, setTotal]     = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const debounced = useDebounce(filters, 380)
  const cancelRef = useRef(false)

  const isLocal = Boolean(source?.isLocal)
  const serverUrl = source?.serverUrl ?? ''
  const libraryVersion = source?.libraryVersion ?? 0
  const sessionEpoch = sessionKey ?? 'anon'

  useEffect(() => {
    cancelRef.current = false
    if (!isLocal && sessionEpoch === 'anon') {
      // No account yet → no library to show; skip the doomed request.
      setAlbums([]); setTotal(0); setLoading(false); setError(null)
      return
    }
    setLoading(true)
    setError(null)

    const request = isLocal
      ? queryAlbums(debounced, page, PAGE_SIZE)
      : api.getAlbums({ ...debounced, page, limit: PAGE_SIZE })

    request
      .then(data => {
        if (cancelRef.current) return
        let items = data.items ?? []
        const hidden = getHiddenDuplicateIds()
        if (hidden.size) {
          items = items.filter((a) => !hidden.has(a.spotify_id || a.id))
        }
        setAlbums(items)
        setTotal(data.total  ?? 0)
      })
      .catch(e => {
        if (cancelRef.current) return
        setError(e.message)
        setAlbums([])
        setTotal(0)
      })
      .finally(() => {
        if (!cancelRef.current) setLoading(false)
      })

    return () => { cancelRef.current = true }
  // Re-query on a mode/URL change too, not just on filter changes: switching
  // data source must not leave the previous source's rows on screen. The
  // local-library version bumps on CSV import/clear, so the grid refreshes
  // without a reload. Sign-in/sign-out is a sessionEpoch change, so the grid
  // refetches for the account that is now in place.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(debounced), page, isLocal, serverUrl, libraryVersion, sessionEpoch])

  return { albums, total, loading, error }
}
