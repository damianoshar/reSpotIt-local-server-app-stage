-- 011_llm_chat_sessions.sql
-- Phase 5: remember the Open WebUI chat each local user is currently in.
-- Open WebUI remains the system of record for the messages themselves.

CREATE TABLE IF NOT EXISTS llm_chat_sessions (
    user_id    UUID        PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    chat_id    TEXT        NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
