"""
services/spotify_actions.py
----------------------------
Playlist and queue operations against the Spotify Web API.
"""

import hashlib
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

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


# ---------------------------------------------------------------------------
# Phase 0 helpers for AI URL scan features
# ---------------------------------------------------------------------------

def _fetch_followed_artists(token: str) -> list[dict]:
    """Paginate /me/following for every artist the user follows."""
    artists: list[dict] = []
    url = "/me/following"
    params = {"type": "artist", "limit": 50}
    while url:
        data = _get(token, url, params=params)
        container = (data.get("artists") or {}) if isinstance(data, dict) else {}
        for artist in container.get("items") or []:
            if not isinstance(artist, dict):
                continue
            images = artist.get("images") or []
            artists.append({
                "id": artist.get("id"),
                "name": artist.get("name") or "Unknown artist",
                "image_url": (images[0].get("url") if images else "") or "",
                "genres": artist.get("genres") or [],
                "followers": (artist.get("followers") or {}).get("total", 0),
            })
        url = container.get("next")
        params = {}
        if url and not isinstance(url, str):
            url = None
        if url and not url.startswith("http"):
            url = f"{BASE}{url}"
    return artists


# /me/following is cursor-paginated: a user with 3,000+ artists costs ~64 serial
# Spotify calls. resolve_artists runs on every AI scan, so cache the list briefly
# to keep correlation fast (a warm scan then resolves in seconds, not a minute).
_FOLLOWED_TTL_SECONDS = 300.0
_followed_cache: dict[str, tuple[float, list[dict]]] = {}
_warming: set[str] = set()
_followed_cache_lock = threading.Lock()


def _followed_key(token: str) -> str:
    # Key by a hash of the bearer token so we never store a live credential.
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:32]


def get_followed_artists(token: str) -> list[dict]:
    """Return the user's followed Spotify artists (paginated, short-lived cache)."""
    key = _followed_key(token)
    now = time.time()
    with _followed_cache_lock:
        cached = _followed_cache.get(key)
        if cached and now - cached[0] < _FOLLOWED_TTL_SECONDS:
            return cached[1]
    artists = _fetch_followed_artists(token)
    with _followed_cache_lock:
        _followed_cache[key] = (time.time(), artists)
        if len(_followed_cache) > 8:
            oldest = min(_followed_cache, key=lambda k: _followed_cache[k][0])
            _followed_cache.pop(oldest, None)
    return artists


def invalidate_followed_artists(token: str | None = None) -> None:
    """Drop the followed-artists cache (all users, or one token's entry)."""
    with _followed_cache_lock:
        if token is None:
            _followed_cache.clear()
        else:
            _followed_cache.pop(_followed_key(token), None)


def _cached_followed_artists(token: str) -> list[dict] | None:
    """The cached followed list, or None when cold (never triggers pagination)."""
    with _followed_cache_lock:
        hit = _followed_cache.get(_followed_key(token))
    if hit and time.time() - hit[0] < _FOLLOWED_TTL_SECONDS:
        return hit[1]
    return None


def _warm_followed_artists(token: str) -> None:
    """Refresh the followed-artists cache in the background (best effort)."""
    key = _followed_key(token)
    with _followed_cache_lock:
        if key in _warming:
            return  # a warm is already in flight for this token
        _warming.add(key)

    def run() -> None:
        try:
            get_followed_artists(token)
        except Exception:
            pass  # warming is opportunistic; the caller already answered
        finally:
            with _followed_cache_lock:
                _warming.discard(key)

    threading.Thread(target=run, daemon=True, name="followed-warm").start()


def _followed_contains(token: str, artist_ids: list[str]) -> set[str]:
    """Authoritative check: which of these artist ids does the user follow?

    /me/following/contains takes 50 ids per call, so a scan page costs one or
    two calls instead of paginating the whole followed list.
    """
    ids = [i for i in dict.fromkeys(artist_ids) if i]
    followed: set[str] = set()
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            flags = _request(
                "GET", token, "/me/following/contains",
                params={"type": "artist", "ids": ",".join(chunk)},
            ).json()
        except Exception:
            continue
        if isinstance(flags, list):
            for j, flag in enumerate(flags):
                if flag:
                    followed.add(chunk[j])
    return followed


def _best_album_match(albums: list[dict], artist: str, album: str) -> dict | None:
    artist_l = (artist or "").strip().lower()
    album_l = (album or "").strip().lower()
    # Prefer exact title + artist match.
    for a in albums:
        if not isinstance(a, dict):
            continue
        if (a.get("title") or "").strip().lower() == album_l and \
           (artist_l == "" or artist_l in (a.get("artist") or "").strip().lower()):
            return a
    # Then exact title only.
    for a in albums:
        if not isinstance(a, dict):
            continue
        if (a.get("title") or "").strip().lower() == album_l:
            return a
    # Then first result whose artist matches.
    for a in albums:
        if not isinstance(a, dict):
            continue
        if artist_l and artist_l in (a.get("artist") or "").strip().lower():
            return a
    return albums[0] if albums and isinstance(albums[0], dict) else None


def resolve_albums(token: str, items: list) -> dict:
    """Resolve [{artist, album}] pairs to Spotify albums."""
    resolved = []
    unresolved = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        artist = str(item.get("artist") or "").strip()
        album = str(item.get("album") or "").strip()
        if not artist and not album:
            continue
        if artist and album:
            query = f'album:"{album}" artist:"{artist}"'
        elif album:
            query = f'album:"{album}"'
        else:
            query = artist
        try:
            data = search_spotify_catalog(token, query, limit=5)
        except Exception:
            data = {"albums": []}
        albums = (data or {}).get("albums") or []
        match = _best_album_match(albums, artist, album)
        if match:
            resolved.append({
                "artist": artist,
                "album": album,
                "spotify_id": match.get("id"),
                "title": match.get("title") or album,
                "artist_name": match.get("artist") or artist,
                "year": match.get("year") or 0,
                "image_url": match.get("image_url") or "",
                "spotify_url": match.get("spotify_url") or "",
            })
        else:
            unresolved.append({"artist": artist, "album": album})
    return {"resolved": resolved, "unresolved": unresolved}


def _best_artist_match(artists: list[dict], name: str) -> dict | None:
    """Return the catalog artist that really is `name`, else None.

    Matching is deliberately strict (same folded name, or the same name in the
    other script via transliteration). Spotify's search returns *something* for
    almost any query, so falling back to the first result used to map Greek
    event titles onto random artists. Unresolved is better than wrong.
    """
    wanted = set(_artist_keys(name))
    if not wanted:
        return None
    for a in artists:
        if isinstance(a, dict) and wanted.intersection(_artist_keys(a.get("name"))):
            return a
    return None


def _normalize_artist_name(name: str) -> str:
    """Fold a name to a comparable key that works for every script.

    NFKD + casefold removes case and accent differences (Σοφία / ΣΟΦΙΑ / Σοφια
    all collapse), and keeping only alphanumerics drops punctuation and spaces.
    Unlike the old [a-z0-9] filter this preserves Greek, Cyrillic, CJK, etc.
    and never collapses a non-Latin name to an empty key.
    """
    folded = unicodedata.normalize("NFKD", (name or "")).casefold()
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return "".join(ch for ch in folded if ch.isalnum())


# Greek -> Latin, so "Σοφία Μανουσάκη" can match Spotify's "Sofia Manousaki"
# and "Μπλε" can match "Mple". Accents are already gone after NFKD.
_GREEK_LATIN = str.maketrans({
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
})
# υ is transliterated both ways in artist names ("Manousaki" vs "Myrto"), so
# both variants are compared.
_GREEK_LATIN_ALT = {**_GREEK_LATIN, ord("υ"): "u"}


def _latin_key(name: str, table) -> str:
    folded = unicodedata.normalize("NFKD", (name or "")).casefold()
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return "".join(ch for ch in folded.translate(table) if ch.isalnum())


def _folded_words(name: str) -> list[str]:
    """Accent- and case-insensitive words, punctuation turned into separators."""
    folded = unicodedata.normalize("NFKD", (name or "")).casefold()
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = "".join(ch if ch.isalnum() else " " for ch in folded)
    return folded.split()


def _word_key(name: str, table) -> str:
    """Word-aligned transliterated key with a tolerance for the Greek final -s.

    Greek pages write names in the accusative ("Τόνι Σφήνος") while Spotify
    keeps the nominative Latin spelling ("Tonis Sfinos"). Comparing words
    without their trailing s keeps those together without merging unrelated
    names, because the word boundaries still have to line up.
    """
    words = []
    for word in _folded_words(name):
        latin = word.translate(table)
        if len(latin) > 2 and latin.endswith("s"):
            latin = latin[:-1]
        if latin:
            words.append(latin)
    return " ".join(words)


def _artist_keys(name: str) -> tuple[str, ...]:
    """Every comparable key for a name (native script + Latin transliterations)."""
    keys = (
        _normalize_artist_name(name),
        _latin_key(name, _GREEK_LATIN),
        _latin_key(name, _GREEK_LATIN_ALT),
        _word_key(name, _GREEK_LATIN),
        _word_key(name, _GREEK_LATIN_ALT),
    )
    return tuple(dict.fromkeys(k for k in keys if k))


def _search_artist_candidates(token: str, name: str, limit: int = 5) -> list[dict]:
    """Artist-only catalog search (lighter than the combined artist+album search)."""
    try:
        data = _get(token, "/search", params={"q": name, "type": "artist", "limit": limit})
    except Exception:
        return []
    artists = []
    for artist in (data.get("artists") or {}).get("items") or []:
        if not isinstance(artist, dict):
            continue
        images = artist.get("images") or []
        artists.append({
            "id": artist.get("id"),
            "name": artist.get("name") or "Unknown artist",
            "image_url": (images[0].get("url") if images else "") or "",
            "genres": artist.get("genres") or [],
            "followers": (artist.get("followers") or {}).get("total", 0),
        })
    return artists


def resolve_artists(token: str, names: list[str]) -> dict:
    """Resolve artist names to Spotify IDs, preferring the user's followed artists.

    Fast by design: the followed list is used only from cache (a cold cache is
    warmed in the background), and followed status for catalog matches comes from
    the batched /me/following/contains call instead of paginating every followed
    artist. A scan page therefore resolves in seconds, not a minute.
    """
    cleaned = [str(raw or "").strip() for raw in (names or [])]
    cleaned = [n for n in cleaned if n]

    followed = _cached_followed_artists(token)
    if followed is None:
        _warm_followed_artists(token)  # do not block this request on pagination
        followed = []
    followed_ids = {a.get("id") for a in followed if a.get("id")}
    followed_by_norm: dict[str, dict] = {}
    for a in followed:
        if not a.get("id"):
            continue
        # Index both the native-script and transliterated keys, and never index
        # the empty key: names that fold to nothing would all collide.
        for key in _artist_keys(a.get("name")):
            followed_by_norm.setdefault(key, a)

    # Names already matched by the cached followed list need no catalog lookup;
    # everything else needs an id so we can ask /me/following/contains. Searches
    # are concurrent because a page can carry 60+ distinct names.
    def _is_followed_match(value: str) -> bool:
        return any(k in followed_by_norm for k in _artist_keys(value))

    search_names = list(dict.fromkeys(
        n for n in cleaned if not _is_followed_match(n)
    ))
    candidates: dict[str, list[dict]] = {}
    if search_names:
        workers = min(8, len(search_names))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for name, found in zip(
                    search_names,
                    pool.map(lambda n: _search_artist_candidates(token, n), search_names)):
                candidates[name] = found

    matches: dict[str, dict] = {}
    for name in search_names:
        match = _best_artist_match(candidates.get(name) or [], name)
        if match and match.get("id"):
            matches[name] = match
    contains = _followed_contains(token, [m["id"] for m in matches.values()])

    resolved = []
    unresolved = []
    for name in cleaned:
        # 1) Correlate directly against the followed list first (source of truth).
        f = next((followed_by_norm[k] for k in _artist_keys(name) if k in followed_by_norm), None)
        if f:
            resolved.append({
                "name": name,
                "spotify_id": f.get("id"),
                "matched_name": f.get("name") or name,
                "image_url": f.get("image_url") or "",
                "genres": f.get("genres") or [],
                "followed": True,
            })
            continue
        # 2) Catalog match, with followed status confirmed by /me/following/contains.
        match = matches.get(name)
        if match:
            aid = match.get("id")
            resolved.append({
                "name": name,
                "spotify_id": aid,
                "matched_name": match.get("name") or name,
                "image_url": match.get("image_url") or "",
                "genres": match.get("genres") or [],
                "followed": aid in contains or aid in followed_ids,
            })
        else:
            unresolved.append(name)
    return {"resolved": resolved, "unresolved": unresolved}
