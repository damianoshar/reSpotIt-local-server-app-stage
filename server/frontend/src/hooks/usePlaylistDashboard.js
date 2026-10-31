/**
 * usePlaylistDashboard
 * --------------------
 * The playlist half of the server, for the dashboard view: Spotify's live
 * playlist list (GET /api/v1/playlists, which this backend annotates with
 * `synced_at`), plus the cached albums of whichever playlist is open
 * (GET /api/v1/playlists/{id}/albums — filtering, sorting and pagination all
 * server-side, mirroring the library's useAlbums).
 *
 * A playlist has two states the UI must respect:
 *   - listed live by Spotify, possibly with no server-side cache. Selecting an
 *     unsynced playlist runs POST /playlists/{id}/sync first, because /albums
 *     404s until the cache exists.
 *   - cached: albums come back deduped (one card per album, however many of
 *     its tracks the playlist holds), and the grid pages through them.
 *
 * Everything here only runs while the dashboard is mounted — opening it is the
 * one user action that starts playlist traffic, and closing it drops the state.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'
import { describeRemoteError } from '../api/errorCodes'

const PAGE_SIZE = 48
const POLL_MS = 2000
const DEFAULT_FILTERS = { search: '', genre: '', artist: '', year: '', sort: 'artist', order: 'asc' }
const IDLE_SYNC = { active: false, current: 0, total: 0, stage: '' }

function useDebounce(value, ms) {
  const [d, setD] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setD(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return d
}

/** Identity of a (playlist, filters) pair the grid can hold. */
const keyOf = (playlistId, filters) => JSON.stringify([playlistId, filters])

export function usePlaylistDashboard() {
  const [playlists, setPlaylists]               = useState([])
  const [playlistsLoading, setPlaylistsLoading] = useState(false)
  const [playlistsError, setPlaylistsError]     = useState(null)
  const [selected, setSelected]                 = useState(null)
  const [albums, setAlbums]                     = useState([])
  const [total, setTotal]                       = useState(0)
  const [loading, setLoading]                   = useState(false)
  const [loadingMore, setLoadingMore]           = useState(false)
  const [hasMore, setHasMore]                   = useState(false)
  const [genres, setGenres]                     = useState([])
  const [artists, setArtists]                   = useState([])
  const [years, setYears]                       = useState([])
  const [filters, setFilters]                   = useState(DEFAULT_FILTERS)
  const [syncState, setSyncState]               = useState(IDLE_SYNC)
  const [syncError, setSyncError]               = useState(null)
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState(new Set())

  const selectedRef   = useRef(null)
  const activeJobRef  = useRef(null)
  const pageRef       = useRef(1)
  // The (playlist, filters) pair the grid currently holds — stops the
  // debounce tick that follows a select or a reset from re-fetching page 1.
  const lastQueryRef  = useRef('')
  // Playlists auto-repaired once already; a second 404 must surface, not
  // loop sync ↔ 404.
  const healedRef     = useRef(new Set())
  // Defined below loadAlbums; reached through a ref because the two call each
  // other (a 404 needs a sync; a finished sync reloads the grid).
  const loadAlbumsRef = useRef(null)

  const debounced = useDebounce(filters, 250)

  const loadPlaylists = useCallback(async () => {
    setPlaylistsLoading(true)
    setPlaylistsError(null)
    try {
      const data = await api.getPlaylists()
      setPlaylists(Array.isArray(data) ? data : [])
    } catch (e) {
      setPlaylistsError(describeRemoteError(e, 'Failed to load playlists'))
    } finally {
      setPlaylistsLoading(false)
    }
  }, [])

  const togglePlaylistSelection = useCallback((playlistId) => {
    setSelectedPlaylistIds((prev) => {
      const next = new Set(prev)
      next.has(playlistId) ? next.delete(playlistId) : next.add(playlistId)
      return next
    })
  }, [])

  const clearPlaylistSelection = useCallback(() => {
    setSelectedPlaylistIds(new Set())
  }, [])

  const deleteSelectedPlaylists = useCallback(async () => {
    const ids = [...selectedPlaylistIds]
    if (!ids.length) return
    const ok = window.confirm(
      `Permanently delete/unfollow ${ids.length} selected playlist(s)? This cannot be undone.`
    )
    if (!ok) return
    setPlaylistsLoading(true)
    setPlaylistsError(null)
    let failed = 0
    for (const id of ids) {
      try {
        await api.deletePlaylist(id)
      } catch {
        failed += 1
      }
    }
    await loadPlaylists()
    setSelectedPlaylistIds(new Set())
    setPlaylistsLoading(false)
    if (failed) setPlaylistsError(`${failed} of ${ids.length} playlists could not be removed.`)
  }, [loadPlaylists, selectedPlaylistIds])

  // Rebuild one playlist's server cache: start the playlist_sync job, poll the
  // canonical job envelope the way the library sync does, then stamp the badge
  // and load the fresh grid.
  const runSync = useCallback(async (playlist) => {
    setSyncState({ active: true, current: 0, total: playlist.track_count ?? 0, stage: 'Starting…' })
    const { job_id } = await api.syncPlaylist(playlist.id)
    activeJobRef.current = job_id
    try {
      for (;;) {
        await new Promise(r => setTimeout(r, POLL_MS))
        if (activeJobRef.current !== job_id) {
          const err = new Error('Playlist sync cancelled')
          err.cancelled = true
          throw err
        }
        const job = await api.getJob(job_id)
        setSyncState({ active: true, current: job.fetched ?? 0,
                       total: job.total ?? 0, stage: job.stage || 'albums' })
        if (job.status === 'done') break
        if (job.status === 'error') throw new Error(job.error || 'Playlist sync failed')
        if (job.status === 'cancelled') {
          const err = new Error('Playlist sync cancelled')
          err.cancelled = true
          throw err
        }
      }
    } finally {
      activeJobRef.current = null
      setSyncState(IDLE_SYNC)
    }

    // The cache exists now: stamp `synced_at` locally (the server includes it
    // on the next list fetch anyway) so the picker badge and the 404 gate both
    // agree, then load the grid through the normal path.
    const syncedAt = new Date().toISOString()
    setPlaylists(prev => prev.map(p => (p.id === playlist.id ? { ...p, synced_at: syncedAt } : p)))
    const cur = selectedRef.current
    if (cur && cur.id === playlist.id) {
      const updated = { ...cur, synced_at: syncedAt }
      selectedRef.current = updated
      setSelected(updated)
    }
    await loadAlbumsRef.current?.(true)
  }, [])

  const loadAlbums = async (reset = true, overrideFilters) => {
    const playlist = selectedRef.current
    if (!playlist) return
    const f = overrideFilters ?? debounced

    try {
      if (reset) {
        setLoading(true)
        pageRef.current = 1
        lastQueryRef.current = keyOf(playlist.id, f)
      } else {
        setLoadingMore(true)
      }

      const page = reset ? 1 : pageRef.current + 1
      const result = await api.getPlaylistAlbums(playlist.id, {
        page,
        limit: PAGE_SIZE,
        search:   f.search || undefined,
        genre:    f.genre  || undefined,
        artist:   f.artist || undefined,
        // The dashboard's single "year" control pins both ends of the range;
        // the endpoint owns the range semantics.
        year_from: f.year || undefined,
        year_to:   f.year || undefined,
        sort:     f.sort || 'artist',
        order:    f.order || 'asc',
      })
      if (selectedRef.current?.id !== playlist.id) return   // selection moved on

      pageRef.current = page
      const items = result?.items ?? []
      setAlbums(prev => {
        const merged = reset ? items : [...prev, ...items]
        const seen = new Set()
        return merged.filter(a => {
          if (seen.has(a.id)) return false
          seen.add(a.id)
          return true
        })
      })
      setTotal(result?.total ?? 0)
      setHasMore(page * PAGE_SIZE < (result?.total ?? 0))

      // Filter dropdown options for this playlist. Non-fatal: the grid works
      // without them, only the dropdowns stay empty.
      if (reset) {
        api.getPlaylistMeta(playlist.id)
          .then(meta => {
            setGenres(meta?.genres ?? [])
            setArtists(meta?.artists ?? [])
            setYears(meta?.years ?? [])
          })
          .catch(() => {})
      }
    } catch (e) {
      if (selectedRef.current?.id !== playlist.id) return
      if (e?.status === 404 && !healedRef.current.has(playlist.id)) {
        // Listed live but never cached (or the cache was wiped): build it once
        // — runSync reloads the grid when it finishes.
        healedRef.current.add(playlist.id)
        try { await runSync(playlist) }
        catch (err) { if (!err?.cancelled) setSyncError(describeRemoteError(err, 'Playlist sync failed')) }
      } else if (e?.status === 404) {
        setSyncError('That playlist is not cached on the server yet.')
      } else {
        setSyncError(describeRemoteError(e, 'Failed to load playlist albums'))
      }
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }
  loadAlbumsRef.current = loadAlbums

  // Re-query when the debounced filters change. Skipped for the pair the grid
  // already holds (select/reset claim it up front) and while a sync is
  // building the cache (runSync reloads explicitly when it finishes).
  useEffect(() => {
    const playlist = selectedRef.current
    if (!playlist || activeJobRef.current) return
    if (lastQueryRef.current === keyOf(playlist.id, debounced)) return
    loadAlbumsRef.current?.(true, debounced)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(debounced)])

  const selectPlaylist = useCallback(async (playlist) => {
    if (activeJobRef.current) return          // don't yank a running sync
    selectedRef.current = playlist
    setSelected(playlist)
    setFilters(DEFAULT_FILTERS)
    setAlbums([])
    setTotal(0)
    setHasMore(false)
    setSyncError(null)
    pageRef.current = 1
    // Claim the (default filters, playlist) pair so the debounce tick that
    // follows setFilters above does not fire a query of its own.
    lastQueryRef.current = keyOf(playlist.id, DEFAULT_FILTERS)

    if (playlist.synced_at) {
      await loadAlbums(true, DEFAULT_FILTERS)
    } else {
      // Never synced on the server: build the cache first, then load it.
      try {
        await runSync(playlist)
      } catch (e) {
        if (!e?.cancelled) setSyncError(describeRemoteError(e, 'Playlist sync failed'))
      }
    }
  }, [runSync])

  const clearPlaylist = useCallback(() => {
    // Detach any poll loop; best-effort server cancel in the background.
    const jobId = activeJobRef.current
    activeJobRef.current = null
    if (jobId) api.cancelJob(jobId).catch(() => {})
    selectedRef.current = null
    lastQueryRef.current = ''
    setSelected(null)
    setAlbums([])
    setTotal(0)
    setHasMore(false)
    setFilters(DEFAULT_FILTERS)
    setSyncState(IDLE_SYNC)
    setSyncError(null)
  }, [])

  const syncNow = useCallback(async () => {
    const playlist = selectedRef.current
    if (!playlist || activeJobRef.current) return
    setSyncError(null)
    try { await runSync(playlist) }
    catch (e) { if (!e?.cancelled) setSyncError(describeRemoteError(e, 'Playlist sync failed')) }
  }, [runSync])

  const cancelSync = useCallback(() => {
    const jobId = activeJobRef.current
    activeJobRef.current = null
    setSyncState(IDLE_SYNC)
    if (jobId) api.cancelJob(jobId).catch(() => {})
  }, [])

  const loadMore = () => {
    if (!loading && !loadingMore && hasMore && !activeJobRef.current) {
      loadAlbumsRef.current?.(false)
    }
  }

  const updateFilter = useCallback((patch) => {
    setFilters(prev => ({ ...prev, ...patch }))
  }, [])

  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), [])

  const hasActiveFilters = Boolean(filters.search || filters.genre || filters.artist || filters.year)

  return {
    playlists, playlistsLoading, playlistsError,
    selected, albums, total, loading, loadingMore, hasMore, hasActiveFilters,
    genres, artists, years, filters,
    syncState, syncError, syncBusy: syncState.active,
    selectedPlaylistIds, togglePlaylistSelection, clearPlaylistSelection,
    deleteSelectedPlaylists,
    loadPlaylists, selectPlaylist, clearPlaylist, loadMore,
    updateFilter, resetFilters, syncNow, cancelSync,
  }
}
