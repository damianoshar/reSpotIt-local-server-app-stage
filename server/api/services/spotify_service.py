"""
services/spotify_service.py
----------------------------
Single responsibility: fetch albums and genres from the Spotify Web API.
Auth token management lives in auth_service.py.
"""

import csv
import os
import time
from typing import Callable

import requests

from .auth_service import get_valid_token

OUTPUT_CSV   = os.getenv("OUTPUT_CSV", "/data/spotify_albums.csv")
PAGE_LIMIT   = 50
ARTIST_BATCH = 50

CSV_FIELDS = [
    "added_at", "name", "artists", "release_date",
    "total_tracks", "album_type", "label", "popularity",
    "genres", "album_id", "spotify_url", "image_url",
]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fetch_artist_genres(artist_ids: list[str], token: str, delay: float = 0.3) -> dict[str, list[str]]:
    genres: dict[str, list[str]] = {}
    unique = list(dict.fromkeys(artist_ids))
    for i in range(0, len(unique), ARTIST_BATCH):
        batch = unique[i : i + ARTIST_BATCH]
        while True:
            resp = requests.get(
                "https://api.spotify.com/v1/artists",
                headers=_headers(token),
                params={"ids": ",".join(batch)},
            )
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", 5)))
                continue
            resp.raise_for_status()
            for a in resp.json().get("artists") or []:
                if a:
                    genres[a["id"]] = a.get("genres", [])
            break
        time.sleep(delay)
    return genres


def fetch_all_albums(
    token: str,
    delay: float = 0.5,
    progress_cb: Callable | None = None,
) -> list[dict]:
    albums: list[dict] = []
    url    = "https://api.spotify.com/v1/me/albums"
    params = {"limit": PAGE_LIMIT, "offset": 0}
    page   = 0

    # Phase 1 — saved albums
    while url:
        page += 1
        resp = requests.get(url, headers=_headers(token), params=params)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", 5)))
            if progress_cb:
                progress_cb(fetched=len(albums), total=None, page=page,
                            current_album="[rate limited]", phase="albums")
            continue
        resp.raise_for_status()
        data  = resp.json()
        total = data.get("total", 0) or 0

        for item in data.get("items", []):
            album = item.get("album", {})
            albums.append({
                "added_at":     item.get("added_at", ""),
                "album_id":     album.get("id", ""),
                "name":         album.get("name", ""),
                "artists":      ", ".join(a["name"] for a in album.get("artists", [])),
                "_artist_ids":  [a["id"] for a in album.get("artists", []) if a.get("id")],
                "release_date": album.get("release_date", ""),
                "total_tracks": album.get("total_tracks", ""),
                "album_type":   album.get("album_type", ""),
                "label":        album.get("label", ""),
                "popularity":   album.get("popularity", ""),
                "genres":       "",
                "spotify_url":  album.get("external_urls", {}).get("spotify", ""),
                "image_url":    album["images"][0]["url"] if album.get("images") else "",
            })

        if progress_cb:
            progress_cb(fetched=len(albums), total=total, page=page,
                        current_album=albums[-1]["name"] if albums else "", phase="albums")
        url, params = data.get("next"), {}
        if url:
            time.sleep(delay)

    # Phase 2 — enrich genres from artists
    all_ids = [aid for a in albums for aid in a.get("_artist_ids", [])]
    if all_ids:
        if progress_cb:
            progress_cb(fetched=len(albums), total=len(albums), page=page,
                        current_album="Fetching artist genres…", phase="genres")
        genre_map = fetch_artist_genres(all_ids, token, delay=delay * 0.6)
        for album in albums:
            ids = album.pop("_artist_ids", [])
            seen: set[str] = set()
            combined = [g for aid in ids for g in genre_map.get(aid, [])
                        if not (g in seen or seen.add(g))]
            album["genres"] = ", ".join(combined)
    else:
        for a in albums:
            a.pop("_artist_ids", None)

    return albums


def save_albums_to_csv(albums: list[dict], path: str = OUTPUT_CSV) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(albums)
