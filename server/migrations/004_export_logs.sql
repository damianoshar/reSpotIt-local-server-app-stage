-- migrations/004_export_logs.sql
-- Audit trail of CSV exports, surfaced by GET /api/v1/exports/history
-- (mirrors the elixir `export_logs` table).

CREATE TABLE IF NOT EXISTS export_logs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT        NOT NULL,
    row_count   INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS export_logs_created_at_idx ON export_logs (created_at DESC);
