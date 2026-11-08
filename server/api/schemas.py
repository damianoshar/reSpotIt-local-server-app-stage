"""
schemas.py
----------
Pydantic v2 models used for API request validation and response serialization.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer


# ── Shared config ─────────────────────────────────────────────────────────────

class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Artists ───────────────────────────────────────────────────────────────────

class ArtistBase(_ORM):
    id:   UUID
    name: str


class ArtistOut(ArtistBase):
    created_at: Optional[datetime] = None


class ArtistDetail(ArtistOut):
    albums: list[AlbumBase] = []


# ── Albums ────────────────────────────────────────────────────────────────────

class AlbumBase(_ORM):
    id:           UUID
    spotify_id:   str
    name:         str
    release_date: Optional[date]    = None
    total_tracks: Optional[int]     = None
    album_type:   Optional[str]     = None
    label:        Optional[str]     = None
    popularity:   Optional[int]     = None
    genres:       Optional[list[str]] = None
    spotify_url:  Optional[str]     = None
    image_url:    Optional[str]     = None
    image_file:   Optional[str]     = None
    added_at:     Optional[datetime] = None


class AlbumOut(AlbumBase):
    artists: list[ArtistBase] = []

    # ── Frozen contract keys (API-PARITY-PLAN §1 "JSON item shapes") ──
    # The flat JSON twin of the CSV columns, alongside the native
    # Spotify-shaped keys the local UI uses. Remote clients read these;
    # unknown/extra keys are ignored by contract.

    @field_serializer("id")
    def _ser_id(self, v: UUID) -> str:
        # Contract `id` is the Spotify ID (what CSV import/export call `id`).
        return self.spotify_id

    @computed_field
    @property
    def title(self) -> str:
        return self.name or ""

    @computed_field
    @property
    def artist(self) -> str:
        names = sorted({a.name for a in (self.artists or []) if a and a.name})
        return "; ".join(names)

    @computed_field
    @property
    def year(self) -> int:
        rd = self.release_date
        return rd.year if isinstance(rd, date) else 0

    @computed_field
    @property
    def genre(self) -> str:
        g = self.genres
        if isinstance(g, list):
            return g[0] if g else ""
        return g or ""


class AlbumDetail(AlbumOut):
    created_at: Optional[datetime] = None


# ── Concerts (server-canonical, docs/STORAGE-POLICY.md) ───────────────────────

class ConcertBase(_ORM):
    id:         str
    artist:     str  = ""
    artist_id:  str  = ""
    title:      str  = ""
    date:       str  = ""
    venue:      str  = ""
    url:        str  = ""
    source_url: str  = ""
    followed:   bool = False
    created_at: str  = ""


class ConcertIn(ConcertBase):
    pass


class ConcertOut(ConcertBase):
    added_at: Optional[datetime] = None


class ConcertsResponse(BaseModel):
    total:    int
    concerts: list[ConcertOut]


class ConcertUpsert(BaseModel):
    items: list[ConcertIn] = []


class ConcertImport(BaseModel):
    items:   list[ConcertIn] = []
    replace: bool = False


# ── Hidden albums (server-canonical duplicate blocklist) ──────────────────────

class HiddenAlbumIn(BaseModel):
    # Clients call the album's Spotify id `id`; accept either name.
    model_config = ConfigDict(populate_by_name=True)
    spotify_id: str = Field(..., alias="id")
    title:      str            = ""
    artist:     str            = ""
    year:       Optional[int]  = None
    genre:      str            = ""
    album_type: str            = "album"
    image_url:  Optional[str]  = None
    added_at:   str            = ""


class HiddenAlbumOut(_ORM):
    spotify_id: str
    title:      str           = ""
    artist:     str           = ""
    year:       Optional[int] = None
    genre:      str           = ""
    album_type: str           = "album"
    image_url:  Optional[str] = None
    added_at:   str           = ""

    @computed_field
    @property
    def id(self) -> str:
        return self.spotify_id


class HiddenAlbumsResponse(BaseModel):
    total:  int
    albums: list[HiddenAlbumOut]


class HiddenAlbumUpsert(BaseModel):
    items: list[HiddenAlbumIn] = []


class HiddenAlbumImport(BaseModel):
    items:   list[HiddenAlbumIn] = []
    replace: bool = False


# ── Concert scans (click-and-forget AI scan, pending review) ──────────────────

class ConcertScanStart(BaseModel):
    url:  Optional[str] = Field(default=None, max_length=2048)
    text: Optional[str] = Field(default=None, max_length=20000)


class ConcertScanItem(BaseModel):
    artist: str = ""
    date:   str = ""
    venue:  str = ""
    url:    str = ""


class ConcertScanOut(_ORM):
    id:          str
    source:      str = ""
    source_url:  str = ""
    source_kind: str = "text"
    status:      str = "running"
    stage:       str = "queued"
    message:     str = ""
    items:       list[ConcertScanItem] = []
    error:       str = ""
    chat_id:     str = ""
    created_at:  Optional[datetime] = None
    updated_at:  Optional[datetime] = None


class ConcertScanLatest(BaseModel):
    scan: Optional[ConcertScanOut] = None


# ── Pagination wrappers ───────────────────────────────────────────────────────

class PaginatedAlbums(BaseModel):
    total: int
    page:  int
    limit: int
    items: list[AlbumOut]


class PaginatedArtists(BaseModel):
    total: int
    page:  int
    limit: int
    items: list[ArtistOut]


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobStarted(BaseModel):
    job_id:  str
    status:  str = "started"
    message: str = ""


class SyncStartBody(BaseModel):
    clean:            bool = False
    download_images:  bool = False
    # Opt-in: also cache each album's track list for offline/fast album sheets.
    # Off by default — it is one Spotify request per album and rate-limits.
    include_tracks:   bool = False


# ── Auth (user accounts) ──────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class TokenRefresh(BaseModel):
    refresh_token: str


class SpotifyTokenImport(BaseModel):
    """Tokens obtained by a mobile client's own PKCE flow (custom-scheme
    redirect), handed to the server so it can call the Spotify Web API.
    Mobile clients cannot use the server's loopback OAuth callback."""
    access_token:  str
    refresh_token: str
    expires_in:    Optional[int] = None


class KeycloakExchange(BaseModel):
    """Authorization code handed to the API by a native client."""
    code:          str
    redirect_uri:  str
    code_verifier: Optional[str] = None


class KeycloakRefresh(BaseModel):
    """Keycloak refresh token (not the server-issued one)."""
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    created_at: Optional[datetime] = None


# Resolve forward references
ArtistDetail.model_rebuild()
