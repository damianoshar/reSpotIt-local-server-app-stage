-- 012_concerts.sql
-- Storage policy (docs/STORAGE-POLICY.md): concerts become server-canonical so
-- every tool works in remote mode and the data syncs both ways.
--
-- `id` is the client-generated concert id (stable across React/Kotlin), so the
-- primary key is the per-user composite (user_id, id) -- the same pattern as
-- album_tracks. `created_at` keeps the client's ISO string; `added_at` is the
-- server-side row timestamp. Additive only.

CREATE TABLE IF NOT EXISTS concerts (
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id         TEXT        NOT NULL,
    artist     TEXT        NOT NULL DEFAULT '',
    artist_id  TEXT        NOT NULL DEFAULT '',
    title      TEXT        NOT NULL DEFAULT '',
    date       TEXT        NOT NULL DEFAULT '',
    venue      TEXT        NOT NULL DEFAULT '',
    url        TEXT        NOT NULL DEFAULT '',
    source_url TEXT        NOT NULL DEFAULT '',
    followed   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at TEXT        NOT NULL DEFAULT '',
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS idx_concerts_user_date
    ON concerts (user_id, date);
