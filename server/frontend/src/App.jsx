import { useState, useCallback, useEffect, useRef } from 'react'
import { handleLocalSpotifyCallback } from './services/spotifyAuth'
import { usePipeline }       from './hooks/usePipeline'
import { useAlbums }         from './hooks/useAlbums'
import { useArtists }        from './hooks/useArtists'
import { useAuth }           from './hooks/useAuth'
import { useQuickJob }       from './hooks/useQuickJob'
import { useDataSource }     from './hooks/useDataSource'
import { api, setApiBase }   from './api/client'
import { getStats as getLocalStats } from './services/localDatabase'
import { downloadLibraryCsv } from './services/exportDownload'
import { saveBackupToFolder } from './services/backupFolder'
import { SyncPanel }         from './components/SyncPanel'
import { AlbumGrid }         from './components/AlbumGrid'
import { AlbumTrackSheet }   from './components/AlbumTrackSheet'
import { FilterSidebar }     from './components/FilterSidebar'
import { ViewToolbar }       from './components/ViewToolbar'
import { StatsBar }          from './components/StatsBar'
import { StatsPanel }       from './components/StatsPanel'
import { Toasts }            from './components/Toasts'
import { SelectionToolbar }  from './components/SelectionToolbar'
import { PlaylistModal }     from './components/PlaylistModal'
import { PlaylistDashboard } from './components/PlaylistDashboard'
import { AuthButton }        from './components/AuthButton'
import { LoginGate }         from './components/LoginGate'
import { SettingsView }      from './components/SettingsView'
import { ToolsView }         from './components/ToolsView'
import { PlayerView }        from './components/PlayerView'

const DEFAULT_FILTERS = {
  search: '', artist: '', genre: '', album_type: '',
  year_from: '', year_to: '', min_pop: 0, max_pop: 100,
}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('reSpotIt_view_prefs')) || {} } catch { return {} }
}

export default function App() {
  // Data source first: mode decides whether any of the server hooks below are
  // allowed to talk to a server at all.
  const ds = useDataSource()
  const serverMode = !ds.isLocal

  const { user, authenticated, displayName, loading: authLoading,
          signingIn, signIn, signInWithPassword, signOut } = useAuth(ds)

  // Per-account storage keys: sync/quick-job rows are persisted under the
  // signed-in user's id so sharing a browser does not mix two accounts.
  const userKey = user?.id ? String(user.id) : 'anon'

  const pipeline = usePipeline(serverMode, userKey)
  const { artists } = useArtists(ds, userKey)
  const [activeTab, setActiveTab] = useState('library')
  // C6: export a CSV backup automatically after a sync that inserted albums.
  // Opt-in and remembered; off until the user asks for it.
  const [autoExport, setAutoExport] = useState(() => {
    try { return localStorage.getItem('reSpotIt_auto_export') === '1' } catch { return false }
  })

  const [autohideNav, setAutohideNav] = useState(() => {
    try { return localStorage.getItem('reSpotIt_autohide_nav') !== '0' } catch { return true }
  })
  const [autohideBoardBar, setAutohideBoardBar] = useState(() => {
    try { return localStorage.getItem('reSpotIt_autohide_board') === '1' } catch { return false }
  })
  const [navVisible, setNavVisible] = useState(true)
  const [boardBarVisible, setBoardBarVisible] = useState(true)
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)

  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  useEffect(() => {
    try { localStorage.setItem('reSpotIt_autohide_nav', autohideNav ? '1' : '0') } catch {}
    try { localStorage.setItem('reSpotIt_autohide_board', autohideBoardBar ? '1' : '0') } catch {}
  }, [autohideNav, autohideBoardBar])

  useEffect(() => {
    if (!autohideNav && !autohideBoardBar) {
      setNavVisible(true)
      setBoardBarVisible(true)
      return
    }
    let lastY = window.scrollY
    const onScroll = () => {
      const y = window.scrollY
      const down = y > lastY + 4
      if (autohideNav) setNavVisible(!down || y < 24)
      if (autohideBoardBar) setBoardBarVisible(!down || y < 24)
      lastY = y
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [autohideNav, autohideBoardBar])

  const imagesJob = useQuickJob({
    storageKey: `reSpotIt_quick_images_v1:${userKey}`,
    starter:    api.startImages,
    enabled:    serverMode,
  })

  const loadJob = useQuickJob({
    storageKey: `reSpotIt_quick_load_v1:${userKey}`,
    starter:    api.startLoad,
    enabled:    serverMode,
  })

  const prefs = loadPrefs()
  const [filters,  setFilters]  = useState(DEFAULT_FILTERS)
  const [page,     setPage]     = useState(1)
  const [viewMode, setViewMode] = useState(prefs.viewMode ?? 'grid')
  const [columns,  setColumns]  = useState(prefs.columns  ?? 5)
  const [sort,     setSort]     = useState(prefs.sort     ?? 'added_at_desc')
  const [sidebarOpen, setSidebarOpen] = useState(prefs.sidebarOpen ?? true)

  const [selectedIds, setSelectedIds] = useState(new Set())
  const [modalMode,   setModalMode]   = useState(null)
  const [trackAlbum,  setTrackAlbum]  = useState(null)
  const [stats,       setStats]       = useState(null)
  const [visible,     setVisible]     = useState([])
  const [toasts,      setToasts]      = useState([])
  const toastId = useRef(0)
  const sentinelRef = useRef(null)
  // Mirror for the sentinel callback (avoids stale closures).
  const scrollState = useRef({ count: 0, total: 0, loading: false })

  const showToast = useCallback((msg, ok = true) => {
    const id = ++toastId.current
    setToasts(prev => [...prev.slice(-2), { id, msg, ok }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4500)
  }, [])

  const handleToggleAutoExport = useCallback(() => {
    setAutoExport(v => {
      const next = !v
      try { localStorage.setItem('reSpotIt_auto_export', next ? '1' : '0') } catch { /* private mode */ }
      return next
    })
  }, [])

  const refreshStats = useCallback(() => {
    // Remote stats are per-user since Phase 2: fetching before the login gate
    // would just burn a 401, and the data would be the wrong account's anyway.
    if (!ds.isLocal && (!user?.id)) return
    const request = ds.isLocal ? getLocalStats() : api.getStats()
    request.then(setStats).catch(() => {})
  }, [ds.isLocal, ds.libraryVersion, user?.id])

  useEffect(() => { refreshStats() }, [refreshStats])

  // Point the API client at the configured server ('' = same origin). Applied
  // on every change so a URL edit takes effect on the next request.
  useEffect(() => {
    setApiBase(ds.isLocal ? '' : ds.serverUrl)
  }, [ds.isLocal, ds.serverUrl])

  // Local (on-device) Spotify PKCE callback: exchange the code, store the
  // token, then return to the app. Server-mode auth is handled by the backend.
  useEffect(() => {
    if (typeof window === 'undefined' || window.location.pathname !== '/callback') return
    let cancelled = false
    void (async () => {
      await handleLocalSpotifyCallback()
      if (!cancelled) window.location.replace('/')
    })()
    return () => { cancelled = true }
  }, [])

  // Toast + stats refresh on pipeline transitions (fires once per change).
  const pipeToastRef = useRef('')
  useEffect(() => {
    const key = pipeline.isRunning ? 'run'
      : pipeline.isDone ? 'done'
      : pipeline.hasError ? 'error'
      : pipeline.isCancelled ? 'cancel' : 'idle'
    if (key === pipeToastRef.current) return
    pipeToastRef.current = key
    if (key === 'done') {
      showToast('Library sync complete', true)
      refreshStats()
      // C6: opt-in backup — only when the run actually inserted something.
      const inserted = pipeline.steps[2]?.data?.inserted ?? 0
      if (autoExport && serverMode && inserted > 0) {
        void (async () => {
          const filename = `spotify-library-${new Date().toISOString().slice(0, 10)}.csv`
          try {
            const blob = await api.exportCsvBlob()
            const saved = await saveBackupToFolder(blob, filename)
            if (!saved) {
              const href = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = href
              a.download = filename
              document.body.appendChild(a)
              a.click()
              a.remove()
              URL.revokeObjectURL(href)
            }
            showToast(saved ? `Auto-export saved to backup folder (${inserted} inserted)` : `Auto-export — CSV download started (${inserted} inserted)`, true)
          } catch (e) {
            showToast(e?.message || 'Auto-export failed', false)
          }
        })()
      }
    } else if (key === 'error') {
      const bad = pipeline.steps.find(s => s.status === 'error')
      showToast(bad?.data?.message || 'Sync failed', false)
    } else if (key === 'cancel') {
      showToast('Sync cancelled — partial progress kept', false)
    }
  }, [pipeline.isRunning, pipeline.isDone, pipeline.hasError, pipeline.isCancelled,
      pipeline.steps, showToast, refreshStats, autoExport, serverMode])

  const handleToggleSelect = useCallback((spotifyId) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(spotifyId) ? next.delete(spotifyId) : next.add(spotifyId)
      return next
    })
  }, [])

  const savePrefs = (patch) => {
    try { localStorage.setItem('reSpotIt_view_prefs', JSON.stringify({ ...loadPrefs(), ...patch })) } catch {}
  }

  const handleViewMode = (m) => { setViewMode(m); savePrefs({ viewMode: m }) }
  const handleColumns  = (c) => { setColumns(c);  savePrefs({ columns: c })  }
  const handleSort     = (s) => { setSort(s);     savePrefs({ sort: s }); setPage(1); window.scrollTo({ top: 0 }) }
  const handleSidebarToggle = () => setSidebarOpen(o => {
    savePrefs({ sidebarOpen: !o })
    return !o
  })
  const handleFilterChange = useCallback(u => { setFilters(u); setPage(1); window.scrollTo({ top: 0 }) }, [])

  // Bottom-tab navigation. Tabs only exist in the page, not the URL; scroll
  // resets so a switch never lands mid-list.
  const switchTab = useCallback((t) => { setActiveTab(t); window.scrollTo({ top: 0 }) }, [])

  // Tabs that only exist server-side must not survive a switch to local mode.
  useEffect(() => {
    if (!serverMode && activeTab === 'playlists') setActiveTab('library')
  }, [serverMode, activeTab])

  const activeFilters = { ...filters, sort }
  // usePipeline's calls above get userKey for storage scoping; the data hooks
  // get it as the fetch epoch: remote data is per-user, so the grid, the
  // artist filter list and stats re-query when the signed-in account changes
  // (and stay quiet 401-less under the login gate).
  const { albums, total, loading } = useAlbums(activeFilters, page, ds, userKey)
  const hasMore = visible.length < total

  // Accumulate pages for infinite scroll (page 1 replaces, rest append).
  useEffect(() => {
    if (page === 1) { setVisible(albums); return }
    setVisible(prev => {
      const seen = new Set(prev.map(a => a.spotify_id))
      return [...prev, ...albums.filter(a => !seen.has(a.spotify_id))]
    })
  }, [albums, page])

  useEffect(() => {
    scrollState.current = { count: visible.length, total, loading }
  })

  // Infinite-scroll sentinel (400px lookahead, mirrors the TS reference).
  // Attach the observer whenever the sentinel actually exists; it is only
  // rendered once enough albums have loaded, so a [] dependency would miss it.
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(([entry]) => {
      const s = scrollState.current
      if (entry.isIntersecting && !s.loading && s.count > 0 && s.count < s.total) {
        setPage(p => p + 1)
      }
    }, { rootMargin: '400px' })
    obs.observe(el)
    return () => obs.disconnect()
  }, [visible.length, total, loading])
  const handleToggleAllVisible = useCallback(() => {
    setSelectedIds(prev => {
      const ids = visible.map(a => a.spotify_id)
      const all = ids.length > 0 && ids.every(id => prev.has(id))
      const next = new Set(prev)
      if (all) ids.forEach(id => next.delete(id))
      else ids.forEach(id => next.add(id))
      return next
    })
  }, [visible])
  const allVisibleSelected = visible.length > 0 && visible.every(a => selectedIds.has(a.spotify_id))
  const hasFilters = Object.entries(filters).some(([k, v]) => {
    if (k === 'min_pop') return v > 0
    if (k === 'max_pop') return v < 100
    return Boolean(v)
  })

  // ── Loading splash ─────────────────────────────────────────────────────────
  if (authLoading) {
    return (
      <div style={{
        minHeight: '100vh', background: '#121212',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: '#1DB954', fontSize: '1.5rem', animation: 'pulseSoft 1.5s ease-in-out infinite' }}>◉</span>
          <span style={{ fontFamily: 'Bodoni Moda, serif', color: '#B3B3B3', fontSize: '1.1rem' }}>reSpotIt</span>
        </div>
      </div>
    )
  }

  // ── Auth gate (server mode only) ───────────────────────────────────────────
  // Only the JWT account is required. A Spotify link is a capability, not a
  // gate: the library may come from a phone push, so the app opens without it
  // and the banner below offers the link for server-side Spotify actions.
  // Local mode has no accounts — the on-device library is the whole app.
  if (serverMode && !user) {
    return <LoginGate onAuthenticate={signInWithPassword} />
  }

  // ── Main app ───────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-base text-ink flex flex-col pb-16">

      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-panel/90 backdrop-blur-md">
        <div className="max-w-screen-xl mx-auto px-6 h-14 flex items-center gap-4">
          <div className="flex items-center gap-2.5 flex-shrink-0">
            <span className="text-accent text-xl">◉</span>
            <span className="font-display text-xl font-semibold tracking-tight">reSpotIt</span>
          </div>

          <div className="flex-1" />

          {/* Sync status — server-side jobs only */}
          <div className="flex items-center gap-3">
            {serverMode && pipeline.isRunning && (
              <div className="flex items-center gap-2">
                <span className="step-dot step-dot-running" />
                <span className="font-mono text-xs text-accent hidden sm:inline">
                  Syncing {pipeline.overallPct}%
                </span>
              </div>
            )}
            {serverMode && pipeline.isCancelled && !pipeline.isRunning && (
              <span className="font-mono text-[0.65rem] hidden sm:inline" style={{ color: '#B3B3B3' }}>◼ Cancelled</span>
            )}
            {serverMode && pipeline.isDone && !pipeline.isRunning && (
              <span className="font-mono text-[0.65rem] text-ok hidden sm:inline">✓ Synced</span>
            )}

            {/* Data source — which library this page is showing */}
            <button
              className="btn btn-ghost btn-sm mode-badge"
              title={ds.isLocal
                ? 'Reading this browser only — opens Settings'
                : `Reading from ${ds.serverUrl || 'this server'} — opens Settings`}
              onClick={() => switchTab('settings')}
            >
              {ds.isLocal ? '⌂ This device' : '☁ Server'}
            </button>

            {serverMode && (<>
            {/* Server-side Spotify sync and clean sync need a linked account.
                Without one the library can still be shown (e.g. pushed by a
                phone); the AuthButton below stays available to link Spotify. */}
            {authenticated && (<>
            <button
              className="btn btn-primary"
              onClick={pipeline.start}
              disabled={pipeline.isRunning}
            >
              {pipeline.isRunning ? '⟳ Syncing…' : '↓ Sync'}
            </button>

            {/* Clean sync — wipe the server library before fetching. Destructive,
                so it is an explicit toggle next to Sync, off on every load. */}
            <button
              className={`btn btn-sm ${pipeline.clean ? 'btn-primary' : 'btn-ghost'}`}
              title={pipeline.clean
                ? 'Clean sync is ON — the library is wiped and refetched'
                : 'Clean sync — wipe the server library before fetching'}
              onClick={() => pipeline.setClean?.(!pipeline.clean)}
              disabled={pipeline.isRunning}
            >
              ⌦ Clean{pipeline.clean ? ' ✓' : ''}
            </button>
            </>)}

            {/* Auth */}
            <AuthButton
              authenticated={authenticated}
              user={user}
              displayName={displayName}
              loading={authLoading}
              signingIn={signingIn}
              onSignIn={signIn}
              onSignOut={signOut}
            />
            </>)}
          </div>
        </div>
      </header>

      {/* A Spotify link is optional: the library can arrive from a phone push
          and stays readable without one. Only server-side Spotify actions
          (sync, playlists, queue) need it, so this is a banner, not a gate. */}
      {serverMode && !authenticated && (
        <div className="animate-slide-down" style={{ borderBottom: '1px solid #333333', background: '#191414' }}>
          <div className="max-w-screen-xl mx-auto px-6 py-3 flex items-center gap-4 flex-wrap">
            <div className="flex-1" style={{ minWidth: 240 }}>
              <div className="font-display text-sm font-semibold">Spotify isn't linked</div>
              <div className="font-mono text-[0.65rem] text-muted">
                Showing this account's library. Push from your phone any time — link
                Spotify only for server-side sync, playlists and the queue.
              </div>
            </div>
            <button className="btn btn-primary btn-sm" onClick={signIn} disabled={signingIn}>
              {signingIn ? 'Opening Spotify…' : 'Connect Spotify'}
            </button>
          </div>
        </div>
      )}

      {/* The pipeline panel is a server-side view, kept on the Library tab. In
          local mode there is nothing to show, so it gets a pipeline with no
          activity, no stale "last sync" restored from localStorage and no
          server-side history line (the hook refuses to keep one while disabled). */}
      {activeTab === 'library' && (
        <SyncPanel
          pipeline={ds.isLocal ? { ...pipeline, hasActivity: false, lastSync: null } : pipeline}
          imagesJob={!ds.isLocal && imagesJob.job ? imagesJob : null}
          loadJob={!ds.isLocal && loadJob.job ? loadJob : null}
          spotifyLinked={authenticated}
        />
      )}

      {!ds.isLocal && !online && (
        <div className="max-w-screen-xl mx-auto px-6 pt-4">
          <div className="font-mono text-xs" style={{ color: '#E22134', border: '1px solid #E22134', padding: '8px 12px', borderRadius: 6 }}>
            Offline — media-server mode needs a connection. Switch to “On this device” in Settings → Server to browse locally.
          </div>
        </div>
      )}

      <main className="flex-1 max-w-screen-xl mx-auto w-full px-6 py-8">
        {activeTab === 'playlists' && serverMode ? (
          <PlaylistDashboard
            onExit={() => switchTab('library')}
            onToast={showToast}
            spotifyLinked={authenticated}
          />
        ) : activeTab === 'player' ? (
          <PlayerView ds={ds} onToast={showToast} />
        ) : activeTab === 'tools' && serverMode ? (
          <ToolsView onToast={showToast} spotifyLinked={authenticated} ds={ds} />
        ) : activeTab === 'stats' ? (
          <div className="stats-tab">
            <h1 className="font-display text-2xl font-semibold mb-5">Stats</h1>
            <StatsBar stats={stats} />
            <StatsPanel stats={stats} defaultOpen />
          </div>
        ) : activeTab === 'settings' ? (
          <SettingsView
            ds={ds} onToast={showToast}
            autoExport={autoExport} onToggleAutoExport={handleToggleAutoExport}
            imagesJob={imagesJob} loadJob={loadJob} pipelineRunning={pipeline.isRunning}
            autohideNav={autohideNav} onToggleAutohide={() => setAutohideNav((v) => !v)}
            autohideBoardBar={autohideBoardBar} onToggleBoardAutohide={() => setAutohideBoardBar((v) => !v)}
          />
        ) : (
        <div className="flex gap-0">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, flex: '1 1 0', minWidth: 0 }}>

          <FilterSidebar
            filters={filters}
            onChange={handleFilterChange}
            artists={artists}
            open={sidebarOpen}
            onToggle={handleSidebarToggle}
          />
          <div className="flex-1 min-w-0 pl-5">
            <div className="flex items-center justify-between mb-5 gap-4 flex-wrap"
                 style={{ transition: 'opacity 0.2s, transform 0.2s',
                          opacity: boardBarVisible ? 1 : 0.35,
                          transform: boardBarVisible ? 'translateY(0)' : 'translateY(-6px)',
                          pointerEvents: boardBarVisible ? 'auto' : 'none' }}>
              <h1 className="font-display text-2xl font-semibold flex-shrink-0">
                {hasFilters ? 'Results' : 'Your Library'}
              </h1>
              <div className="flex items-center gap-4 ml-auto">
                {!loading && total > 0 && (
                  <span className="font-mono text-[0.65rem] text-muted hidden sm:block">
                    {total.toLocaleString()} album{total !== 1 ? 's' : ''}
                  </span>
                )}
                <ViewToolbar
                  viewMode={viewMode} setViewMode={handleViewMode}
                  columns={columns}   setColumns={handleColumns}
                  sort={sort}         setSort={handleSort}
                />
              </div>
            </div>

            {visible.length > 0 && (
              <div className="flex items-center justify-between mb-3">
                <button className="btn btn-ghost btn-sm" onClick={handleToggleAllVisible}>
                  {allVisibleSelected
                    ? `Deselect ${visible.length} shown`
                    : `Select all ${visible.length} shown`}
                </button>
                {selectedIds.size > 0 && (
                  <span className="font-mono text-[0.65rem] text-muted">
                    {selectedIds.size} selected
                  </span>
                )}
              </div>
            )}

            <AlbumGrid
              albums={visible}
              loading={loading && visible.length === 0}
              hasFilters={hasFilters}
              viewMode={viewMode}
              columns={columns}
              selectedIds={selectedIds}
              onToggleSelect={handleToggleSelect}
              onShowTracks={(album) => setTrackAlbum({ ...album, id: album.spotify_id || album.id })}
            />

            {visible.length > 0 && visible.length < total && (
              <div ref={sentinelRef} aria-hidden="true" style={{ height: 1 }} />
            )}
            {loading && visible.length > 0 && (
              <div className="flex justify-center py-6">
                <span className="font-mono text-xs text-muted animate-pulse-soft">Loading more…</span>
              </div>
            )}
          </div>
    </div>
        </div>
        )}
      </main>

      <footer className="border-t border-border py-5">
        <div className="max-w-screen-xl mx-auto px-6 flex items-center justify-between">
          <span className="font-display italic text-muted text-sm">reSpotIt</span>
          <span className="font-mono text-[0.6rem] text-muted uppercase tracking-widest">
            Spotify Library Dashboard
          </span>
        </div>
      </footer>

      <SelectionToolbar
        selectedIds={selectedIds}
        onClear={() => setSelectedIds(new Set())}
        onOpenModal={setModalMode}
        onToast={showToast}
        localMode={ds.isLocal}
        spotifyLinked={authenticated}
      />

      <Toasts toasts={toasts} />

      {trackAlbum && (
        <AlbumTrackSheet album={trackAlbum} onClose={() => setTrackAlbum(null)} onToast={showToast} />
      )}

      {modalMode && (
        <PlaylistModal
          mode={modalMode}
          albumIds={[...selectedIds]}
          localMode={ds.isLocal}
          onClose={() => setModalMode(null)}
        />
      )}

      {/* Bottom tab bar — the fleet IA: Library / Playlists (server only) /
          Stats / Settings. Fixed; the page reserves room via pb-16. */}
      <nav className="bottom-tabs" aria-label="Main navigation"
           style={{ transform: navVisible ? 'translateY(0)' : 'translateY(100%)',
                    transition: 'transform 0.2s ease' }}>
        <button
          className={'bottom-tab' + (activeTab === 'library' ? ' active' : '')}
          onClick={() => switchTab('library')}
        >
          Library
        </button>
        {serverMode && (
          <button
            className={'bottom-tab' + (activeTab === 'playlists' ? ' active' : '')}
            onClick={() => switchTab('playlists')}
          >
            Playlists
          </button>
        )}
        <button
          className={'bottom-tab' + (activeTab === 'player' ? ' active' : '')}
          onClick={() => switchTab('player')}
        >
          Player
        </button>
        {serverMode && (
          <button
            className={'bottom-tab' + (activeTab === 'tools' ? ' active' : '')}
            onClick={() => switchTab('tools')}
          >
            Tools
          </button>
        )}
        <button
          className={'bottom-tab' + (activeTab === 'stats' ? ' active' : '')}
          onClick={() => switchTab('stats')}
        >
          Stats
        </button>
        <button
          className={'bottom-tab' + (activeTab === 'settings' ? ' active' : '')}
          onClick={() => switchTab('settings')}
        >
          Settings
        </button>
      </nav>
    </div>
  )
}
