"""routers/spotify_actions.py β€” playlists (live + cached) and queue jobs."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import csv
import io
import time
from datetime import date

from ..contract import ContractError
from ..deps import get_current_user
from ..job_store import create_job, update_job, is_cancelled
from ..models import User
from ..services.auth_service import get_valid_token, is_authenticated
from ..services.spotify_actions import get_current_user as get_spotify_user
from ..services.spotify_actions import (
    get_user_playlists, create_playlist, add_tracks_to_playlist,
    get_albums_track_uris, get_playlist, get_playlist_tracks,
    queue_single_track, get_album_details, remove_tracks_from_playlist,
    unfollow_playlist, set_playlist_public,
    follow_artists_from_saved_albums, remove_saved_albums, save_saved_albums,
    search_spotify_catalog, get_artist_albums, get_spotify_albums,
    get_player_state, get_player_queue,
)
from ..services.playlist_cache import (
    upsert_playlist, get_playlist_by_spotify, replace_tracks,
    mark_synced, album_groups, filter_options, synced_map,
    album_track_uris, remove_album_tracks_from_cache, delete_playlist_cache,
)
from ..services import album_cache, retention_service

router = APIRouter(prefix="/api/v1", tags=["spotify"])


@router.get("/spotify/status", summary="Check Spotify link status")
def spotify_status(user: User = Depends(get_current_user)):
    user_id = str(user.id)
    if not is_authenticated(user_id):
        return {"connected": False, "display_name": None}
    display_name = None
    try:
        spotify_user = get_spotify_user(get_valid_token(user_id))
        display_name = spotify_user.get("display_name") or spotify_user.get("id")
    except Exception:
        pass
    return {"connected": True, "display_name": display_name}


class AlbumSelection(BaseModel):
    album_ids: list[str]

class CreatePlaylistBody(BaseModel):
    name:            str
    description:     str = ""
    album_ids:       list[str] = Field(default_factory=list)
    # Direct item URIs (queue snapshots). Tracks and episodes are both allowed.
    uris:            list[str] = Field(default_factory=list)
    # Shortlived playlists: either a relative number of hours or an explicit
    # ISO-8601 expiry. Both omitted = permanent playlist (the default).
    retention_hours: float | None = None
    retention_until: str | None = None


PLAYABLE_URI_PREFIXES = ("spotify:track:", "spotify:episode:")


def _require_playable_uris(uris: list[str]) -> None:
    if not all(isinstance(uri, str) and uri.startswith(PLAYABLE_URI_PREFIXES)
               for uri in uris):
        raise HTTPException(422, "Only spotify:track: and spotify:episode: URIs can be added.")


class RetentionBody(BaseModel):
    expires_at: str


class TrackUrisBody(BaseModel):
    uris: list[str]


def _expires_at(body: CreatePlaylistBody):
    from datetime import datetime, timedelta, timezone
    if body.retention_until:
        try:
            expires = retention_service.as_utc(
                datetime.fromisoformat(body.retention_until.replace("Z", "+00:00"))
            )
        except ValueError:
            raise HTTPException(422, "retention_until must be an ISO-8601 date/time.")
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(422, "retention_until must be in the future.")
        return expires
    if body.retention_hours is not None:
        if body.retention_hours <= 0:
            raise HTTPException(422, "retention_hours must be positive.")
        return datetime.now(timezone.utc) + timedelta(hours=body.retention_hours)
    return None


def _token(user_id: str):
    try:
        return get_valid_token(user_id)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _handle(e: Exception):
    if isinstance(e, PermissionError): raise HTTPException(403, str(e))
    if isinstance(e, ValueError):      raise HTTPException(422, str(e))
    raise HTTPException(502, f"Spotify error: {e}")


def _cached_or_404(playlist_id: str, user_id: str):
    """This user's cached playlist row, or 404 when never (fully) synced."""
    from ..services.playlist_cache import get_playlist_by_spotify
    pl = get_playlist_by_spotify(playlist_id, user_id)
    if not pl or not pl["synced_at"]:
        raise HTTPException(404, "Playlist is not synced yet. Sync it first.")
    return pl


@router.get("/playlists")
def list_playlists(user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        playlists = get_user_playlists(_token(user_id))
    except Exception as e:
        _handle(e)
    # Cached-sync annotation (extra key, Β§1 allows it): lets the dashboard
    # badge each playlist and know a first visit must sync before /albums can
    # answer. Best-effort β€” the live list must still load without a database.
    try:
        synced = synced_map(user_id)
    except Exception:
        synced = {}
    for p in playlists:
        p["synced_at"] = synced.get(p["id"])
    return playlists


@router.post("/playlists")
def create_new_playlist(body: CreatePlaylistBody, user: User = Depends(get_current_user)):
    if not body.name.strip():
        raise HTTPException(422, "Playlist name cannot be empty.")
    if not body.album_ids and not body.uris:
        raise HTTPException(422, "No albums or track URIs selected.")
    _require_playable_uris(body.uris)
    user_id = str(user.id)
    try:
        token      = _token(user_id)
        expires_at = _expires_at(body)
        uris       = list(body.uris)
        if body.album_ids:
            uris += get_albums_track_uris(token, body.album_ids)
        playlist   = create_playlist(token, body.name.strip(), body.description)
        added      = add_tracks_to_playlist(token, playlist["id"], uris)
        if expires_at:
            retention_service.set_retention(playlist["id"], expires_at, user_id)
        return {
            "playlist_id":   playlist["id"],
            "playlist_name": playlist["name"],
            "playlist_url":  playlist["url"],
            "tracks_added":  added,
            "expires_at":    expires_at.isoformat() if expires_at else None,
        }
    except Exception as e:
        _handle(e)


@router.post("/playlists/{playlist_id}/tracks")
def add_to_existing(playlist_id: str, body: dict, user: User = Depends(get_current_user)):
    uris      = body.get("uris") or []
    album_ids = body.get("album_ids") or []
    if not isinstance(uris, list) or not isinstance(album_ids, list):
        raise HTTPException(422, "uris and album_ids must be arrays.")
    if not uris and not album_ids:
        raise HTTPException(422, "No track URIs or albums provided.")
    if uris and not all(u.startswith("spotify:track:") for u in uris):
        raise HTTPException(422, "Only spotify:track: URIs can be added.")
    try:
        token = _token(str(user.id))
        resolved = get_albums_track_uris(token, album_ids) if album_ids else []
        return {"playlist_id": playlist_id,
                "tracks_added": add_tracks_to_playlist(token, playlist_id, uris + resolved)}
    except Exception as e:
        _handle(e)


@router.post("/playlists/{playlist_id}/items")
def add_items_to_existing(
    playlist_id: str,
    body: TrackUrisBody,
    user: User = Depends(get_current_user),
):
    """Append direct track/episode URIs to a playlist (queue snapshot action).

    This is the additive counterpart to the older album-based /tracks route.
    It keeps the same response shape so the phone clients can share DTOs.
    """
    if not body.uris:
        raise HTTPException(422, "No track URIs provided.")
    _require_playable_uris(body.uris)
    try:
        token = _token(str(user.id))
        return {
            "playlist_id": playlist_id,
            "tracks_added": add_tracks_to_playlist(token, playlist_id, body.uris),
        }
    except Exception as e:
        _handle(e)


def _run_queue(job_id: str, user_id: str, album_ids: list[str]):
    """Resolve every album's tracks, then queue each URI (stages + cancel)."""
    try:
        update_job(job_id, status="running", stage="tracks",
                   fetched=0, total=len(album_ids), message="Resolving tracksβ€¦")
        token = get_valid_token(user_id)
        uris: list[str] = []
        failed_albums = 0
        for idx, album_id in enumerate(album_ids, 1):
            if is_cancelled(job_id):
                update_job(job_id, status="cancelled", message="Cancelled by user.")
                return
            try:
                uris += get_albums_track_uris(token, [album_id])
            except Exception:
                failed_albums += 1
            update_job(job_id, stage="tracks", fetched=idx, total=len(album_ids))

        total_tracks = len(uris)
        if not uris:
            raise RuntimeError("No tracks resolved from the selected albums.")

        queued = failed = failed_albums
        errors: list[str] = []
        for idx, uri in enumerate(uris, 1):
            if is_cancelled(job_id):
                update_job(job_id, status="cancelled", inserted=queued, skipped=failed,
                           errors=errors, message="Cancelled by user.")
                return
            try:
                queue_single_track(token, uri)
                queued += 1
            except (PermissionError, ValueError) as e:
                # Premium / no-device never resolves by retrying β€” fail the job now.
                raise RuntimeError(str(e))
            except Exception as e:
                failed += 1
                if len(errors) < 5:
                    errors.append(str(e))
            update_job(job_id, stage="queueing", fetched=idx, total=total_tracks,
                       inserted=queued, skipped=failed, errors=errors)
            time.sleep(0.1)

        update_job(job_id, status="done", fetched=total_tracks, total=total_tracks,
                   inserted=queued, skipped=failed, errors=errors,
                   message=f"Queued {queued} tracks.")
    except Exception as e:
        update_job(job_id, status="error", message=str(e))


@router.post("/queue", status_code=202)
def queue_albums(
    body: AlbumSelection,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    # Codes here are explicit (not status-derived) so a shared frontend sees
    # `no_albums` / `not_connected` from every backend.
    if not body.album_ids:
        raise ContractError(422, "no_albums", "No albums selected.")
    user_id = str(user.id)
    if not is_authenticated(user_id):
        raise ContractError(422, "not_connected", "Spotify account is not connected.")
    job_id = create_job("queue", user_id)
    background_tasks.add_task(_run_queue, job_id, user_id, body.album_ids)
    return {"job_id": job_id}


def _run_playlist_sync(job_id: str, user_id: str, spotify_id: str):
    """Fetch meta + tracks, replace cache, mark synced (stages + cancel)."""
    from ..services.playlist_cache import (
        upsert_playlist, replace_tracks, mark_synced,
    )
    from ..services.spotify_actions import get_playlist, get_playlist_tracks

    try:
        update_job(job_id, status="running", stage="albums",
                   fetched=0, total=0, message="Fetching playlistβ€¦")
        token = get_valid_token(user_id)
        raw = get_playlist(token, spotify_id)
        # Flatten Spotify's nested shape into the cache shape (nested dicts
        # like owner/images can't go straight into TEXT columns).
        images = raw.get("images") or []
        meta = {
            "spotify_id":  raw.get("id"),
            "name":        raw.get("name", ""),
            "description": raw.get("description", "") or "",
            "image_url":   (images[0].get("url") if images else None),
            "owner":       (raw.get("owner") or {}).get("display_name"),
            "track_count": (raw.get("tracks") or {}).get("total", 0) or 0,
            "public":      raw.get("public", False),
        }
        uuid = upsert_playlist(meta, user_id)
        if is_cancelled(job_id):
            update_job(job_id, status="cancelled", message="Cancelled by user.")
            return
        tracks = get_playlist_tracks(token, spotify_id)
        update_job(job_id, stage="albums", fetched=len(tracks), total=len(tracks))
        if is_cancelled(job_id):
            update_job(job_id, status="cancelled", message="Cancelled by user.")
            return
        count = replace_tracks(uuid, tracks, user_id)
        mark_synced(spotify_id, meta["track_count"] or count, user_id)
        update_job(job_id, status="done", fetched=count, total=count,
                   inserted=count, message=f"Synced {count} tracks.")
    except Exception as e:
        update_job(job_id, status="error", message=str(e))


@router.post("/playlists/{playlist_id}/sync", status_code=202)
def sync_playlist(
    playlist_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    user_id = str(user.id)
    job_id = create_job("playlist_sync", user_id)
    background_tasks.add_task(_run_playlist_sync, job_id, user_id, playlist_id)
    return {"job_id": job_id}


@router.get("/playlists/{playlist_id}/albums")
def playlist_albums(
    playlist_id: str,
    user:        User = Depends(get_current_user),
    search:    str = None,
    genre:     str = None,
    artist:    str = None,
    year_from: int = None,
    year_to:   int = None,
    sort:      str = "artist",
    order:     str = "asc",
    page:      int = 1,
    limit:     int = 48,
):
    from ..services.playlist_cache import album_groups

    user_id = str(user.id)
    _cached_or_404(playlist_id, user_id)
    groups = album_groups(playlist_id, user_id)

    q = (search or "").strip().lower()
    g = (genre or "").strip().lower()
    a = (artist or "").strip().lower()

    def keep(gr):
        if q and q not in gr["title"].lower() and q not in gr["artist"].lower():
            return False
        if g and gr["genre"].lower() != g:
            return False
        if a and gr["artist"].lower() != a:
            return False
        if year_from and not (gr["year"] and gr["year"] >= year_from):
            return False
        if year_to and not (gr["year"] and gr["year"] <= year_to):
            return False
        return True

    filtered = [gr for gr in groups if keep(gr)]

    key = {
        "title":       lambda gr: gr["title"].lower(),
        "artist":      lambda gr: gr["artist"].lower(),
        "year":        lambda gr: gr["year"],
        "genre":       lambda gr: gr["genre"].lower(),
        "track_count": lambda gr: gr["track_count"],
    }.get(sort, lambda gr: gr["artist"].lower())
    filtered.sort(key=key, reverse=(order == "desc"))

    total = len(filtered)
    page = max(page, 1)
    limit = min(max(limit, 1), 200)
    items = filtered[(page - 1) * limit:page * limit]
    return {
        "items": [
            {
                "id": gr["album_spotify_id"], "title": gr["title"], "artist": gr["artist"],
                "year": gr["year"], "genre": gr["genre"], "image_url": gr["image_url"],
                "track_count": gr["track_count"], "track_titles": gr["track_titles"],
            }
            for gr in items
        ],
        "total": total, "page": page, "limit": limit,
    }


@router.get("/playlists/{playlist_id}/meta")
def playlist_meta(playlist_id: str, user: User = Depends(get_current_user)):
    from ..services.playlist_cache import filter_options

    user_id = str(user.id)
    _cached_or_404(playlist_id, user_id)
    return filter_options(playlist_id, user_id)


@router.get("/playlists/{playlist_id}/export")
def export_playlist(playlist_id: str, user: User = Depends(get_current_user)):
    from ..services.playlist_cache import album_groups

    user_id = str(user.id)
    pl = _cached_or_404(playlist_id, user_id)
    groups = album_groups(playlist_id, user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "album_title", "artist", "year", "genre",
                     "image_url", "track_count", "tracks"])
    for gr in groups:
        writer.writerow([
            gr["album_spotify_id"], gr["title"], gr["artist"], gr["year"],
            gr["genre"], gr["image_url"], gr["track_count"],
            "; ".join(gr["track_titles"]),
        ])

    safe = "".join(c if c.isalnum() else "-" for c in (pl["name"] or "playlist"))
    safe = "-".join(filter(None, safe.split("-")))[:60] or "playlist"
    filename = f"playlist-{safe.lower()}-{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# β”€β”€ Album track sheet β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

@router.get("/albums/{album_id}/tracks", summary="Album track list (cache-first)")
def album_track_list(album_id: str, user: User = Depends(get_current_user)):
    """Cached when warm; otherwise fetch from Spotify and cache the result."""
    user_id = str(user.id)
    tracks = album_cache.get_album_tracks(album_id, user_id)
    if tracks:
        return {"album_id": album_id, "cached": True, "items": tracks}
    if not is_authenticated(user_id):
        raise HTTPException(404, "No cached tracks for this album.")
    try:
        tracks = get_album_details(_token(user_id), album_id)
        album_cache.replace_album_tracks(album_id, tracks, user_id)
        return {"album_id": album_id, "cached": False, "items": tracks}
    except Exception as e:
        _handle(e)


# β”€β”€ Remove albums from a playlist β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

@router.delete("/playlists/{playlist_id}/albums", summary="Remove albums from a playlist")
def remove_albums_from_playlist(
    playlist_id: str,
    body: AlbumSelection,
    user: User = Depends(get_current_user),
):
    if not body.album_ids:
        raise HTTPException(422, "No albums selected.")
    user_id = str(user.id)
    if not is_authenticated(user_id):
        raise HTTPException(401, "Spotify account is not connected.")
    try:
        token = _token(user_id)
        # Read the cache first; delete rows only after Spotify confirms, so a
        # failed removal cannot leave the cache ahead of the real playlist.
        uris = album_track_uris(playlist_id, body.album_ids, user_id)
        if not uris:
            # Not cached (or no matching tracks): resolve from the live playlist.
            wanted = set(body.album_ids)
            live = get_playlist_tracks(token, playlist_id)
            uris = [
                f"spotify:track:{t['spotify_id']}"
                for t in live
                if t.get("album_spotify_id") in wanted and t.get("spotify_id")
            ]
        if not uris:
            return {"playlist_id": playlist_id, "albums_removed": len(body.album_ids),
                    "tracks_removed": 0}
        removed = remove_tracks_from_playlist(token, playlist_id, uris)
        remove_album_tracks_from_cache(playlist_id, body.album_ids, user_id)
        return {"playlist_id": playlist_id, "albums_removed": len(body.album_ids),
                "tracks_removed": removed}
    except Exception as e:
        _handle(e)


@router.delete("/playlists/{playlist_id}/tracks", summary="Remove individual tracks from a playlist")
def remove_tracks_from_playlist_route(
    playlist_id: str,
    body: TrackUrisBody,
    user: User = Depends(get_current_user),
):
    if not body.uris:
        raise HTTPException(422, "No track URIs provided.")
    if not all(u.startswith("spotify:track:") for u in body.uris):
        raise HTTPException(422, "Only spotify:track: URIs can be removed.")
    user_id = str(user.id)
    try:
        removed = remove_tracks_from_playlist(_token(user_id), playlist_id, body.uris)
        try:
            from ..services.playlist_cache import remove_track_uris
            remove_track_uris(playlist_id, body.uris, user_id)
        except Exception:
            pass  # cache maintenance must not fail the removal
        return {"playlist_id": playlist_id, "tracks_removed": removed}
    except Exception as e:
        _handle(e)


# β”€β”€ Queue individual tracks β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

@router.post("/queue/tracks", summary="Queue individual track URIs")
def queue_track_uris(body: TrackUrisBody, user: User = Depends(get_current_user)):
    if not body.uris:
        raise HTTPException(422, "No track URIs provided.")
    if not all(u.startswith("spotify:track:") for u in body.uris):
        raise HTTPException(422, "Only spotify:track: URIs can be queued.")
    try:
        token = _token(str(user.id))
        queued = 0
        for uri in body.uris:
            queue_single_track(token, uri)
            queued += 1
        return {"queued": queued}
    except Exception as e:
        _handle(e)


# β”€β”€ Shortlived-playlist retention β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

@router.get("/playlists/retention", summary="List playlists with an expiry")
def list_playlist_retention(user: User = Depends(get_current_user)):
    rows = retention_service.list_retention(str(user.id))
    return {
        "items": [
            {
                "playlist_id":  r["playlist_spotify_id"],
                "expires_at":   r["expires_at"].isoformat() if r["expires_at"] else None,
                "keep_forever": r["keep_forever"],
                "last_error":   r["last_error"],
            }
            for r in rows
        ]
    }


@router.put("/playlists/{playlist_id}/retention", summary="Set a playlist expiry")
def set_playlist_retention(
    playlist_id: str,
    body: RetentionBody,
    user: User = Depends(get_current_user),
):
    try:
        expires = retention_service.as_utc(body.expires_at)
    except ValueError:
        raise HTTPException(422, "expires_at must be an ISO-8601 date/time.")
    if not expires:
        raise HTTPException(422, "expires_at is required.")
    retention_service.set_retention(playlist_id, expires, str(user.id))
    return {"playlist_id": playlist_id, "expires_at": expires.isoformat()}


@router.put("/playlists/{playlist_id}/visibility", summary="Change a playlist's public/private flag")
def set_playlist_visibility(playlist_id: str, public: bool, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        set_playlist_public(_token(user_id), playlist_id, public)
    except Exception as e:
        _handle(e)
    return {"playlist_id": playlist_id, "public": public}


@router.post("/playlists/{playlist_id}/retention/extend", summary="Extend a playlist expiry")
def extend_playlist_retention(
    playlist_id: str,
    body: RetentionBody,
    user: User = Depends(get_current_user),
):
    return set_playlist_retention(playlist_id, body, user)


@router.delete("/playlists/{playlist_id}/retention", summary="Keep a playlist forever")
def keep_playlist_forever(playlist_id: str, user: User = Depends(get_current_user)):
    removed = retention_service.clear_retention(playlist_id, str(user.id))
    return {"playlist_id": playlist_id, "kept": True, "had_retention": removed}


@router.post("/playlists/{playlist_id}/retention/delete-now",
             summary="Delete a shortlived playlist now")
def delete_playlist_now(playlist_id: str, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        unfollow_playlist(_token(user_id), playlist_id)
    except Exception as e:
        _handle(e)
    retention_service.clear_retention(playlist_id, user_id)
    try:
        delete_playlist_cache(playlist_id, user_id)
    except Exception:
        pass  # cache maintenance must not fail the delete
    return {"playlist_id": playlist_id, "deleted": True}


@router.delete("/playlists/{playlist_id}", summary="Unfollow/delete a playlist")
def delete_playlist(
    playlist_id: str,
    user: User = Depends(get_current_user),
):
    user_id = str(user.id)
    if not is_authenticated(user_id):
        raise HTTPException(401, "Spotify account is not connected.")
    try:
        token = _token(user_id)
        unfollow_playlist(token, playlist_id)
        delete_playlist_cache(playlist_id, user_id)
        return {"playlist_id": playlist_id, "deleted": True}
    except Exception as e:
        _handle(e)


# --- Spotify account tools ---

@router.post("/spotify/follow-artists", summary="Follow artists from saved Spotify albums")
def follow_artists_from_saved(user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        return follow_artists_from_saved_albums(_token(user_id))
    except Exception as e:
        _handle(e)


@router.delete("/spotify/albums", summary="Remove albums from the Spotify saved library")
def remove_saved_spotify_albums(body: AlbumSelection, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        removed = remove_saved_albums(_token(user_id), body.album_ids)
        return {"removed": removed}
    except Exception as e:
        _handle(e)


@router.post("/spotify/albums/save", summary="Save albums to the Spotify library")
def save_spotify_albums_route(body: AlbumSelection, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        saved = save_saved_albums(_token(user_id), body.album_ids)
        return {"saved": saved}
    except Exception as e:
        _handle(e)


@router.get("/spotify/catalog/search", summary="Search Spotify artists and albums")
def catalog_search(q: str, limit: int = 8, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        return search_spotify_catalog(_token(user_id), q, limit)
    except Exception as e:
        _handle(e)


@router.get("/spotify/artists/{artist_id}/albums", summary="Artist discography")
def artist_discography(artist_id: str, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        return {"artist_id": artist_id, "albums": get_artist_albums(_token(user_id), artist_id)}
    except Exception as e:
        _handle(e)


@router.get("/spotify/albums", summary="Spotify album metadata by id")
def spotify_album_metadata(ids: str, user: User = Depends(get_current_user)):
    user_id = str(user.id)
    try:
        album_ids = [x.strip() for x in ids.split(",") if x.strip()]
        return {"albums": get_spotify_albums(_token(user_id), album_ids)}
    except Exception as e:
        _handle(e)

# --- Spotify player token ---

@router.get("/spotify/player-token", summary="Mint a Spotify access token for the Web Playback SDK")
def spotify_player_token(user: User = Depends(get_current_user)):
    user_id = str(user.id)
    if not is_authenticated(user_id):
        raise HTTPException(401, "Spotify account is not connected.")
    try:
        return {"access_token": get_valid_token(user_id), "token_type": "Bearer"}
    except Exception as e:
        _handle(e)

# --- Spotify player state ---

@router.get("/spotify/player", summary="Current Spotify playback state")
def spotify_player_state(user: User = Depends(get_current_user)):
    user_id = str(user.id)
    if not is_authenticated(user_id):
        raise HTTPException(401, "Spotify account is not connected.")
    try:
        return get_player_state(_token(user_id))
    except Exception as e:
        _handle(e)


@router.get("/spotify/player/queue", summary="Current Spotify queue")
def spotify_player_queue(user: User = Depends(get_current_user)):
    user_id = str(user.id)
    if not is_authenticated(user_id):
        raise HTTPException(401, "Spotify account is not connected.")
    try:
        return get_player_queue(_token(user_id))
    except Exception as e:
        _handle(e)
