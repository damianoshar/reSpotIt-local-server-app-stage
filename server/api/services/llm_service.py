"""llm_service.py - Open WebUI proxy for the local llama-server model.

Open WebUI sits in front of llama-server (OpenAI-compatible) and adds user
accounts, conversation history and model management. Keeping the Open WebUI
personal access token on the backend means the phone never holds it.

Environment:
    OPENWEBUI_URL      Base URL (default http://localhost:3000)
    OPENWEBUI_API_KEY  Personal access token (sk-...). Unset = feature disabled.
    OPENWEBUI_MODEL    Optional model id. Default: first model Open WebUI lists.

The endpoints are additive: the frozen /api/v1 library contract is untouched.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterable

from . import mcp_service

import requests

logger = logging.getLogger("llm")

CONNECT_TIMEOUT = 5.0
MODELS_TIMEOUT = 15.0
DEFAULT_READ_TIMEOUT = 30.0

# Diagnostic tracing of every request/response that leaves this module.
# Off by default; set LLM_TRACE=1 on the api service to log full prompts and
# completions (may contain user data -- use only while debugging).
TRACE_CHARS = 20000


def _trace_enabled() -> bool:
    return os.getenv("LLM_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}


def _trace(label: str, payload: Any) -> None:
    if not _trace_enabled():
        return
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(payload)
    if len(text) > TRACE_CHARS:
        text = text[:TRACE_CHARS] + f"... (+{len(text) - TRACE_CHARS} chars)"
    logger.info("LLM TRACE %s: %s", label, text)


class LLMError(RuntimeError):
    """Base class for errors the router turns into a contract envelope."""

    status_code = 502
    code = "llm_error"


class LLMNotConfigured(LLMError):
    status_code = 503
    code = "llm_not_configured"


class LLMUnavailable(LLMError):
    status_code = 502
    code = "llm_unavailable"


class LLMUpstreamError(LLMError):
    status_code = 502
    code = "llm_upstream_error"


class LLMCredentialRejected(LLMUpstreamError):
    """The Open WebUI credential was rejected (stale per-user token)."""
    code = "llm_unauthorized"


class LLMTimeout(LLMError):
    status_code = 504
    code = "llm_timeout"


def _base_url() -> str:
    return os.getenv("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")


_API_KEY_FILE = "/data/.owui_api_key"


def _api_key() -> str:
    # 1. Environment variable (explicit config).
    env_key = os.getenv("OPENWEBUI_API_KEY", "").strip()
    if env_key:
        return env_key
    # 2. Auto-generated key persisted to file.
    try:
        with open(_API_KEY_FILE) as f:
            return f.read().strip()
    except (OSError, IOError):
        return ""


def is_configured(token: str | None = None) -> bool:
    return bool(token or _api_key())


def _headers(token: str | None = None) -> dict[str, str]:
    key = (token or "").strip() or _api_key()
    if not key:
        raise LLMNotConfigured(
            "LLM is not configured. Set OPENWEBUI_API_KEY on the server "
            "(Open WebUI: Settings -> Account -> API Keys)."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: tuple[float, float] | float | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    url = _base_url() + path
    _trace("-> {} {}".format(method, path), json_body)
    try:
        resp = requests.request(
            method,
            url,
            headers=_headers(token),
            json=json_body,
            timeout=timeout if timeout is not None else (CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT),
        )
    except requests.Timeout as exc:
        raise LLMTimeout("The LLM did not answer in time.") from exc
    except requests.RequestException as exc:
        raise LLMUnavailable(f"Cannot reach Open WebUI at {_base_url()}.") from exc

    if resp.status_code >= 400:
        _trace("<- {} {} (error)".format(resp.status_code, path), resp.text[:4000])
        detail: Any = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("error") or ""
            else:
                detail = body
        except ValueError:
            detail = resp.text[:300]
        message = f"Open WebUI returned {resp.status_code}"
        if detail:
            message += f": {detail}"
        if resp.status_code == 401:
            raise LLMCredentialRejected(message)
        raise LLMUpstreamError(message)

    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMUpstreamError("Open WebUI returned a non-JSON response.") from exc
    if not isinstance(data, dict):
        raise LLMUpstreamError("Open WebUI returned an unexpected response.")
    _trace("<- {} {}".format(resp.status_code, path), data)
    return data


def list_models(token: str | None = None) -> list[dict[str, Any]]:
    """Return the models Open WebUI currently exposes."""
    data = _request("GET", "/api/models", timeout=(CONNECT_TIMEOUT, MODELS_TIMEOUT),
                    token=token)
    rows = data.get("data")
    if not isinstance(rows, list):
        raise LLMUpstreamError("Open WebUI returned an unexpected model list.")

    models: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not model_id:
            continue
        models.append(
            {
                "id": str(model_id),
                "name": str(row.get("name") or model_id),
                "owned_by": str(row.get("owned_by") or ""),
            }
        )
    return models


def resolve_model(models: list[dict[str, Any]] | None = None,
                  token: str | None = None) -> str:
    """Pick OPENWEBUI_MODEL when set, else the first model Open WebUI lists."""
    override = os.getenv("OPENWEBUI_MODEL", "").strip()
    if override:
        return override
    available = list_models(token=token) if models is None else models
    if not available:
        raise LLMUnavailable(
            "Open WebUI has no model connected. "
            "Check Admin -> Settings -> Connections."
        )
    return str(available[0]["id"])


def chat(
    messages: Iterable[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    use_tools: bool = True,
    tool_rounds: int = 4,
    token: str | None = None,
    timeout: tuple[float, float] | float | None = None,
) -> dict[str, Any]:
    """Send a non-streaming chat completion through Open WebUI.

    When use_tools is True and at least one MCP server is configured, the model
    is given the merged (curated) tool set from every server and a small
    function-calling loop runs locally: tool calls returned by the model are
    routed to the server that advertised them and their results fed back,
    until the model stops calling tools or tool_rounds is exhausted.
    """
    import json

    chosen = (model or "").strip() or resolve_model(token=token)
    msgs: list[dict[str, Any]] = [dict(m) for m in messages]

    tools: list[dict[str, Any]] = []
    if use_tools and mcp_service.is_configured():
        tools = mcp_service.list_tools()

    tool_calls_log: list[dict[str, Any]] = []
    finish_reason = None
    data: dict[str, Any] = {}
    for _ in range(max(1, tool_rounds)):
        body: dict[str, Any] = {
            "model": chosen,
            "messages": msgs,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_effort": "none",
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = _request("POST", "/api/chat/completions", json_body=body, token=token,
                        timeout=timeout)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMUpstreamError("Open WebUI returned no choices.")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        finish_reason = choice.get("finish_reason")

        tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        if not tool_calls:
            # Final answer
            return {
                "content": message.get("content") or "",
                "reasoning_content": message.get("reasoning_content") or "",
                "finish_reason": finish_reason,
                "model": data.get("model") or chosen,
                "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
                "tool_calls": tool_calls_log,
            }

        # Record assistant turn with tool_calls
        msgs.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        # Execute each tool
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            tc_id = tc.get("id") or ""
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = fn.get("name") or ""
            args_raw = fn.get("arguments")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except (json.JSONDecodeError, TypeError):
                args = {}
            result_text = mcp_service.call_tool(name, args) if name else "Unknown tool."
            tool_calls_log.append({"name": name, "arguments": args, "result": result_text[:500]})
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                }
            )

    # Exhausted rounds: do one final call without tools to get a summary
    body = {
        "model": chosen,
        "messages": msgs,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning_effort": "none",
    }
    data = _request("POST", "/api/chat/completions", json_body=body, token=token,
                    timeout=timeout)
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    return {
        "content": message.get("content") or "",
        "reasoning_content": message.get("reasoning_content") or "",
        "finish_reason": choice.get("finish_reason"),
        "model": data.get("model") or chosen,
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
        "tool_calls": tool_calls_log,
    }


def status(token: str | None = None) -> dict[str, Any]:
    """Configuration + reachability snapshot; never raises."""
    result: dict[str, Any] = {
        "configured": is_configured(token),
        "available": False,
        "base_url": _base_url(),
        "model": os.getenv("OPENWEBUI_MODEL", "").strip() or None,
        "models": 0,
        "error": None,
        "mcp_configured": mcp_service.is_configured(),
        "mcp_tools": len(mcp_service.list_tools()) if mcp_service.is_configured() else 0,
        "mcp_servers": mcp_service.server_status(),
        "per_user_auth": bool(token),
    }
    if not result["configured"]:
        result["error"] = "OPENWEBUI_API_KEY is not set."
        return result

    try:
        models = list_models(token=token)
        result["models"] = len(models)
        result["model"] = result["model"] or (models[0]["id"] if models else None)
        result["available"] = bool(models)
        if not models:
            result["error"] = "No model is connected in Open WebUI."
    except LLMCredentialRejected:
        raise
    except LLMError as exc:
        result["error"] = str(exc)
    return result


# ---------------------------------------------------------------------------
# Phase 0 helpers: URL fetch + structured JSON extraction for AI URL scan
# ---------------------------------------------------------------------------

import json as _json
import re as _re


def html_to_text(html: str) -> str:
    """Strip scripts/styles/tags and collapse whitespace to plain text."""
    text = html or ""
    text = _re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=_re.S | _re.I)
    text = _re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=_re.S | _re.I)
    text = _re.sub(r"<[^>]+>", " ", text)
    return _re.sub(r"\s+", " ", text).strip()


def fetch_page_text(url: str, *, max_chars: int = 12000) -> str:
    """Fetch a URL and return cleaned plain text (tags stripped, truncated)."""
    if not url or not str(url).strip():
        raise LLMError("url is required")
    try:
        resp = requests.get(
            str(url).strip(),
            headers={"User-Agent": "reSpotIt/1.0 (+https://github.com/damianoshar/reSpotIt)"},
            timeout=(CONNECT_TIMEOUT, 30.0),
        )
    except requests.RequestException as exc:
        raise LLMUnavailable(f"Cannot fetch page: {exc}") from exc
    if resp.status_code >= 400:
        raise LLMUpstreamError(f"Page returned HTTP {resp.status_code}")
    text = html_to_text(resp.text or "")
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _parse_json_object(text: str) -> dict:
    if not text:
        raise LLMUpstreamError("LLM returned empty content.")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = _re.sub(r"\n?```$", "", cleaned).strip()
    match = _re.search(r"\{.*\}", cleaned, _re.S)
    if not match:
        match = _re.search(r"\[.*\]", cleaned, _re.S)
    if not match:
        raise LLMUpstreamError("LLM did not return JSON.")
    try:
        data = _json.loads(match.group(0))
    except (ValueError, TypeError) as exc:
        raise LLMUpstreamError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        data = {"items": data}
    return data


_ALBUMS_SYSTEM = (
    "You are a data extractor. Given the text of a web page, extract every album "
    "mentioned (artist + album title). Return ONLY valid JSON with this exact shape: "
    '{"albums": [{"artist": "...", "album": "..."}]}. No prose, no markdown fences. '
    "If none found, return {\"albums\": []}."
)

_CONCERTS_SYSTEM = (
    "You are a data extractor. Given the text of a web page about concerts or "
    "events, extract every concert. Return ONLY valid JSON with this exact shape: "
    '{"concerts": [["artist", "YYYY-MM-DD or empty", "venue"], ...]}. '
    "Each concert is a 3-item ARRAY, not an object: artist first, then date, "
    "then venue. Never add other keys or a url. Keep the JSON compact. "
    "Rules: 'artist' is the specific performer or band only - never an event "
    "title, festival name, tribute, recital or benefit concert. When an entry "
    "has no named performer (for example 'Concert of Baroque Music' or 'A "
    "concert for Children'), skip that entry entirely: do not copy the event "
    "title into 'artist' and do not cut a name down to a single generic word. "
    "Keep every name in the page's original language and script: do not "
    "translate, transliterate or invent names. 'venue' is the place only, "
    "without the city. Infer the year from the page when it is clear; "
    "otherwise leave the date empty. "
    "No prose, no markdown fences. "
    "If none found, return {\"concerts\": []}."
)


_STRICTER_SUFFIX = (
    "\n\nIMPORTANT: Your previous answer was not valid JSON. "
    "Reply with ONLY a single JSON object matching the requested shape "
    '(for concerts: {"concerts": [["artist", "date", "venue"], ...]}). '
    "No prose, no markdown fences, no extra text."
)

# Nudges for degenerate answers from a small local model. They are appended to
# the *user* message, never to the system prompt: llama.cpp reuses the prompt
# cache by prefix, so rewriting the system prompt would re-evaluate the whole
# page (seconds -> minutes) on every retry.
_CONCERT_NUDGE_EMPTY = (
    "\n\n---\n\nIMPORTANT: this text lists real events with dates. Extract every "
    "one of them as a separate [artist, date, venue] array. Never return an "
    "empty list when dated events are present."
)

_CONCERT_NUDGE_DATES = (
    "\n\n---\n\nIMPORTANT: every event in this text has a date next to it. Put "
    "the date in slot 2 of every array as YYYY-MM-DD. When the year is missing, "
    "infer the nearest upcoming year from the page context. Never leave the "
    "date empty when the text shows one."
)

# Separators that unambiguously mean "several performers on one bill".
# "&", "and" and "," are deliberately absent: they are part of single artist
# names too (Simon & Garfunkel, Earth, Wind & Fire), and a wrong split would
# resolve each half separately.
_LINEUP_SEPARATORS = (" + ", " / ", " - ", " – ", " | ")


def _split_lineup(artist: str) -> list[str]:
    """Split "A + B" / "A - B" lineups into individual performers."""
    parts = [artist]
    for sep in _LINEUP_SEPARATORS:
        parts = [chunk for part in parts for chunk in part.split(sep)]
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        name = part.strip(" ,;·•")
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        cleaned.append(name)
    return cleaned or [artist]


def extract_structured(system: str, user_text: str, *, token=None, max_tokens: int = 1024,
                       timeout: tuple[float, float] | float | None = None) -> dict:
    """Run a chat with tools disabled and parse the reply as JSON.

    Retries once with a stricter prompt if the first attempt does not yield
    parseable JSON (per the plan's edge case). On the second failure the raw
    content is included in the error so the caller can surface it.

    ``timeout`` overrides the request read timeout; background callers (the
    concert scan) pass a long one because a local model can take minutes.
    """
    result = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        temperature=0.1,
        max_tokens=max_tokens,
        use_tools=False,
        token=token,
        timeout=timeout,
    )
    content = result.get("content") or ""
    try:
        return _parse_json_object(content)
    except LLMUpstreamError:
        pass

    # Retry once with a stricter prompt.
    retry_result = chat(
        [{"role": "system", "content": system + _STRICTER_SUFFIX},
         {"role": "user", "content": user_text}],
        temperature=0.0,
        max_tokens=max_tokens,
        use_tools=False,
        token=token,
        timeout=timeout,
    )
    retry_content = retry_result.get("content") or ""
    try:
        return _parse_json_object(retry_content)
    except LLMUpstreamError as exc:
        raise LLMUpstreamError(
            f"LLM did not return valid JSON: {exc}. "
            f"Raw response: {retry_content[:500]!r}"
        ) from exc


def extract_albums(text: str, *, token=None) -> dict:
    data = extract_structured(_ALBUMS_SYSTEM, text, token=token, max_tokens=4096)
    albums = data.get("albums") if isinstance(data.get("albums"), list) else []
    out = []
    for a in albums:
        if isinstance(a, dict):
            out.append({
                "artist": str(a.get("artist") or "").strip(),
                "album": str(a.get("album") or "").strip(),
            })
    return {"albums": out}


def extract_concerts(text: str, *, token=None, timeout=None, mode: str | None = None) -> dict:
    """Extract concerts from page text.

    ``mode`` is a retry hint used by the background scan: ``"empty"`` when the
    model returned no rows for a page that clearly lists events, ``"dates"``
    when it returned rows without any date.
    """
    system = _CONCERTS_SYSTEM
    prompt = text
    # The nudge goes on the user message so the cached system+page prefix
    # survives the retry (llama.cpp reuses the prompt cache by prefix).
    if mode == "empty":
        prompt = text + _CONCERT_NUDGE_EMPTY
    elif mode == "dates":
        prompt = text + _CONCERT_NUDGE_DATES
    data = extract_structured(system, prompt, token=token, max_tokens=4096,
                              timeout=timeout)
    concerts = data.get("concerts") if isinstance(data.get("concerts"), list) else []
    out = []
    for c in concerts:
        if isinstance(c, dict):
            # Legacy object shape (and anything the model improvises).
            row = {
                "artist": str(c.get("artist") or "").strip(),
                "date": str(c.get("date") or "").strip(),
                "venue": str(c.get("venue") or "").strip(),
                "url": str(c.get("url") or "").strip(),
            }
        elif isinstance(c, (list, tuple)):
            # Compact [artist, date, venue] row: far fewer generated tokens
            # (~12 vs ~30 per concert), which is the scan's real bottleneck.
            vals = [str(v).strip() if v is not None else "" for v in c]
            vals += [""] * (3 - len(vals))
            row = {
                "artist": vals[0],
                "date": vals[1],
                "venue": vals[2],
                "url": "",
            }
        else:
            continue
        # A lineup ("A + B", "A - B") is one event with several performers;
        # each performer becomes its own row so it can correlate on its own.
        for artist in _split_lineup(row["artist"]):
            out.append({**row, "artist": artist})
    return {"concerts": out}