"""llm_service.py - Open WebUI proxy for the local llama-server model.

Open WebUI sits in front of llama-server (OpenAI-compatible) and adds user
accounts, conversation history and model management. Keeping the Open WebUI
personal access token on the backend means the phone never holds it.

Environment:
    OPENWEBUI_URL      Base URL (default http://localhost:3000)
    OPENWEBUI_API_KEY  Personal access token (sk-...). Unset = feature disabled.
    OPENWEBUI_MODEL    Optional model id. Default: first model Open WebUI lists.
    LLM_TIMEOUT        Read timeout in seconds (default 180; 35B models are slow).

The endpoints are additive: the frozen /api/v1 library contract is untouched.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from . import mcp_service

import requests

DEFAULT_TIMEOUT = 180.0
CONNECT_TIMEOUT = 5.0
MODELS_TIMEOUT = 15.0


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


def _timeout() -> float:
    try:
        return max(10.0, float(os.getenv("LLM_TIMEOUT", "180")))
    except ValueError:
        return DEFAULT_TIMEOUT


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
    try:
        resp = requests.request(
            method,
            url,
            headers=_headers(token),
            json=json_body,
            timeout=timeout if timeout is not None else (CONNECT_TIMEOUT, _timeout()),
        )
    except requests.Timeout as exc:
        raise LLMTimeout("The LLM did not answer in time.") from exc
    except requests.RequestException as exc:
        raise LLMUnavailable(f"Cannot reach Open WebUI at {_base_url()}.") from exc

    if resp.status_code >= 400:
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
        data = _request("POST", "/api/chat/completions", json_body=body, token=token)

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
    data = _request("POST", "/api/chat/completions", json_body=body, token=token)
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
    html = resp.text or ""
    text = _re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=_re.S | _re.I)
    text = _re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=_re.S | _re.I)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
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
    '{"concerts": [{"artist": "...", "date": "YYYY-MM-DD or empty", '
    '"venue": "...", "url": "..."}]}. No prose, no markdown fences. '
    "If none found, return {\"concerts\": []}."
)


_STRICTER_SUFFIX = (
    "\n\nIMPORTANT: Your previous answer was not valid JSON. "
    "Reply with ONLY a single JSON object matching the requested shape. "
    "No prose, no markdown fences, no extra text."
)


def extract_structured(system: str, user_text: str, *, token=None, max_tokens: int = 1024) -> dict:
    """Run a chat with tools disabled and parse the reply as JSON.

    Retries once with a stricter prompt if the first attempt does not yield
    parseable JSON (per the plan's edge case). On the second failure the raw
    content is included in the error so the caller can surface it.
    """
    result = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        temperature=0.1,
        max_tokens=max_tokens,
        use_tools=False,
        token=token,
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


def extract_concerts(text: str, *, token=None) -> dict:
    data = extract_structured(_CONCERTS_SYSTEM, text, token=token, max_tokens=4096)
    concerts = data.get("concerts") if isinstance(data.get("concerts"), list) else []
    out = []
    for c in concerts:
        if isinstance(c, dict):
            out.append({
                "artist": str(c.get("artist") or "").strip(),
                "date": str(c.get("date") or "").strip(),
                "venue": str(c.get("venue") or "").strip(),
                "url": str(c.get("url") or "").strip(),
            })
    return {"concerts": out}