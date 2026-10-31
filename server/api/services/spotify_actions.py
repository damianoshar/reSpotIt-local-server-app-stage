"""
services/spotify_actions.py
----------------------------
Playlist and queue operations against the Spotify Web API.
"""

import time
import requests

BASE = "https://api.spotify.com/v1"


def _request(method: str, token: str, path: str, **kwargs) -> requests.Response:
    """Single entry point for all Spotify API calls with rate-limit and error handling."""
    url = path if path.startswith("http") else f"{BASE}{path}"
    while True:
        resp = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            **kwargs,
        )
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", 3)))
            continue
        if resp.status_code == 403:
            raise PermissionError(
                "Spotify returned 403. Re-authorise via DELETE /auth/token then /auth/login."
            )
        if resp.status_code == 404 and "player" in url:
            raise ValueError("No active Spotify player. Open Spotify on any device first.")
        resp.raise_for_status()
        return resp


def _get(token: str, path: str, **kwargs) -> dict:
    return _request("GET", token, path, **kwargs).json()


def _post(token: str, path: str, **kwargs) -> requests.Response:
    return _request("POST", token, path, **kwargs)


# ── User ──────────────────────────────────────────────────────────────────────

def get_current_user(token: str) -> dict:
    return _get(token, "/me")


# ── Playlists ─────────────────────────────────────────────────────────────────

def get_user_playlists(token: str) -> list[dict]:
    playlists, url, params = [], "/me/playlists", {"limit": 50}
    # Spotify exposes no date field on a playlist, but returns /me/playlists
    # in recency order (newest first). Record that position as added_order so
    # the dashboard can sort by "Date Added" without fabricating timestamps.
    order = 0
    while url:
        data = _get(token, url, params=params)
        for p in data.get("items") or []:
            if p:
                playlists.append({
                    "id":          p["id"],
                    "name":        p["name"],
                    "track_count": p["tracks"]["total"],
                    "image_url":   p["images"][0]["url"] if p.get("images") else None,
                    "public":      p.get("public", False),
                    "owner":       p["owner"]["display_name"],
                    "added_order": order,
                })
                order += 1
        url, params = data.get("next"), {}
    return playlists


def get_playlist(token: str, playlist_id: str) -> dict:
    return _get(token, f"/playlists/{playlist_id}")


def get_playlist_tracks(token: str, playlist_id: str) -> list[dict]:
    """All tracks with the album info needed for dedup + caching."""
    tracks, url, params = [], f"/playlists/{playlist_id}/tracks", {
        "limit": 100,
        "fields": "items(track(id,name,duration_ms,track_number,artists,"
                 "album(id,name,images,release_date))),next,total",
    }
    while url:
        data = _get(token, url, params=params)
        for item in data.get("items") or []:
            track = (item or {}).get("track") or {}
            if not isinstance(track, dict):
                continue
            album = track.get("album") or {}
            artists = ", ".join(
                a["name"] for a in (track.get("artists") or []) if a.get("name")
            )
            images = album.get("images") or []
            release_year = None
            release_date = album.get("release_date") or ""
            if len(release_date) >= 4 and release_date[:4].isdigit():
                release_year = int(release_date[:4])
            tracks.append({
                "spotify_id":       track.get("id"),
                "name":             track.get("name") or "",
                "artist_names":     artists,
                "album_spotify_id": album.get("id"),
                "album_name":       album.get("name") or "",
                "album_image_url":  (images[0].get("url") if images else None),
                "release_year":     release_year,
                "duration_ms":      track.get("duration_ms"),
                "track_number":     track.get("track_number"),
            })
        url, params = data.get("next"), {}
    return tracks


def create_playlist(token: str, name: str, description: str = "") -> dict:
    user = get_current_user(token)
    data = _post(token, f"/users/{user['id']}/playlists",
                 json={"name": name, "description": description, "public": False}).json()
    return {"id": data["id"], "name": data["name"], "url": data["external_urls"]["spotify"]}


def add_tracks_to_playlist(token: str, playlist_id: str, uris: list[str]) -> int:
    """Append items to a playlist.

    Uses Spotify's current ``/items`` endpoint (the old ``/tracks`` route is
    deprecated). The function name is kept for existing callers, but the body
    may contain both tracks and episodes.
    """
    for i in range(0, len(uris), 100):
        _post(token, f"/playlists/{playlist_id}/items", json={"uris": uris[i:i + 100]})
    return len(uris)


def remove_tracks_from_playlist(token: str, playlist_id: str, uris: list[str]) -> int:
    """Remove track URIs from a playlist (Spotify caps each call at 100).

    Uses the current ``/items`` route and its ``items`` body. The old
    ``/tracks`` remove endpoint is deprecated alongside the add route.
    """
    removed = 0
    for i in range(0, len(uris), 100):
        chunk = uris[i:i + 100]
        _request(
            "DELETE", token, f"/playlists/{playlist_id}/items",
            json={"items": [{"uri": u} for u in chunk]},
        )
        removed += len(chunk)
    return removed


def unfollow_playlist(token: str, playlist_id: str) -> None:
    """Remove a playlist from the owner's library (Spotify has no hard delete).

    Idempotent: a 404 means the playlist is already gone (for example the owner
    removed it manually), which is the desired end state for retention sweeps
    and "delete now".
    """
    try:
        _request("DELETE", token, f"/playlists/{playlist_id}/followers")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return
        raise


# ── Album tracks ──────────────────────────────────────────────────────────────

def set_playlist_public(token: str, playlist_id: str, public: bool) -> None:
    _request(
        "PUT",
        token,
        f"/playlists/{playlist_id}",
        json={"public": public},
    ).raise_for_status()


def get_albums_track_uris(token: str, album_ids: list[str]) -> list[str]:
    uris = []
    for album_id in album_ids:
        url, params = f"{BASE}/albums/{album_id}/tracks", {"limit": 50}
        while url:
            data = _get(token, url, params=params)
            uris.extend(item["uri"] for item in (data.get("items") or []) if item)
            url, params = data.get("next"), {}
        time.sleep(0.15)
    return uris


def get_album_details(token: str, album_id: str) -> list[dict]:
    """Full track list for one album (album sheet + on-demand cache warming)."""
    album = _get(token, f"/albums/{album_id}")
    images = album.get("images") or []
    album_image_url = images[0].get("url") if images else None
    album_name = album.get("name") or ""
    release_date = album.get("release_date") or ""
    release_year = (int(release_date[:4])
                    if len(release_date) >= 4 and release_date[:4].isdigit() else None)
    album_artists = ", ".join(
        a["name"] for a in (album.get("artists") or []) if a.get("name")
    )

    out, url, params = [], f"/albums/{album_id}/tracks", {"limit": 50}
    while url:
        data = _get(token, url, params=params)
        for item in data.get("items") or []:
            if not item:
                continue
            out.append({
                "spotify_id":      item.get("id"),
                "name":            item.get("name") or "",
                "artist_names":    ", ".join(
                    a["name"] for a in (item.get("artists") or []) if a.get("name")
                ) or album_artists,
                "disc_number":     item.get("disc_number"),
                "track_number":    item.get("track_number"),
                "duration_ms":     item.get("duration_ms"),
                "uri":             item.get("uri"),
                "explicit":        bool(item.get("explicit")),
                "preview_url":     item.get("preview_url"),
                "album_name":      album_name,
                "album_image_url": album_image_url,
                "release_year":    release_year,
            })
        url, params = data.get("next"), {}
    return out


# ── Queue ─────────────────────────────────────────────────────────────────────

def queue_single_track(token: str, uri: str) -> None:
    """Queue one track URI (per-track errors propagate to the caller)."""
    _post(token, "/me/player/queue", params={"uri": uri})


def add_to_queue(token: str, uris: list[str]) -> int:
    for uri in uris:
        queue_single_track(token, uri)
        time.sleep(0.1)
    return len(uris)


# ── Library follow / save helpers ─────────────────────────────────────────────

def _paginated_get(token: str, path: str, params: dict | None = None) -> list[dict]:
    items = []
    url = path
    p = dict(params or {})
    while url:
        data = _get(token, url, params=p)
        batch = data.get("items") or []
        items.extend(batch)
        url = data.get("next")
        p = {}
        if url and not url.startswith("http"):
            url = f"{BASE}{url}"
    return items


def follow_artists_from_saved_albums(token: str) -> dict:
    artist_ids = set()
    for item in _paginated_get(token, "/me/albums", {"limit": 50}):
        for artist in (item.get("album") or {}).get("artists") or []:
            if artist.get("id"):
                artist_ids.add(artist["id"])

    followed = set()
    ids = sorted(artist_ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        result = _get(token, "/me/following/contains", params={"type": "artist", "ids": ",".join(chunk)})
        for artist_id, is_followed in zip(chunk, result or []):
            if is_followed:
                followed.add(artist_id)

    to_follow = [artist_id for artist_id in ids if artist_id not in followed]
    for i in range(0, len(to_follow), 50):
        chunk = to_follow[i:i + 50]
        _request("PUT", token, "/me/following", params={"type": "artist"}, json={"ids": chunk})

    return {
        "total": len(ids),
        "already_followed": len(followed),
        "followed": len(to_follow),
    }


def remove_saved_albums(token: str, album_ids: list[str]) -> int:
    removed = 0
    for i in range(0, len(album_ids), 50):
        chunk = album_ids[i:i + 50]
        _request("DELETE", token, "/me/albums", params={"ids": ",".join(chunk)})
        removed += len(chunk)
    return removed


def save_saved_albums(token: str, album_ids: list[str]) -> int:
    saved = 0
    for i in range(0, len(album_ids), 50):
        chunk = album_ids[i:i + 50]
        _request("PUT", token, "/me/albums", params={"ids": ",".join(chunk)})
        saved += len(chunk)
    return saved


def search_spotify_catalog(token: str, query: str, limit: int = 8) -> dict:
    data = _get(token, "/search", params={"q": query, "type": "artist,album", "limit": limit})
    artists = []
    for artist in (data.get("artists") or {}).get("items") or []:
        images = artist.get("images") or []
        artists.append({
            "id": artist.get("id"),
            "name": artist.get("name") or "Unknown artist",
            "image_url": (images[0].get("url") if images else "") or "",
            "genres": artist.get("genres") or [],
            "followers": (artist.get("followers") or {}).get("total", 0),
        })
    albums = []
    for album in (data.get("albums") or {}).get("items") or []:
        images = album.get("images") or []
        artists_list = album.get("artists") or []
        year = None
        release_date = album.get("release_date") or ""
        if len(release_date) >= 4 and release_date[:4].isdigit():
            year = int(release_date[:4])
        albums.append({
            "id": album.get("id"),
            "title": album.get("name") or "Unknown title",
            "artist": ", ".join(a.get("name", "") for a in artists_list if a.get("name")) or "Unknown artist",
            "artist_ids": [a.get("id") for a in artists_list if a.get("id")],
            "year": year or 0,
            "genre": "",
            "image_url": (images[0].get("url") if images else "") or "",
            "album_type": album.get("album_type") or "",
            "total_tracks": album.get("total_tracks") or 0,
            "spotify_url": (album.get("external_urls") or {}).get("spotify") or "",
        })
    return {"artists": artists, "albums": albums}


def get_artist_albums(token: str, artist_id: str) -> list[dict]:
    albums = []
    url = f"/artists/{artist_id}/albums"
    params = {"include_groups": "album,single,appears_on,compilation", "limit": 50, "offset": 0}
    while url:
        data = _get(token, url, params=params)
        for album in data.get("items") or []:
            images = album.get("images") or []
            artists_list = album.get("artists") or []
            release_date = album.get("release_date") or ""
            year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else 0
            albums.append({
                "id": album.get("id"),
                "title": album.get("name") or "Unknown title",
                "artist": ", ".join(a.get("name", "") for a in artists_list if a.get("name")) or "Unknown artist",
                "artist_ids": [a.get("id") for a in artists_list if a.get("id")],
                "year": year,
                "genre": "",
                "image_url": (images[0].get("url") if images else "") or "",
                "album_type": album.get("album_type") or "",
                "album_group": album.get("album_group") or album.get("album_type") or "",
                "total_tracks": album.get("total_tracks") or 0,
                "spotify_url": (album.get("external_urls") or {}).get("spotify") or "",
            })
        url = data.get("next")
        params = {}
        if url and not url.startswith("http"):
            url = f"{BASE}{url}"
    by_id = {}
    for album in albums:
        by_id.setdefault(album["id"], album)
    return list(by_id.values())


def get_spotify_albums(token: str, album_ids: list[str]) -> list[dict]:
    out = []
    for album_id in album_ids:
        album = _get(token, f"/albums/{album_id}")
        images = album.get("images") or []
        artists_list = album.get("artists") or []
        release_date = album.get("release_date") or ""
        year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else 0
        out.append({
            "id": album.get("id"),
            "title": album.get("name") or "Unknown title",
            "artist": ", ".join(a.get("name", "") for a in artists_list if a.get("name")) or "Unknown artist",
            "artist_ids": [a.get("id") for a in artists_list if a.get("id")],
            "year": year,
            "genre": "",
            "image_url": (images[0].get("url") if images else "") or "",
            "album_type": album.get("album_type") or "",
            "total_tracks": album.get("total_tracks") or 0,
            "spotify_url": (album.get("external_urls") or {}).get("spotify") or "",
        })
    return out

# --- Player helpers ---

def get_player_state(token: str) -> dict:
    resp = _request("GET", token, "/me/player")
    if resp.status_code == 204:
        return {}
    return resp.json()


def get_player_queue(token: str) -> dict:
    resp = _request("GET", token, "/me/player/queue")
    if resp.status_code == 204:
        return {"queue": []}
    return resp.json()
