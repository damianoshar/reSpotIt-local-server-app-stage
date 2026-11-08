-- 013_hidden_albums.sql
-- Storage policy (docs/STORAGE-POLICY.md): hidden duplicates become
-- server-canonical so the duplicate finder works in remote mode and the hidden
-- set syncs both ways. `spotify_id` is the album's Spotify id (what clients call
-- `id`); the full album metadata is cached so a restore can rebuild the row
-- without a network round-trip. Additive only.

CREATE TABLE IF NOT EXISTS hidden_albums (
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spotify_id TEXT        NOT NULL,
    title      TEXT        NOT NULL DEFAULT '',
    artist     TEXT        NOT NULL DEFAULT '',
    year       INTEGER,
    genre      TEXT        NOT NULL DEFAULT '',
    album_type TEXT        NOT NULL DEFAULT 'album',
    image_url  TEXT,
    added_at   TEXT        NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, spotify_id)
);

CREATE INDEX IF NOT EXISTS idx_hidden_albums_user
    ON hidden_albums (user_id);
