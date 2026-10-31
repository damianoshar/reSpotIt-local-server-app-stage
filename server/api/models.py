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