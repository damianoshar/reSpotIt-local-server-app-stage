-- migrations/002_spotify_tokens.sql
-- Single-row Spotify OAuth token cache (replaces /data/.spotify_token.json).

CREATE TABLE IF NOT EXISTS spotify_tokens (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    access_token  TEXT        NOT NULL,
    refresh_token TEXT        NOT NULL,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
