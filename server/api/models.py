"""
models.py
---------
SQLAlchemy ORM models for all tables.
Dialect-agnostic: works on both Postgres (Docker) and SQLite (desktop).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Date, ForeignKey, Index, SmallInteger, Integer, Boolean,
    Table, Text, TIMESTAMP, UniqueConstraint, JSON, String,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


album_artists = Table(
    "album_artists",
    Base.metadata,
    Column("album_id",  String(36), ForeignKey("albums.id",  ondelete="CASCADE"), primary_key=True),
    Column("artist_id", String(36), ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True),
    Column("position",  SmallInteger, nullable=False, default=0),
    Index("idx_album_artists_artist", "artist_id"),
    Index("idx_album_artists_album",  "album_id"),
)


class Artist(Base):
    __tablename__ = "artists"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="artists_user_name_unique"),
        Index("idx_artists_user_name", "user_id", "name"),
    )
    id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name       = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    albums = relationship("Album", secondary=album_artists, back_populates="artists")
    def __repr__(self): return f"<Artist name={self.name!r}>"


class User(Base):
    __tablename__ = "users"
    id            = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    created_at    = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    def __repr__(self): return f"<User email={self.email!r}>"


class KeycloakIdentity(Base):
    """Maps a Keycloak ``sub`` to the local user row that owns the library.

    A separate table (rather than a new users column) means ``create_all`` on
    SQLite and the SQL migration on Postgres can add it without touching the
    existing users table.
    """
    __tablename__ = "keycloak_identities"
    __table_args__ = (Index("idx_keycloak_identities_user", "user_id"),)
    sub           = Column(Text, primary_key=True)
    user_id       = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"),
                           nullable=False, unique=True)
    email         = Column(Text, nullable=False)
    created_at    = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    last_login_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    def __repr__(self): return f"<KeycloakIdentity sub={self.sub!r} email={self.email!r}>"


class KeycloakToken(Base):
    """Server-side Keycloak tokens for one local user.

    Never returned to clients and never logged. Phase 4 uses the access token
    for Open WebUI on-behalf-of calls; the refresh token keeps it fresh.
    """
    __tablename__ = "keycloak_tokens"
    user_id       = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"),
                           primary_key=True)
    access_token  = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at    = Column(TIMESTAMP(timezone=True), nullable=True)
    scope         = Column(Text, nullable=True)
    updated_at    = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    def __repr__(self): return f"<KeycloakToken user_id={self.user_id!r}>"


class LLMChatSession(Base):
    """The Open WebUI chat the user is currently talking to.

    Open WebUI owns the messages; this table only remembers which chat to
    resume, so the client does not have to list chats on every launch.
    """
    __tablename__ = "llm_chat_sessions"
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"),
                        primary_key=True)
    chat_id    = Column(Text, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    def __repr__(self): return f"<LLMChatSession user_id={self.user_id!r} chat_id={self.chat_id!r}>"


class Album(Base):
    __tablename__ = "albums"
    __table_args__ = (
        UniqueConstraint("user_id", "spotify_id", name="albums_user_spotify_unique"),
        Index("idx_albums_name",          "name"),
        Index("idx_albums_release_date",  "release_date"),
        Index("idx_albums_popularity",    "popularity"),
        Index("idx_albums_album_type",    "album_type"),
        Index("idx_albums_user_added",    "user_id", "added_at"),
        Index("idx_albums_user_spotify",  "user_id", "spotify_id"),
    )
    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id      = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    spotify_id   = Column(Text, nullable=False)
    name         = Column(Text, nullable=False)
    release_date = Column(Date)
    total_tracks = Column(SmallInteger)
    album_type   = Column(Text)
    label        = Column(Text)
    popularity   = Column(SmallInteger)
    genres       = Column(JSON)
    spotify_url  = Column(Text)
    image_url    = Column(Text)
    image_file   = Column(Text)
    added_at     = Column(TIMESTAMP(timezone=True))
    created_at   = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    artists = relationship("Artist", secondary=album_artists, back_populates="albums", order_by=album_artists.c.position)
    def __repr__(self): return f"<Album name={self.name!r}>"


class SpotifyToken(Base):
    __tablename__ = "spotify_tokens"
    __table_args__ = (UniqueConstraint("user_id", name="spotify_tokens_user_id_unique"),)
    id            = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id       = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_token  = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    expires_at    = Column(TIMESTAMP(timezone=True))
    created_at    = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at    = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    state       = Column(Text, primary_key=True)
    user_id     = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at  = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class AlbumTrack(Base):
    __tablename__ = "album_tracks"
    __table_args__ = (
        UniqueConstraint("user_id", "album_spotify_id", "track_spotify_id", name="album_tracks_pk"),
        Index("idx_album_tracks_user_album", "user_id", "album_spotify_id"),
    )
    user_id          = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    album_spotify_id = Column(Text, primary_key=True)
    track_spotify_id = Column(Text, primary_key=True)
    name             = Column(Text, nullable=False, default="")
    artist_names     = Column(Text, nullable=False, default="")
    disc_number      = Column(Integer)
    track_number     = Column(Integer)
    duration_ms      = Column(Integer)
    uri              = Column(Text)
    explicit         = Column(Boolean, nullable=False, default=False)
    preview_url      = Column(Text)
    album_name       = Column(Text, nullable=False, default="")
    album_image_url  = Column(Text)
    release_year     = Column(Integer)
    updated_at       = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class Playlist(Base):
    __tablename__ = "playlists"
    __table_args__ = (UniqueConstraint("user_id", "spotify_id", name="playlists_user_spotify_unique"),)
    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id     = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    spotify_id  = Column(Text, nullable=False)
    name        = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    image_url   = Column(Text)
    owner_name  = Column(Text)
    track_count = Column(Integer, nullable=False, default=0)
    public      = Column(Boolean, nullable=False, default=False)
    synced_at   = Column(TIMESTAMP(timezone=True))
    created_at  = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at  = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    id               = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id      = Column(String(36), ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    position         = Column(Integer, nullable=False, default=0)
    spotify_id       = Column(Text)
    name             = Column(Text, nullable=False, default="")
    artist_names     = Column(Text, nullable=False, default="")
    album_spotify_id = Column(Text)
    album_name       = Column(Text, nullable=False, default="")
    album_image_url  = Column(Text)
    release_year     = Column(Integer)
    duration_ms      = Column(Integer)
    track_number     = Column(Integer)
    created_at       = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class ExportLog(Base):
    __tablename__ = "export_logs"
    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id     = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename    = Column(Text, nullable=False)
    row_count   = Column(Integer, nullable=False, default=0)
    created_at  = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class PlaylistRetention(Base):
    __tablename__ = "playlist_retention"
    __table_args__ = (UniqueConstraint("user_id", "playlist_spotify_id", name="playlist_retention_pk"),)
    user_id             = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    playlist_spotify_id = Column(Text, primary_key=True)
    expires_at          = Column(TIMESTAMP(timezone=True), nullable=False)
    keep_forever        = Column(Boolean, nullable=False, default=False)
    last_error          = Column(Text)
    created_at          = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at          = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class Concert(Base):
    """Server-canonical concert rows (docs/STORAGE-POLICY.md).

    ``id`` is the client-generated concert id, so the primary key is the
    per-user composite ``(user_id, id)`` (mirrors ``AlbumTrack``). ``created_at``
    holds the client's ISO string; ``added_at`` is the server row timestamp.
    """
    __tablename__ = "concerts"
    __table_args__ = (Index("idx_concerts_user_date", "user_id", "date"),)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    id         = Column(Text, primary_key=True)
    artist     = Column(Text, nullable=False, default="")
    artist_id  = Column(Text, nullable=False, default="")
    title      = Column(Text, nullable=False, default="")
    date       = Column(Text, nullable=False, default="")
    venue      = Column(Text, nullable=False, default="")
    url        = Column(Text, nullable=False, default="")
    source_url = Column(Text, nullable=False, default="")
    followed   = Column(Boolean, nullable=False, default=False)
    created_at = Column(Text, nullable=False, default="")
    added_at   = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    def __repr__(self): return f"<Concert artist={self.artist!r} date={self.date!r}>"


class HiddenAlbum(Base):
    """Server-canonical hidden-duplicate rows (docs/STORAGE-POLICY.md).

    ``spotify_id`` is the album's Spotify id (clients call it ``id``); the album
    metadata is cached so a restore can rebuild the row without the network.
    """
    __tablename__ = "hidden_albums"
    __table_args__ = (Index("idx_hidden_albums_user", "user_id"),)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    spotify_id = Column(Text, primary_key=True)
    title      = Column(Text, nullable=False, default="")
    artist     = Column(Text, nullable=False, default="")
    year       = Column(Integer)
    genre      = Column(Text, nullable=False, default="")
    album_type = Column(Text, nullable=False, default="album")
    image_url  = Column(Text)
    added_at   = Column(Text, nullable=False, default="")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    def __repr__(self): return f"<HiddenAlbum spotify_id={self.spotify_id!r}>"