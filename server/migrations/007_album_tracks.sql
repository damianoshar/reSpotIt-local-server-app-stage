-- migrations/007_album_tracks.sql
-- Cached album track lists, used by the album track sheet and the
-- "remove album from playlist" flow. Populated on demand (or by a sync with
-- "Include track lists" enabled).

CREATE TABLE IF NOT EXISTS album_tracks (
    album_spotify_id TEXT        NOT NULL,
    track_spotify_id TEXT        NOT NULL,
    name             TEXT        NOT NULL DEFAULT '',
    artist_names     TEXT        NOT NULL DEFAULT '',
    disc_number      INT,
    track_number     INT,
    duration_ms      INT,
    uri              TEXT,
    explicit         BOOLEAN     NOT NULL DEFAULT FALSE,
    preview_url      TEXT,
    album_name       TEXT        NOT NULL DEFAULT '',
    album_image_url  TEXT,
    release_year     INT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (album_spotify_id, track_spotify_id)
);

CREATE INDEX IF NOT EXISTS idx_album_tracks_album ON album_tracks (album_spotify_id);
