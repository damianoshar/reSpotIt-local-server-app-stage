/**
 * SettingsView — the Settings tab's content.
 *
 * V-pass IA (Library / Playlists / Stats / Settings) folds the two standalone
 * surfaces that used to sit outside any tab into sections:
 *   Backup — the ExportSection strip (export + history + auto-export).
 *   Server — the DataSourcePanel (mode, server URL, test, local library
 *            import/export/clear) plus the server-side Covers/DB jobs, which
 *            are backend-coupled and therefore stay server-only.
 */
import React, { useState } from 'react'
import { ExportSection } from './ExportSection'
import { DataSourcePanel } from './DataSourceModal'
import { readSyncPhotos, writeSyncPhotos, useSyncPhotos } from '../hooks/useSyncPhotos'
import { useLocalSpotify } from '../hooks/useLocalSpotify'
import { api } from '../api/client'
import { SpotifyCredentialsSection } from './SpotifyCredentialsSection'
import { queryAlbums } from '../services/localDatabase'
import { findDuplicates } from '../utils/duplicateFinder'
import {
  getHiddenDuplicateIds, hideDuplicateIds, restoreHiddenDuplicates,
} from '../utils/duplicateBlocklist'

const LABEL = {
  fontFamily: 'Space Mono, monospace', fontSize: '0.65rem',
  textTransform: 'uppercase', letterSpacing: '0.16em', color: '#B3B3B3',
}

export function SettingsView({
  ds, onToast,
  autoExport = false, onToggleAutoExport,
  imagesJob = null, loadJob = null, pipelineRunning = false,
  autohideNav = true, onToggleAutohide,
  autohideBoardBar = false, onToggleBoardAutohide,
}) {
  const [syncPhotos, toggleSyncPhotos] = useSyncPhotos()
  const localSpotify = useLocalSpotify()
  const [dupesOpen, setDupesOpen] = useState(false)
  const [dupGroups, setDupGroups] = useState([])
  const [dupLoading, setDupLoading] = useState(false)
  const [hiddenCount, setHiddenCount] = useState(getHiddenDuplicateIds().size)

  const openDuplicates = async () => {
    setDupLoading(true)
    try {
      const hidden = getHiddenDuplicateIds()
      let items = []
      if (ds.isLocal) {
        const res = await queryAlbums({}, 1, 100000)
        items = res?.items || []
      } else {
        let page = 1
        while (page <= 200) {
          const res = await api.getAlbums({ page, limit: 200 })
          const batch = res?.items || res?.albums || []
          items = items.concat(batch)
          if (batch.length === 0 || batch.length < 500) break
          if (res?.total && items.length >= res.total) break
          page += 1
        }
      }
      const groups = findDuplicates(items.filter((a) => !hidden.has(a.spotify_id || a.id)))
      setDupGroups(groups)
      setHiddenCount(hidden.size)
      setDupesOpen(true)
    } catch (e) {
      onToast && onToast('Duplicate scan failed.', false)
    } finally {
      setDupLoading(false)
    }
  }

  const handleHideDuplicates = (ids) => {
    hideDuplicateIds(ids)
    setHiddenCount(getHiddenDuplicateIds().size)
    setDupesOpen(false)
  }

  const handlePermanentDuplicates = async (ids) => {
    try {
      await api.removeSavedAlbums(ids)
      hideDuplicateIds(ids)
      setHiddenCount(getHiddenDuplicateIds().size)
      setDupGroups((groups) => groups.map((group) => ({
        ...group,
        albums: group.albums.filter((album) => !ids.includes(album.id)),
      })).filter((group) => group.albums.length > 1))
      onToast && onToast(`Permanently removed ${ids.length} duplicate album(s) from Spotify.`, true)
    } catch (e) {
      onToast && onToast(e?.message || 'Could not remove albums from Spotify.', false)
    }
  }

  const restoreDuplicates = () => {
    restoreHiddenDuplicates()
    setHiddenCount(0)
  }

  const connectLocalSpotify = async () => {
    try {
      const { startLocalSpotifyAuth } = await import('../services/spotifyAuth')
      await startLocalSpotifyAuth()
    } catch (e) {
      onToast && onToast(e?.message || 'Could not start Spotify login.', false)
    }
  }
  return (
    <div className="settings-page">
      <h1 className="font-display text-2xl font-semibold mb-6">Settings</h1>

      <section className="mb-8">
        <h2 className="font-display text-lg font-semibold mb-1">Backup</h2>
        <p className="text-xs text-muted mb-3">
          Export your whole library to CSV — or let it back up automatically after a sync
          that inserts albums.
        </p>
        <ExportSection
          onToast={onToast}
          ds={ds}
          autoExport={autoExport}
          onToggleAutoExport={onToggleAutoExport}
        />
      </section>

      <section className="mb-8">
        <h2 className="font-display text-lg font-semibold mb-1">Display</h2>
        <p className="text-xs text-muted mb-3">
          Turn artwork off on low-RAM or battery-limited devices. Icons and placeholder
          graphics remain visible.
        </p>
        <div className="rounded-lg border border-border bg-panel px-5 py-4">
          <label className="flex items-center gap-3" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={syncPhotos}
              onChange={(e) => toggleSyncPhotos(e.target.checked)}
            />
            <span className="text-sm text-ink">Load and render artwork (Sync photos)</span>
            <span className="text-xs text-muted">Default: on. Off hides cover thumbnails and avoids fetching image files.</span>
          </label>
          {onToggleAutohide && (
            <label className="flex items-center gap-3 mt-3" style={{ cursor: 'pointer' }}>
              <input type="checkbox" checked={autohideNav} onChange={(e) => onToggleAutohide(e.target.checked)} />
              <span className="text-sm text-ink">Hide the bottom bar while scrolling down</span>
            </label>
          )}
          {onToggleBoardAutohide && (
            <label className="flex items-center gap-3 mt-3" style={{ cursor: 'pointer' }}>
              <input type="checkbox" checked={autohideBoardBar} onChange={(e) => onToggleBoardAutohide(e.target.checked)} />
              <span className="text-sm text-ink">Autohide the search/sort bar while scrolling down</span>
            </label>
          )}
        </div>
      </section>

      {ds.isLocal && (
        <section className="mb-8">
          <h2 className="font-display text-lg font-semibold mb-1">Spotify on this device</h2>
          <p className="text-xs text-muted mb-3">
            Local mode uses a direct Spotify login on this browser for playlists, the queue and Tools.
          </p>
          <div className="rounded-lg border border-border bg-panel px-5 py-4">
            {localSpotify.linked ? (
              <div className="flex items-center gap-3">
                <span className="text-sm text-ink">Spotify connected on this device</span>
                <button className="btn btn-ghost btn-sm" onClick={async () => {
                  const { clearLocalSpotifyTokens } = await import('../services/spotifyAuth')
                  clearLocalSpotifyTokens()
                }}>Disconnect</button>
              </div>
            ) : (
              <button className="btn btn-primary btn-sm" onClick={connectLocalSpotify}>
                Connect Spotify
              </button>
            )}
          </div>
        </section>
      )}

      <section className="mb-8">
        <h2 className="font-display text-lg font-semibold mb-1">Server</h2>
        <p className="text-xs text-muted mb-3">
          Choose whether your library lives on this device or on your media server, and
          manage the connection.
        </p>
        <div className="rounded-lg border border-border bg-panel px-5 py-4">
          <DataSourcePanel ds={ds} onToast={onToast} />
        </div>

        {!ds.isLocal && (
          <div className="mt-4">
            <div style={LABEL} className="mb-2">Server jobs</div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                className="btn btn-ghost btn-sm"
                title="Download missing cover art from CSV"
                onClick={imagesJob?.start}
                disabled={imagesJob?.isRunning || pipelineRunning}
              >
                {imagesJob?.isRunning ? '⟳' : '⬚'} Covers — refresh missing art
              </button>
              <button
                className="btn btn-ghost btn-sm"
                title="Re-load the database from the CSV file"
                onClick={loadJob?.start}
                disabled={loadJob?.isRunning || pipelineRunning}
              >
                {loadJob?.isRunning ? '⟳' : '⬡'} DB — reload from CSV
              </button>
            </div>
            <p className="text-xs text-muted mt-2">
              Progress and the sync history show on the Library tab, next to ↓ Sync / ⌦ Clean.
            </p>
          </div>
        )}
      </section>

      <section className="mb-8">
        <h2 className="font-display text-lg font-semibold mb-1">Duplicates</h2>
        <p className="text-xs text-muted mb-3">
          Review albums that normalise to the same title and primary artist. Cancelling duplicates
          hides them from the current library; they remain in Spotify.
        </p>
        <div className="rounded-lg border border-border bg-panel px-5 py-4">
          <div className="flex items-center gap-2 flex-wrap">
            <button className="btn btn-ghost btn-sm" onClick={openDuplicates} disabled={dupLoading}>
              {dupLoading ? 'Scanning...' : 'Find duplicates'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={restoreDuplicates} disabled={hiddenCount === 0}>
              Restore hidden ({hiddenCount})
            </button>
          </div>
          {!ds.isLocal && (
            <p className="text-xs text-muted mt-3">
              Remote review scans the server library and stores hidden duplicate IDs in this browser; it is not a server-side deletion.
            </p>
          )}
        </div>
      </section>

      <SpotifyCredentialsSection />

      <DuplicatesDialog
        open={dupesOpen}
        groups={dupGroups}
        hiddenCount={hiddenCount}
        loading={dupLoading}
        isRemote={!ds.isLocal}
        onDismiss={() => setDupesOpen(false)}
        onHide={handleHideDuplicates}
        onRemovePermanent={handlePermanentDuplicates}
        onRestore={() => { restoreDuplicates(); openDuplicates().catch(() => {}) }}
      />
    </div>
  )
}
