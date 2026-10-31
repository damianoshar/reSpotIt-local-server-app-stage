"""services/chat_session_service.py - the user's current Open WebUI chat.

Open WebUI owns chat messages. This module only stores the pointer to the
chat the user is currently in, so the app can resume without listing every
chat on launch. It is deliberately separate from ``openwebui_service``: that
module talks HTTP, this one talks SQL.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import LLMChatSession


def get_current_chat_id(db: Session, user_id: str) -> str | None:
    row = db.get(LLMChatSession, str(user_id))
    return row.chat_id if row is not None else None


def set_current_chat_id(db: Session, user_id: str, chat_id: str) -> None:
    row = db.get(LLMChatSession, str(user_id))
    if row is None:
        row = LLMChatSession(user_id=str(user_id), chat_id=chat_id)
        db.add(row)
    row.chat_id = chat_id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def clear_current_chat_id(db: Session, user_id: str, chat_id: str | None = None) -> None:
    """Forget the pointer. When ``chat_id`` is given, only clear a match."""
    row = db.get(LLMChatSession, str(user_id))
    if row is None:
        return
    if chat_id is not None and row.chat_id != chat_id:
        return
    db.delete(row)
    db.commit()
