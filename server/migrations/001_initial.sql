-- migrations/001_initial.sql
-- Run once to set up the schema.

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- for gen_random_uuid()

-- ── Artists ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS artists (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT artists_name_unique UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_artists_name ON artists (name);

-- ── Albums ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS albums (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    spotify_id    TEXT        NOT NULL,
    name          TEXT        NOT NULL,
    release_date  DATE,
    total_tracks  SMALLINT,
    album_type    TEXT,
    label         TEXT,
    popularity    SMALLINT,
    genres        TEXT[],           -- stored as a Postgres array
    spotify_url   TEXT,
    image_url     TEXT,
    image_file    TEXT,             -- relative path inside /data/images/
    added_at      TIMESTAMPTZ,      -- when the user saved it to their library
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT albums_spotify_id_unique UNIQUE (spotify_id)
);

CREATE INDEX IF NOT EXISTS idx_albums_spotify_id  ON albums (spotify_id);
CREATE INDEX IF NOT EXISTS idx_albums_name        ON albums (name);
CREATE INDEX IF NOT EXISTS idx_albums_release_date ON albums (release_date);
CREATE INDEX IF NOT EXISTS idx_albums_popularity  ON albums (popularity);
CREATE INDEX IF NOT EXISTS idx_albums_album_type  ON albums (album_type);

-- ── Album ↔ Artist join ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS album_artists (
    album_id   UUID NOT NULL REFERENCES albums(id)  ON DELETE CASCADE,
    artist_id  UUID NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    position   SMALLINT NOT NULL DEFAULT 0,    -- order of artists on the album

    PRIMARY KEY (album_id, artist_id)
);

CREATE INDEX IF NOT EXISTS idx_album_artists_artist ON album_artists (artist_id);
CREATE INDEX IF NOT EXISTS idx_album_artists_album  ON album_artists (album_id);
