"""routers/llm.py - local LLM access through Open WebUI.

  GET    /api/v1/llm/status          - configuration + reachability
  GET    /api/v1/llm/models          - models Open WebUI exposes
  POST   /api/v1/llm/chat            - non-streaming chat completion
  GET    /api/v1/llm/chats           - the user's Open WebUI chats
  GET    /api/v1/llm/chats/current   - the chat this user is currently in
  POST   /api/v1/llm/chats           - create a chat
  GET    /api/v1/llm/chats/{id}      - one chat with its messages
  DELETE /api/v1/llm/chats/{id}      - delete a chat

Additive: the frozen library contract is untouched. Every route needs the
same server JWT (or a Keycloak access token) as the rest of /api/v1; the
Open WebUI credential stays server-side.

Phase 4: when OPENWEBUI_TRUSTED_AUTH is enabled, the API exchanges the
signed-in user's email for a per-user Open WebUI JWT, so chat activity is
attributed to that user instead of the shared service key.

Phase 5/6: chats are stored in Open WebUI under that same per-user identity.
``POST /chat`` can continue a chat (``chat_id``), prepends its last N turns
(``use_history`` / ``history_limit``) and appends the new exchange
(``persist``). The pointer to the current chat is kept locally in
``llm_chat_sessions``.
"""
import logging
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..contract import ContractError
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services import chat_session_service, llm_service, openwebui_service

logger = logging.getLogger("llm")

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

MAX_MESSAGE_CHARS = 20_000
MAX_MESSAGES = 40
MAX_CHAT_ID_CHARS = 128


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class LLMChatBody(BaseModel):
    messages: list[LLMMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    model: str | None = Field(default=None, max_length=512)
    system: str | None = Field(default=None, max_length=MAX_MESSAGE_CHARS)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    use_tools: bool = Field(default=True)
    # Phase 5/6: continue a stored chat instead of starting from scratch.
    chat_id: str | None = Field(default=None, max_length=MAX_CHAT_ID_CHARS)
    use_history: bool = Field(default=True)
    history_limit: int = Field(default=20, ge=0, le=MAX_MESSAGES)
    persist: bool = Field(default=True)


class LLMChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=512)


def _contract_error(exc: llm_service.LLMError) -> ContractError:
    return ContractError(exc.status_code, exc.code, str(exc))


def _chat_error(exc: openwebui_service.OpenWebUIError) -> ContractError:
    if isinstance(exc, openwebui_service.OpenWebUIChatNotFound):
        return ContractError(404, "llm_chat_not_found", str(exc))
    return ContractError(502, "llm_chat_error", str(exc))


def _status_for_user(user: User) -> dict:
    token = openwebui_service.get_user_token(user)
    try:
        return llm_service.status(token=token)
    except llm_service.LLMCredentialRejected:
        if not token:
            raise
        openwebui_service.invalidate(str(user.id))
        token = openwebui_service.get_user_token(user)
        return llm_service.status(token=token)


async def _with_user_token(user: User, fn, *args, **kwargs):
    """Run an Open WebUI LLM call as the signed-in user, retrying once on 401.

    A recreated Open WebUI container can invalidate cached JWTs; the retry
    performs a fresh trusted-header sign-in before giving up.
    """
    token = await run_in_threadpool(openwebui_service.get_user_token, user)
    try:
        return await run_in_threadpool(fn, *args, token=token, **kwargs)
    except llm_service.LLMCredentialRejected:
        if not token:
            raise
        openwebui_service.invalidate(str(user.id))
        token = await run_in_threadpool(openwebui_service.get_user_token, user)
        return await run_in_threadpool(fn, *args, token=token, **kwargs)


async def _chat_token(user: User) -> str:
    token = await run_in_threadpool(openwebui_service.get_user_token, user)
    if not token:
        raise ContractError(
            503,
            "llm_chat_unavailable",
            "Chat history requires OPENWEBUI_TRUSTED_AUTH=true and a "
            "reachable Open WebUI.",
        )
    return token


async def _with_chat_token(user: User, fn, *args, **kwargs):
    """Run a chat-history call with the per-user token (token is first arg)."""
    token = await _chat_token(user)
    try:
        return await run_in_threadpool(fn, token, *args, **kwargs)
    except openwebui_service.OpenWebUICredentialRejected:
        openwebui_service.invalidate(str(user.id))
        token = await _chat_token(user)
        return await run_in_threadpool(fn, token, *args, **kwargs)


@router.get("/status", summary="LLM configuration and reachability")
def status(user: User = Depends(get_current_user)):
    data = _status_for_user(user)
    data["chat_history"] = openwebui_service.trusted_auth_enabled()
    return {
        "data": data,
        "identity": openwebui_service.status(),
    }


@router.get("/models", summary="Models exposed by Open WebUI")
async def models(user: User = Depends(get_current_user)):
    try:
        return {"data": await _with_user_token(user, llm_service.list_models)}
    except llm_service.LLMError as exc:
        raise _contract_error(exc) from exc


@router.get("/chats", summary="The signed-in user's Open WebUI chats")
async def list_chats(user: User = Depends(get_current_user)):
    try:
        rows = await _with_chat_token(user, openwebui_service.list_chats)
        return {"data": rows}
    except openwebui_service.OpenWebUIError as exc:
        raise _chat_error(exc) from exc


@router.get("/chats/current", summary="The chat this user is currently in")
async def current_chat(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat_id = chat_session_service.get_current_chat_id(db, str(user.id))
    if not chat_id:
        return {"data": None}
    try:
        row = await _with_chat_token(user, openwebui_service.get_chat, chat_id)
        return {"data": row}
    except openwebui_service.OpenWebUIChatNotFound:
        chat_session_service.clear_current_chat_id(db, str(user.id), chat_id)
        return {"data": None}
    except openwebui_service.OpenWebUIError as exc:
        raise _chat_error(exc) from exc


@router.delete("/chats/current", summary="Forget the current chat without deleting it")
async def clear_current_chat(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat_session_service.clear_current_chat_id(db, str(user.id))
    return {"data": {"cleared": True}}


@router.post("/chats", summary="Create a new Open WebUI chat")
async def create_chat(
    body: LLMChatCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    title = (body.title or "").strip() or "New Chat"
    try:
        row = await _with_chat_token(
            user, openwebui_service.create_chat, title=title, model=body.model
        )
    except openwebui_service.OpenWebUIError as exc:
        raise _chat_error(exc) from exc
    chat_session_service.set_current_chat_id(db, str(user.id), row["id"])
    return {"data": row}


@router.get("/chats/{chat_id}", summary="One Open WebUI chat with messages")
async def get_chat(chat_id: str, user: User = Depends(get_current_user)):
    try:
        row = await _with_chat_token(user, openwebui_service.get_chat, chat_id)
        return {"data": row}
    except openwebui_service.OpenWebUIError as exc:
        raise _chat_error(exc) from exc


@router.delete("/chats/{chat_id}", summary="Delete an Open WebUI chat")
async def delete_chat(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        await _with_chat_token(user, openwebui_service.delete_chat, chat_id)
    except openwebui_service.OpenWebUIError as exc:
        raise _chat_error(exc) from exc
    chat_session_service.clear_current_chat_id(db, str(user.id), chat_id)
    return {"data": {"deleted": True, "chat_id": chat_id}}


@router.post("/chat", summary="Chat with the local model")
async def chat(
    body: LLMChatBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages: list[dict[str, str]] = []
    if body.system:
        messages.append({"role": "system", "content": body.system})

    # Phase 6: load the stored conversation before the new turn.
    if body.chat_id and body.use_history and body.history_limit > 0:
        try:
            row = await _with_chat_token(user, openwebui_service.get_chat, body.chat_id)
        except openwebui_service.OpenWebUIError as exc:
            raise _chat_error(exc) from exc
        messages.extend(openwebui_service.history_messages(row, body.history_limit))

    messages.extend(message.model_dump() for message in body.messages)

    try:
        result = await _with_user_token(
            user,
            llm_service.chat,
            messages,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            use_tools=body.use_tools,
        )
    except llm_service.LLMError as exc:
        raise _contract_error(exc) from exc

    chat_id = body.chat_id
    persisted = False
    if body.persist:
        user_text = next(
            (m.content for m in reversed(body.messages) if m.role == "user"), ""
        ).strip()
        try:
            if not chat_id:
                row = await _with_chat_token(
                    user,
                    openwebui_service.create_chat,
                    title=user_text[:80] or "New Chat",
                    model=result.get("model"),
                )
                chat_id = row["id"]
            await _with_chat_token(
                user,
                openwebui_service.append_exchange,
                chat_id,
                user_text,
                str(result.get("content") or ""),
                model=result.get("model"),
                title=user_text[:80] or None,
            )
            persisted = True
            chat_session_service.set_current_chat_id(db, str(user.id), chat_id)
        except openwebui_service.OpenWebUIError as exc:
            # The answer is still useful; report that it was not stored.
            logger.warning("Could not persist chat turn: %s", exc)

    payload = dict(result)
    payload["chat_id"] = chat_id
    payload["persisted"] = persisted
    return {"data": payload}
