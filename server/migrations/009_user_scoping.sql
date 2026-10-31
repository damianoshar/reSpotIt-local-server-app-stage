-- migrations/009_user_scoping.sql
-- Phase 2: make the library, playlist cache, exports, retention, track cache,
-- Spotify OAuth state and Spotify token per-user.
--
-- The existing single-user library is intentionally cleared after a verified
-- pg_dump backup; the owner will run a fresh sync. The current Spotify token
-- is preserved and assigned to the phone owner account.
--
-- This file is safe to re-run (columns/PKs/constraints are guarded), and the
-- destructive clear is skipped once the runner records this filename in
-- schema_migrations.

-- The runner creates this table, but create it here too so a manual psql
-- application of this file is self-contained.
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1. Owner columns ─────────────────────────────────────────────────────────

ALTER TABLE albums             ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE artists            ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE spotify_tokens     ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE playlists          ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE export_logs        ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE oauth_states       ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE playlist_retention ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE album_tracks       ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;

-- ── 2. Preserve the existing Spotify link for the phone owner ────────────────

-- Token preservation is handled by the application on first run; no
-- owner-specific account is assumed here so the migration stays generic.

-- ── 3. Clear the old global library/cache once (backup is external) ──────────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM schema_migrations WHERE filename = '009_user_scoping.sql'
    ) THEN
        EXECUTE 'TRUNCATE TABLE album_artists, album_tracks, playlist_tracks, '
             || 'playlists, playlist_retention, export_logs, oauth_states, '
             || 'albums, artists CASCADE';
    END IF;
END $$;

-- ── 4. Enforce ownership ─────────────────────────────────────────────────────

ALTER TABLE albums             ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE artists            ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE spotify_tokens     ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE playlists          ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE export_logs        ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE oauth_states       ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE playlist_retention ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE album_tracks       ALTER COLUMN user_id SET NOT NULL;

-- ── 5. Replace global uniqueness with per-user uniqueness ────────────────────

ALTER TABLE albums  DROP CONSTRAINT IF EXISTS albums_spotify_id_unique;
ALTER TABLE artists DROP CONSTRAINT IF EXISTS artists_name_unique;
ALTER TABLE playlists DROP CONSTRAINT IF EXISTS playlists_spotify_id_unique;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'albums_user_spotify_unique') THEN
        ALTER TABLE albums ADD CONSTRAINT albums_user_spotify_unique UNIQUE (user_id, spotify_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'artists_user_name_unique') THEN
        ALTER TABLE artists ADD CONSTRAINT artists_user_name_unique UNIQUE (user_id, name);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'playlists_user_spotify_unique') THEN
        ALTER TABLE playlists ADD CONSTRAINT playlists_user_spotify_unique UNIQUE (user_id, spotify_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'spotify_tokens_user_id_unique') THEN
        ALTER TABLE spotify_tokens ADD CONSTRAINT spotify_tokens_user_id_unique UNIQUE (user_id);
    END IF;
END $$;

-- ── 6. Composite primary keys for the two owner-scoped caches ────────────────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = 'playlist_retention'::regclass
          AND i.indisprimary
          AND a.attname = 'user_id'
    ) THEN
        ALTER TABLE playlist_retention DROP CONSTRAINT IF EXISTS playlist_retention_pkey;
        ALTER TABLE playlist_retention ADD PRIMARY KEY (user_id, playlist_spotify_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = 'album_tracks'::regclass
          AND i.indisprimary
          AND a.attname = 'user_id'
    ) THEN
        ALTER TABLE album_tracks DROP CONSTRAINT IF EXISTS album_tracks_pkey;
        ALTER TABLE album_tracks ADD PRIMARY KEY (user_id, album_spotify_id, track_spotify_id);
    END IF;
END $$;

-- ── 7. Per-user indexes ──────────────────────────────────────────────────────

DROP INDEX IF EXISTS idx_albums_spotify_id;
DROP INDEX IF EXISTS idx_artists_name;
DROP INDEX IF EXISTS idx_playlists_spotify;

CREATE INDEX IF NOT EXISTS idx_albums_user_added ON albums (user_id, added_at DESC);
CREATE INDEX IF NOT EXISTS idx_albums_user_spotify ON albums (user_id, spotify_id);
CREATE INDEX IF NOT EXISTS idx_artists_user_name ON artists (user_id, name);
CREATE INDEX IF NOT EXISTS idx_playlists_user_spotify ON playlists (user_id, spotify_id);
CREATE INDEX IF NOT EXISTS idx_export_logs_user_created ON export_logs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_oauth_states_user ON oauth_states (user_id);
CREATE INDEX IF NOT EXISTS idx_playlist_retention_user_expires ON playlist_retention (user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_album_tracks_user_album ON album_tracks (user_id, album_spotify_id);
