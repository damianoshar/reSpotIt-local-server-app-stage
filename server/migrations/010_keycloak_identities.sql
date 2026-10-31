-- 010_keycloak_identities.sql
-- Phase 3: map Keycloak subjects to local library owners and keep the
-- per-user Keycloak tokens server-side (Phase 4). Additive only.
--
-- users.id is UUID on Postgres (008_users.sql), so the FK columns must be
-- UUID as well; SQLite keeps TEXT and creates the same tables from the ORM.

CREATE TABLE IF NOT EXISTS keycloak_identities (
    sub           TEXT        PRIMARY KEY,
    user_id       UUID        NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    email         TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_keycloak_identities_user
    ON keycloak_identities (user_id);

CREATE TABLE IF NOT EXISTS keycloak_tokens (
    user_id       UUID        PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    access_token  TEXT        NOT NULL,
    refresh_token TEXT,
    expires_at    TIMESTAMPTZ,
    scope         TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
