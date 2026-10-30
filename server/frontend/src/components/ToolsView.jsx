import { useState } from 'react'
import { api } from '../api/client'
import { useLocalSpotify } from '../hooks/useLocalSpotify'
import * as localSpotify from '../services/localSpotify'
import { AddFromSiteDialog } from './AddFromSiteDialog'
import { ArtistDiscographyDialog } from './ArtistDiscographyDialog'

export function ToolsView({ onToast, spotifyLinked = true, ds }) {
  const local = useLocalSpotify()
  const isLocal = !!ds?.isLocal
  const linked = isLocal ? local.linked : spotifyLinked
  const [followBusy, setFollowBusy] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [discOpen, setDiscOpen] = useState(false)

  const handleFollow = async () => {
    if (!window.confirm('Follow all artists from your saved Spotify albums that you do not already follow?')) return
    setFollowBusy(true)
    try {
      const res = isLocal
        ? await localSpotify.followArtistsFromSavedAlbums()
        : await api.followArtistsFromLibrary()
      onToast?.(
        `Followed ${res.followed} new artist(s) (${res.already_followed} already, ${res.total} total).`,
        true,
      )
    } catch (e) {
      onToast?.(e?.message || 'Could not follow artists.', false)
    } finally {
      setFollowBusy(false)
    }
  }

  const handleConnect = async () => {
    try {
      const { startLocalSpotifyAuth } = await import('../services/spotifyAuth')
      await startLocalSpotifyAuth()
    } catch (e) {
      onToast?.(e?.message || 'Could not start Spotify login.', false)
    }
  }

  return (
    <div className="tools-tab">
      <section className="settings-section" style={{ width: '100%' }}>
        <h3 className="settings-heading">Library tools</h3>
        <p className="settings-sub">
          Server-side Spotify actions for the linked account.
        </p>
        {isLocal && !linked && (
          <button className="btn btn-primary full-width" style={{ marginBottom: '0.75rem' }} onClick={handleConnect}>
            Connect Spotify on this device
          </button>
        )}
        <button className="btn btn-ghost full-width" onClick={handleFollow} disabled={followBusy || !linked}>
          {followBusy ? 'Following artists…' : 'Follow artists from saved Spotify albums'}
        </button>
        <button className="btn btn-ghost full-width" style={{ marginTop: '0.5rem' }}
                onClick={() => setAddOpen(true)} disabled={!linked}>
          Add albums from a website
        </button>
      </section>

      <section className="settings-section" style={{ width: '100%', marginTop: '1.5rem' }}>
        <h3 className="settings-heading">Spotify playlist tools</h3>
        <p className="settings-sub">
          Search Spotify, inspect an artist discography, then create a private playlist or save albums.
        </p>
        <button className="btn btn-ghost full-width" onClick={() => setDiscOpen(true)} disabled={!linked}>
          Artist discography &amp; playlist
        </button>
      </section>

      {addOpen && (
        <AddFromSiteDialog open={addOpen} onClose={() => setAddOpen(false)}
                           onToast={onToast} localMode={isLocal} />
      )}
      {discOpen && (
        <ArtistDiscographyDialog open={discOpen} onClose={() => setDiscOpen(false)}
                                 onToast={onToast} localMode={isLocal} />
      )}
    </div>
  )
}
