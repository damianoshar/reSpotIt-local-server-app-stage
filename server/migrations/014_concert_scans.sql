-- 014_concert_scans.sql
-- Click-and-forget AI concert scans (docs/STORAGE-POLICY.md). A scan is
-- created immediately and processed in the background; the worker streams
-- progress into an Open WebUI chat (chat_type=extract_concerts) and stores the
-- extracted rows here. Clients render a ready scan as a pending review list --
-- nothing enters `concerts` until the user saves. Additive only.

CREATE TABLE IF NOT EXISTS concert_scans (
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id          TEXT        NOT NULL,
    source      TEXT        NOT NULL DEFAULT '',
    source_url  TEXT        NOT NULL DEFAULT '',
    source_kind TEXT        NOT NULL DEFAULT 'text',
    status      TEXT        NOT NULL DEFAULT 'running',
    stage       TEXT        NOT NULL DEFAULT 'queued',
    message     TEXT        NOT NULL DEFAULT '',
    items       JSON        NOT NULL DEFAULT '[]',
    error       TEXT        NOT NULL DEFAULT '',
    chat_id     TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS idx_concert_scans_user_created
    ON concert_scans (user_id, created_at DESC);
