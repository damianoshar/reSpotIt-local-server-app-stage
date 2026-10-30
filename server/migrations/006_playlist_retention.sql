-- migrations/006_playlist_retention.sql
-- Shortlived playlists: a playlist created by the app can carry an expiry.
-- The startup worker unfollows (removes) it from the Spotify library when due.

CREATE TABLE IF NOT EXISTS playlist_retention (
    playlist_spotify_id TEXT        PRIMARY KEY,
    expires_at          TIMESTAMPTZ NOT NULL,
    keep_forever        BOOLEAN     NOT NULL DEFAULT FALSE,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_playlist_retention_expires
    ON playlist_retention (expires_at);
