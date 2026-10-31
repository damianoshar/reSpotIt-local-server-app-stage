"""services/openwebui_service.py - per-user Open WebUI identity (Phase 4).

Open WebUI is the system of record for chat history, so calls made by the API
must be attributed to the signed-in user instead of the shared service key.

Open WebUI supports trusted-header sign-in: ``POST /api/v1/auths/signin`` with
``WEBUI_AUTH_TRUSTED_EMAIL_HEADER`` set returns a normal Open WebUI JWT for
that email (auto-provisioning the account when needed). This module performs
that exchange, caches the token per local user, and hands it to
``llm_service`` as the bearer token.

Security: the header name is only trusted by Open WebUI and must never be
reachable from the public internet. It is opt-in via
``OPENWEBUI_TRUSTED_AUTH=true``; when disabled, the static service key is used
exactly as before.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import jwt
import requests

from ..config import get_settings
from ..models import User

logger = logging.getLogger("openwebui")

CONNECT_TIMEOUT = 5.0
SIGNIN_TIMEOUT = 15.0
DEFAULT_CACHE_SECONDS = 3600

_lock = threading.Lock()
# user_id -> (token, expires_at_epoch)
_cache: dict[str, tuple[str, float]] = {}


class OpenWebUIError(RuntimeError):
    """Raised when a per-user Open WebUI token cannot be obtained."""


def _base_url() -> str:
    return os.getenv("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")


def trusted_auth_enabled() -> bool:
    return get_settings().openwebui_trusted_auth


def _token_expiry(token: str) -> float:
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        exp = claims.get("exp")
        if isinstance(exp, (int, float)):
            return float(exp)
    except jwt.PyJWTError:
        pass
    return time.time() + DEFAULT_CACHE_SECONDS


def _signin(email: str, name: str | None = None) -> str:
    s = get_settings()
    headers = {
        s.openwebui_trusted_header: email,
        "Content-Type": "application/json",
    }
    if name:
        headers[s.openwebui_trusted_name_header] = name
    try:
        resp = requests.post(
            f"{_base_url()}/api/v1/auths/signin",
            json={"email": email, "password": ""},
            headers=headers,
            timeout=(CONNECT_TIMEOUT, SIGNIN_TIMEOUT),
        )
    except requests.RequestException as exc:
        raise OpenWebUIError(f"Cannot reach Open WebUI: {exc}") from exc

    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("error") or ""
        except ValueError:
            detail = resp.text[:200]
        raise OpenWebUIError(
            f"Open WebUI trusted sign-in failed ({resp.status_code})"
            + (f": {detail}" if detail else "")
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise OpenWebUIError("Open WebUI returned non-JSON sign-in response.") from exc
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        raise OpenWebUIError("Open WebUI returned no token.")
    return str(token)


def get_user_token(user: User) -> str | None:
    """Return a cached Open WebUI JWT for this user, or None when disabled.

    The caller falls back to the shared service key on None. Failures are
    logged without the token or header value.
    """
    if not trusted_auth_enabled():
        return None

    user_id = str(user.id)
    now = time.time()
    with _lock:
        cached = _cache.get(user_id)
        if cached and cached[1] - 30 > now:
            return cached[0]

    try:
        token = _signin(user.email, name=None)
    except OpenWebUIError as exc:
        logger.warning("Per-user Open WebUI token unavailable: %s", exc)
        return None

    with _lock:
        _cache[user_id] = (token, _token_expiry(token))
    return token


def invalidate(user_id: str) -> None:
    with _lock:
        _cache.pop(str(user_id), None)


def status() -> dict[str, Any]:
    s = get_settings()
    return {
        "trusted_auth": s.openwebui_trusted_auth,
        "trusted_header": s.openwebui_trusted_header if s.openwebui_trusted_auth else None,
        "cached_users": len(_cache),
    }


def generate_api_key(service_email: str = "mcp-service@respotit.local") -> str | None:
    """Auto-generate an Open WebUI API key via trusted-header sign-in.

    Returns the new key (sk-...) or None if trusted auth is disabled or fails.
    The key is NOT persisted to .env; callers should set OPENWEBUI_API_KEY
    or cache it in process memory.
    """
    if not trusted_auth_enabled():
        return None

    try:
        token = _signin(service_email, name="reSpotIt Service")
    except OpenWebUIError as exc:
        logger.warning("Auto API key generation: sign-in failed: %s", exc)
        return None

    try:
        resp = requests.post(
            f"{_base_url()}/api/v1/auths/api_key",
            headers={"Authorization": f"Bearer {token}"},
            timeout=(CONNECT_TIMEOUT, SIGNIN_TIMEOUT),
        )
    except requests.RequestException as exc:
        logger.warning("Auto API key generation: request failed: %s", exc)
        return None

    if resp.status_code >= 400:
        logger.warning(
            "Auto API key generation: Open WebUI returned %s: %s",
            resp.status_code, resp.text[:200],
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    key = data.get("api_key") or data.get("key") if isinstance(data, dict) else None
    if not key:
        logger.warning("Auto API key generation: no key in response: %s", data)
        return None

    logger.info("Auto-generated Open WebUI API key for %s", service_email)
    return str(key)


# ── Chat history (Phase 5/6) ────────────────────────────────────────────────
#
# Open WebUI owns the chats. These helpers use the per-user token from
# ``get_user_token`` so every read/write lands in that user's own history.

CHAT_TIMEOUT = 20.0


class OpenWebUIChatNotFound(OpenWebUIError):
    """The chat does not exist or belongs to another Open WebUI user."""


class OpenWebUICredentialRejected(OpenWebUIError):
    """The cached per-user Open WebUI token is no longer accepted."""


def _require_token(token: str | None) -> str:
    if not token:
        raise OpenWebUIError(
            "Chat history requires a per-user Open WebUI token "
            "(set OPENWEBUI_TRUSTED_AUTH=true)."
        )
    return token


def _chat_request(
    method: str,
    path: str,
    token: str | None,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = CHAT_TIMEOUT,
) -> Any:
    key = _require_token(token)
    try:
        resp = requests.request(
            method,
            f"{_base_url()}{path}",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=json_body,
            timeout=(CONNECT_TIMEOUT, timeout),
        )
    except requests.RequestException as exc:
        raise OpenWebUIError(f"Cannot reach Open WebUI chats: {exc}") from exc

    if resp.status_code == 404:
        raise OpenWebUIChatNotFound("Chat not found.")
    if resp.status_code == 401:
        # Open WebUI returns 401 (not 404) when a chat exists but belongs to
        # another user, to avoid leaking its existence. Treat that specific
        # response as not-found; other 401s mean the token is stale and the
        # caller should refresh it and retry.
        detail_text = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail_text = str(body.get("detail") or body.get("error") or "")
        except ValueError:
            detail_text = resp.text[:200]
        if "could not find what you're looking for" in detail_text.lower():
            raise OpenWebUIChatNotFound("Chat not found.")
        raise OpenWebUICredentialRejected("Open WebUI rejected the chat credential.")
    if resp.status_code >= 400:
        detail: Any = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("error") or ""
        except ValueError:
            detail = resp.text[:200]
        raise OpenWebUIError(
            f"Open WebUI chat request failed ({resp.status_code})"
            + (f": {detail}" if detail else "")
        )
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise OpenWebUIError("Open WebUI returned non-JSON chat data.") from exc


def list_chats(token: str | None, limit: int = 50) -> list[dict[str, Any]]:
    data = _chat_request("GET", "/api/v1/chats/", token)
    rows = data if isinstance(data, list) else []
    return [row for row in rows if isinstance(row, dict)][: max(1, limit)]


def get_chat(token: str | None, chat_id: str) -> dict[str, Any]:
    data = _chat_request("GET", f"/api/v1/chats/{chat_id}", token)
    if not isinstance(data, dict):
        raise OpenWebUIChatNotFound("Chat not found.")
    return data


def create_chat(
    token: str | None,
    *,
    title: str = "New Chat",
    model: str | None = None,
) -> dict[str, Any]:
    chat = {
        "title": title,
        "models": [model] if model else [],
        "params": {},
        "messages": [],
        "history": {"messages": {}, "currentId": None},
        "tags": [],
        "files": [],
    }
    data = _chat_request("POST", "/api/v1/chats/new", token, json_body={"chat": chat})
    if not isinstance(data, dict) or not data.get("id"):
        raise OpenWebUIError("Open WebUI did not return the created chat.")
    return data


def update_chat(token: str | None, chat_id: str, chat: dict[str, Any]) -> dict[str, Any]:
    data = _chat_request(
        "POST", f"/api/v1/chats/{chat_id}", token, json_body={"chat": chat}
    )
    if not isinstance(data, dict):
        raise OpenWebUIChatNotFound("Chat not found.")
    return data


def delete_chat(token: str | None, chat_id: str) -> bool:
    _chat_request("DELETE", f"/api/v1/chats/{chat_id}", token)
    return True


def history_messages(chat_row: dict[str, Any], limit: int = 20) -> list[dict[str, str]]:
    """Return the last ``limit`` user/assistant turns as chat-completion rows."""
    if limit <= 0:
        return []
    chat = chat_row.get("chat") if isinstance(chat_row, dict) else None
    messages = chat.get("messages") if isinstance(chat, dict) else None
    if not isinstance(messages, list):
        return []
    rows: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            rows.append({"role": role, "content": content})
    return rows[-limit:]


def append_exchange(
    token: str | None,
    chat_id: str,
    user_text: str,
    assistant_text: str,
    *,
    model: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Append one user/assistant turn to an existing Open WebUI chat.

    Both the flat ``messages`` list (what the UI renders) and the
    ``history.messages`` tree (what the UI navigates) are kept in sync, which
    is the same shape the Open WebUI frontend writes.
    """
    import uuid

    row = get_chat(token, chat_id)
    chat = dict(row.get("chat") or {})
    messages = list(chat.get("messages") or [])
    history = dict(chat.get("history") or {})
    tree = dict(history.get("messages") or {})

    parent_id = history.get("currentId")
    if not parent_id and messages:
        last = messages[-1]
        if isinstance(last, dict):
            parent_id = last.get("id")

    now = int(time.time())
    user_id = str(uuid.uuid4())
    assistant_id = str(uuid.uuid4())

    user_message = {
        "id": user_id,
        "parentId": parent_id,
        "childrenIds": [assistant_id],
        "role": "user",
        "content": user_text,
        "timestamp": now,
        "models": [model] if model else [],
    }
    assistant_message = {
        "id": assistant_id,
        "parentId": user_id,
        "childrenIds": [],
        "role": "assistant",
        "content": assistant_text,
        "model": model or "",
        "modelName": model or "",
        "timestamp": now,
        "done": True,
    }

    if parent_id and isinstance(tree.get(parent_id), dict):
        siblings = tree[parent_id].get("childrenIds")
        children = list(siblings) if isinstance(siblings, list) else []
        children.append(user_id)
        tree[parent_id]["childrenIds"] = children

    tree[user_id] = user_message
    tree[assistant_id] = assistant_message
    history["messages"] = tree
    history["currentId"] = assistant_id

    chat["messages"] = messages + [user_message, assistant_message]
    chat["history"] = history

    if title and str(row.get("title") or "").strip() in {"", "New Chat"}:
        chat["title"] = title

    return update_chat(token, chat_id, chat)
