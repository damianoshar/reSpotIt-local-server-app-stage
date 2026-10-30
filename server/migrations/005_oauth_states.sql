-- migrations/005_oauth_states.sql
-- Short-lived OAuth `state` values for the Spotify authorization flow
-- (CSRF protection). Each row is consumed (deleted) on callback.

CREATE TABLE IF NOT EXISTS oauth_states (
    state       TEXT        PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_created ON oauth_states (created_at);