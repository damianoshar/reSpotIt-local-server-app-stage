import { getLocalSpotifyToken, hasLocalSpotify } from './spotifyAuth'

const API = 'https://api.spotify.com/v1'

async function spotifyFetch(path, options = {}) {
  const token = await getLocalSpotifyToken()
  if (!token) throw new Error('Spotify is not connected on this device.')
  const url = path.startsWith('http') ? path : `${API}${path}`
  const res = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  if (!res.ok) throw new Error(`Spotify request failed (${res.status})`)
  if (res.status === 204) return null
  return res.json()
}

function chunks(items, size) {
  const out = []
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
  return out
}

export { hasLocalSpotify }

export async function getLocalSpotifyUser() {
  return spotifyFetch('/me')
}

export async function getSavedAlbumArtistIds() {
  const ids = new Set()
  let url = '/me/albums?limit=50'
  while (url) {
    const data = await spotifyFetch(url)
    for (const item of data.items || []) {
      for (const artist of item.album?.artists || []) {
        if (artist.id) ids.add(artist.id)
      }
    }
    url = data.next
    if (url && !url.startsWith('http')) url = `${API}${url}`
  }
  return [...ids]
}

export async function areArtistsFollowed(ids) {
  const followed = new Set()
  for (const chunk of chunks(ids, 50)) {
    const data = await spotifyFetch(`/me/following/contains?type=artist&ids=${encodeURIComponent(chunk.join(','))}`)
    chunk.forEach((id, index) => {
      if (data[index]) followed.add(id)
    })
  }
  return followed
}

export async function followArtists(ids) {
  for (const chunk of chunks(ids, 50)) {
    await spotifyFetch('/me/following?type=artist', {
      method: 'PUT',
      body: JSON.stringify({ ids: chunk }),
    })
  }
}

export async function removeSavedAlbums(ids) {
  for (const chunk of chunks(ids, 50)) {
    await spotifyFetch(`/me/albums?ids=${encodeURIComponent(chunk.join(','))}`, { method: 'DELETE' })
  }
}

export async function saveAlbums(ids) {
  for (const chunk of chunks(ids, 50)) {
    await spotifyFetch(`/me/albums?ids=${encodeURIComponent(chunk.join(','))}`, { method: 'PUT' })
  }
}

export async function searchSpotifyCatalog(query, limit = 8) {
  const params = new URLSearchParams({ q: query, type: 'artist,album', limit: String(limit) })
  const data = await spotifyFetch(`/search?${params}`)
  return {
    artists: (data.artists?.items || []).filter((a) => a.id).map((a) => ({
      id: a.id,
      name: a.name || 'Unknown artist',
      image_url: a.images?.[0]?.url || '',
      genres: a.genres || [],
      followers: a.followers?.total || 0,
    })),
    albums: (data.albums?.items || []).filter((a) => a.id).map((a) => ({
      id: a.id,
      title: a.name || 'Unknown title',
      artist: (a.artists || []).map((x) => x.name).filter(Boolean).join(', ') || 'Unknown artist',
      artist_ids: (a.artists || []).map((x) => x.id).filter(Boolean),
      year: /^\d{4}/.test(a.release_date || '') ? Number(a.release_date.slice(0, 4)) : 0,
      genre: a.genres?.[0] || '',
      image_url: a.images?.[0]?.url || '',
      album_type: a.album_type || '',
      total_tracks: a.total_tracks || 0,
      spotify_url: a.external_urls?.spotify || '',
    })),
  }
}

export async function getArtistAlbums(artistId) {
  const albums = []
  const seen = new Set()
  let url = `/artists/${encodeURIComponent(artistId)}/albums?include_groups=album,single,appears_on,compilation&limit=50`
  while (url) {
    const data = await spotifyFetch(url)
    for (const album of data.items || []) {
      if (seen.has(album.id)) continue
      seen.add(album.id)
      const release = album.release_date || ''
      albums.push({
        id: album.id,
        title: album.name || 'Unknown title',
        artist: (album.artists || []).map((a) => a.name).filter(Boolean).join(', ') || 'Unknown artist',
        artist_ids: (album.artists || []).map((a) => a.id).filter(Boolean),
        year: /^\d{4}/.test(release) ? Number(release.slice(0, 4)) : 0,
        genre: '',
        image_url: album.images?.[0]?.url || '',
        album_type: album.album_type || '',
        album_group: album.album_group || album.album_type || '',
        total_tracks: album.total_tracks || 0,
        spotify_url: album.external_urls?.spotify || '',
      })
    }
    url = data.next
    if (url && !url.startsWith('http')) url = `${API}${url}`
  }
  return albums
}

export async function getSpotifyAlbums(ids) {
  const albums = []
  for (const id of ids) {
    const album = await spotifyFetch(`/albums/${encodeURIComponent(id)}`)
    const release = album.release_date || ''
    albums.push({
      id: album.id,
      title: album.name || 'Unknown title',
      artist: (album.artists || []).map((a) => a.name).filter(Boolean).join(', ') || 'Unknown artist',
      artist_ids: (album.artists || []).map((a) => a.id).filter(Boolean),
      year: /^\d{4}/.test(release) ? Number(release.slice(0, 4)) : 0,
      genre: (album.genres || [])[0] || '',
      image_url: album.images?.[0]?.url || '',
      album_type: album.album_type || '',
      total_tracks: album.total_tracks || 0,
      spotify_url: album.external_urls?.spotify || '',
    })
  }
  return albums
}

export async function getAlbumTracks(albumId) {
  const uris = []
  let url = `/albums/${encodeURIComponent(albumId)}/tracks?limit=50`
  while (url) {
    const data = await spotifyFetch(url)
    for (const item of data.items || []) {
      if (item.uri) uris.push(item.uri)
    }
    url = data.next
    if (url && !url.startsWith('http')) url = `${API}${url}`
  }
  return uris
}

export async function getUserPlaylists() {
  const playlists = []
  let url = '/me/playlists?limit=50'
  while (url) {
    const data = await spotifyFetch(url)
    for (const playlist of data.items || []) {
      if (playlist) playlists.push(playlist)
    }
    url = data.next
    if (url && !url.startsWith('http')) url = `${API}${url}`
  }
  return playlists
}

export async function createPlaylist(name, albumIds = []) {
  const user = await spotifyFetch('/me')
  const playlist = await spotifyFetch(`/users/${user.id}/playlists`, {
    method: 'POST',
    body: JSON.stringify({ name, public: false }),
  })
  if (albumIds.length) {
    const uris = []
    for (const id of albumIds) uris.push(...(await getAlbumTracks(id)))
    for (let i = 0; i < uris.length; i += 100) {
      await spotifyFetch(`/playlists/${playlist.id}/items`, {
        method: 'POST',
        body: JSON.stringify({ uris: uris.slice(i, i + 100) }),
      })
    }
  }
  return { ...playlist, playlist_name: playlist.name, tracks_added: albumIds.length ? 'tracks' : 0 }
}

export async function addAlbumsToPlaylist(playlistId, albumIds) {
  const uris = []
  for (const id of albumIds) uris.push(...(await getAlbumTracks(id)))
  let added = 0
  for (let i = 0; i < uris.length; i += 100) {
    await spotifyFetch(`/playlists/${playlistId}/items`, {
      method: 'POST',
      body: JSON.stringify({ uris: uris.slice(i, i + 100) }),
    })
    added += Math.min(100, uris.length - i)
  }
  return added
}

export async function queueAlbums(albumIds, onProgress) {
  const uris = []
  for (let i = 0; i < albumIds.length; i++) {
    onProgress?.(i, albumIds.length)
    uris.push(...(await getAlbumTracks(albumIds[i])))
  }
  onProgress?.(albumIds.length, albumIds.length)
  for (const uri of uris) {
    await spotifyFetch(`/me/player/queue?uri=${encodeURIComponent(uri)}`, { method: 'POST' })
  }
  return { queued: uris.length, failed: 0 }
}

export async function followArtistsFromSavedAlbums() {
  const artistIds = new Set()
  let url = '/me/albums?limit=50'
  while (url) {
    const data = await spotifyFetch(url)
    for (const item of data.items || []) {
      for (const artist of item.album?.artists || []) {
        if (artist.id) artistIds.add(artist.id)
      }
    }
    url = data.next
    if (url && !url.startsWith('http')) url = `${API}${url}`
  }
  const ids = [...artistIds]
  const followed = await areArtistsFollowed(ids)
  const toFollow = ids.filter((id) => !followed.has(id))
  await followArtists(toFollow)
  return { total: ids.length, already_followed: followed.size, followed: toFollow.length }
}