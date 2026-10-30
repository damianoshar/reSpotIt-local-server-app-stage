/**
 * Spotify outbound links — one place, shared by every card that links out.
 *
 * The server sends `spotify_url` on library albums, but not every surface
 * carries it (playlist-cache albums, CSV imports), so fall back to building
 * the canonical URL from the id. Only a 22-char base62 string is a Spotify id;
 * anything else (CSV ids like "SP1") gets no link rather than a dead one.
 *
 * Mirrors `utils/spotifyLinks.ts` in the windows/csharp frontends.
 */

const SPOTIFY_ID = /^[A-Za-z0-9]{22}$/

/** Best link for an album: the server's spotify_url, else built from the id. */
export function spotifyAlbumUrl(album) {
  if (album?.spotify_url) return album.spotify_url
  const id = album?.spotify_id || album?.id
  return typeof id === 'string' && SPOTIFY_ID.test(id)
    ? `https://open.spotify.com/album/${id}`
    : ''
}

/** Playlist cards link out to open.spotify.com; non-Spotify ids get no link. */
export function spotifyPlaylistUrl(id) {
  return typeof id === 'string' && SPOTIFY_ID.test(id)
    ? `https://open.spotify.com/playlist/${id}`
    : ''
}
