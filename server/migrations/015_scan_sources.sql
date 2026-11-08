-- 015_scan_sources.sql
-- Persist the full source text of an AI scan so it can be re-run and audited.
-- Today `concert_scans.source` keeps only a 120-char preview. Additive only.
--
-- `scan_sources` is user-scoped (FK CASCADE), mirroring every other canonical
-- table. `concert_scans` gains a nullable link and a chunk count so clients can
-- show extraction progress without loading the source.

CREATE TABLE IF NOT EXISTS scan_sources (
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id         TEXT        NOT NULL,
    kind       TEXT        NOT NULL DEFAULT 'text',   -- text | url | file
    source_url TEXT        NOT NULL DEFAULT '',
    content    TEXT        NOT NULL DEFAULT '',
    sha256     TEXT        NOT NULL DEFAULT '',
    chars      INTEGER     NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS idx_scan_sources_user_created
    ON scan_sources (user_id, created_at DESC);

ALTER TABLE concert_scans ADD COLUMN IF NOT EXISTS source_id TEXT;
ALTER TABLE concert_scans ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0;