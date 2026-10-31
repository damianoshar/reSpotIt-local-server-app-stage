-- migrations/003_playlists.sql
-- Cached Spotify playlists + their tracks (powers the playlist dashboard:
-- deduped album grid, resync, export — all without re-hitting Spotify).

CREATE TABLE IF NOT EXISTS playlists (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    spotify_id  TEXT        NOT NULL,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    image_url   TEXT,
    owner_name  TEXT,
    track_count INT         NOT NULL DEFAULT 0,
    public      BOOLEAN     NOT NULL DEFAULT FALSE,
    synced_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT playlists_spotify_id_unique UNIQUE (spotify_id)
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    playlist_id      UUID        NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position         INT         NOT NULL DEFAULT 0,
    spotify_id       TEXT,
    name             TEXT        NOT NULL DEFAULT '',
    artist_names     TEXT        NOT NULL DEFAULT '',
    album_spotify_id TEXT,
    album_name       TEXT        NOT NULL DEFAULT '',
    album_image_url  TEXT,
    release_year     INT,
    duration_ms      INT,
    track_number     INT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON playlist_tracks (playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlists_spotify ON playlists (spotify_id);
