#!/usr/bin/env python3
"""Backfill Open WebUI chats written before the model id was stored.

Scan chats created before 2026-11-13 were written with a "Progress"
placeholder as the user message and with no model id. Open WebUI then showed
the placeholder in the sidebar preview and hid the assistant reply, because
it only renders an answer when the parent user message names one model.

This script rewrites those chats in place: the placeholder becomes the
request that started the scan, the progress lines are merged into a single
assistant message and every message names the model, so the chat reads like
the ones the server writes today.

Chats without a "Progress" placeholder are left untouched.

Run it inside the api container (it needs the Open WebUI credentials):

    docker exec -w /app -e PYTHONPATH=/app <api-container> \
        python scripts/backfill_openwebui_chat_messages.py --email <email>

Add --apply to write; without it the script only reports what it would do.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from api.database import SessionLocal
from api.models import User
from api.services import openwebui_service

PLACEHOLDER = "Progress"
TITLE_PREFIX = "Concert scan: "


def request_for(title: str) -> str:
    """The request text a scan chat shows as its user message."""
    if title.startswith(TITLE_PREFIX):
        source = title[len(TITLE_PREFIX):].strip()
        if source.startswith("http"):
            return f"Find the concerts listed on {source}"
        if source == "uploaded file":
            return "Find the concerts listed in the uploaded file"
        if source == "pasted text":
            return "Find the concerts listed in the pasted text"
        return f"Find the concerts listed on {source}"
    return title.strip() or "Find the concerts listed in this page"


def rebuild(chat: dict, title: str, model_id: str) -> dict | None:
    """Return the rewritten chat, or None when there is nothing to rewrite."""
    messages = chat.get("messages")
    if not isinstance(messages, list):
        return None

    user_messages = [
        m for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
        and str(m.get("content") or "").strip() == PLACEHOLDER
    ]
    if not user_messages:
        return None

    assistant_messages = [
        m for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant"
        and str(m.get("content") or "").strip()
    ]
    if not assistant_messages:
        return None

    first_user = dict(user_messages[0])
    last_assistant = dict(assistant_messages[-1])

    merged = "\n\n".join(
        str(m.get("content") or "").strip() for m in assistant_messages
    )

    user_id = str(first_user.get("id") or uuid.uuid4())
    assistant_id = str(last_assistant.get("id") or uuid.uuid4())

    user_message = {
        **first_user,
        "id": user_id,
        "parentId": None,
        "childrenIds": [assistant_id],
        "content": request_for(title),
        "models": [model_id],
    }
    assistant_message = {
        **last_assistant,
        "id": assistant_id,
        "parentId": user_id,
        "childrenIds": [],
        "content": merged,
        "model": model_id,
        "modelName": model_id,
        "done": True,
    }

    chat = dict(chat)
    chat["messages"] = [user_message, assistant_message]
    chat["history"] = {
        "messages": {user_id: user_message, assistant_id: assistant_message},
        "currentId": assistant_id,
    }
    chat["models"] = [model_id]
    return chat


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="the chat owner's email")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.strip().lower()).first()
    finally:
        db.close()
    if user is None:
        print(f"No local user for {args.email}")
        return 2

    token = openwebui_service.get_user_token(user)
    if not token:
        print("No Open WebUI token: trusted auth is disabled.")
        return 2

    model_id = openwebui_service.resolve_model_id(token)
    print(f"model: {model_id}")

    rows = openwebui_service.list_chats(token, limit=args.limit)
    changed = 0
    for row in rows:
        chat_id = str(row.get("id") or "")
        if not chat_id:
            continue
        current = openwebui_service.get_chat(token, chat_id)
        chat = current.get("chat")
        if not isinstance(chat, dict):
            continue
        title = str(current.get("title") or chat.get("title") or "")
        rebuilt = rebuild(chat, title, model_id)
        if rebuilt is None:
            continue
        changed += 1
        print(f"  {chat_id}  {title[:70]}")
        if args.apply:
            openwebui_service.update_chat(token, chat_id, rebuilt)

    print(f"{changed} chat(s) {'rewritten' if args.apply else 'to rewrite'}")
    if not args.apply:
        print("Nothing was written. Re-run with --apply to store the changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
