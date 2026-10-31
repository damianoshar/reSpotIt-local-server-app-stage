"""mcp_service.py - minimal Streamable HTTP MCP client for reSpotIt.

Exposes tools from one or more MCP servers to llm_service. Stateless: each call
opens a short-lived session (initialize -> request -> close) so the FastAPI
worker never holds an MCP session between requests.

Servers are configured independently and merged into one OpenAI
function-calling tool list:

    Spotify playback     SPOTIFY_MCP_URL  / SPOTIFY_MCP_TOKEN
                         MCP_TOOLS          (default: curated playback set)
    reSpotIt library     RESPOTIT_MCP_URL / RESPOTIT_MCP_TOKEN
                         RESPOTIT_MCP_TOOLS (default: curated library set)

Tool names are kept exactly as the server reports them unless two servers
expose the same name; colliding names are prefixed with the server alias
(e.g. ``spotify_search``). Tool calls are routed back to the server that
advertised the name.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

_log = logging.getLogger("mcp_service")

CONNECT_TIMEOUT = 5.0
REQUEST_TIMEOUT = 30.0

DEFAULT_SPOTIFY_URL = "http://localhost:8090/mcp"
DEFAULT_RESPOTIT_URL = "http://localhost:8091/mcp"

DEFAULT_TOOLS = [
    "search",
    "get_now_playing",
    "play",
    "play_from_search",
    "pause",
    "skip_next",
    "set_volume",
    "get_queue",
    "add_to_queue",
    "get_devices",
]

# Curated library/playlist surface. Destructive tools (playlist_delete,
# library_clear, catalog_remove_saved_albums, ...) are intentionally left out
# of the default set; opt in with RESPOTIT_MCP_TOOLS=all or an explicit list.
DEFAULT_RESPOTIT_TOOLS = [
    "spotify_status",
    "library_stats",
    "library_list_albums",
    "library_list_artists",
    "library_get_album",
    "library_genres",
    "playlist_list",
    "playlist_albums",
    "catalog_search",
    "catalog_artist_albums",
    "playlist_create",
    "playlist_add_tracks",
    "playlist_remove_tracks",
]


@dataclass(frozen=True)
class McpServer:
    """One MCP endpoint plus the subset of its tools to expose."""

    alias: str
    url: str
    token: str
    allowed: frozenset[str] | None = None
    # The NovaLux server requires a loopback Host header when bound to a
    # non-loopback interface (DNS-rebinding defence). Other servers keep the
    # default Host header.
    host_header: str | None = None


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _allowed(env_name: str, default: list[str]) -> frozenset[str] | None:
    """Parse a comma-separated allow-list; empty means the curated default."""
    raw = _env(env_name)
    if raw.lower() == "all":
        return None
    if raw:
        return frozenset(x.strip() for x in raw.split(",") if x.strip())
    return frozenset(default)


def _servers() -> list[McpServer]:
    """Build the configured server list from the environment."""
    servers: list[McpServer] = []

    spotify_token = _env("SPOTIFY_MCP_TOKEN")
    if spotify_token:
        servers.append(
            McpServer(
                alias="spotify",
                url=_env("SPOTIFY_MCP_URL", DEFAULT_SPOTIFY_URL).rstrip("/"),
                token=spotify_token,
                allowed=_allowed("MCP_TOOLS", DEFAULT_TOOLS),
                host_header="127.0.0.1",
            )
        )

    respotit_token = _env("RESPOTIT_MCP_TOKEN")
    if respotit_token:
        servers.append(
            McpServer(
                alias="respotit",
                url=_env("RESPOTIT_MCP_URL", DEFAULT_RESPOTIT_URL).rstrip("/"),
                token=respotit_token,
                allowed=_allowed("RESPOTIT_MCP_TOOLS", DEFAULT_RESPOTIT_TOOLS),
            )
        )

    return servers


def is_configured() -> bool:
    return bool(_servers())


def _config_key(servers: list[McpServer]) -> tuple[Any, ...]:
    return tuple(
        (s.alias, s.url, s.token, s.allowed, s.host_header) for s in servers
    )


# Simple TTL cache for the merged tool list (tools don't change at runtime).
_TOOLS_CACHE: dict[str, Any] = {
    "key": None,
    "ts": 0.0,
    "tools": [],
    "routes": {},
}
_TOOLS_TTL = 300.0  # 5 minutes
_CACHE_LOCK = threading.Lock()


def _headers(server: McpServer, session_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {server.token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if server.host_header:
        headers["Host"] = server.host_header
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _parse_sse(text: str) -> dict[str, Any] | None:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
    # Fallback: maybe plain JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _rpc(
    server: McpServer,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Open a session, send one request, close it. Returns the JSON-RPC result."""
    url = server.url
    _log.info("MCP[%s] _rpc method=%s url=%s", server.alias, method, url)

    # 1. initialize
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "respotit", "version": "1"},
        },
    }
    try:
        resp = requests.post(
            url,
            headers=_headers(server),
            json=init_body,
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"MCP[{server.alias}] unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(
            f"MCP[{server.alias}] initialize failed: "
            f"{resp.status_code} {resp.text[:200]}"
        )
    session_id = resp.headers.get("Mcp-Session-Id")
    parsed = _parse_sse(resp.text)
    if not parsed or "error" in parsed:
        raise RuntimeError(f"MCP[{server.alias}] initialize error: {parsed}")

    # 2. initialized notification
    try:
        requests.post(
            url,
            headers=_headers(server, session_id),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
        )
    except requests.RequestException:
        pass

    # 3. actual request
    body = {"jsonrpc": "2.0", "id": 2, "method": method}
    if params is not None:
        body["params"] = params
    try:
        resp = requests.post(
            url,
            headers=_headers(server, session_id),
            json=body,
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
        )
    except requests.RequestException as exc:
        _close(server, session_id)
        raise RuntimeError(f"MCP[{server.alias}] request failed: {exc}") from exc

    result = None
    parsed = _parse_sse(resp.text)
    if parsed:
        if "error" in parsed:
            raise RuntimeError(f"MCP[{server.alias}] error: {parsed['error']}")
        result = parsed.get("result")

    # 4. close session
    _close(server, session_id)
    return result if result is not None else {}


def _close(server: McpServer, session_id: str | None) -> None:
    if not session_id:
        return
    try:
        requests.delete(
            server.url,
            headers=_headers(server, session_id),
            timeout=(CONNECT_TIMEOUT, 5.0),
        )
    except requests.RequestException:
        pass


def _collect_tools(
    servers: list[McpServer],
) -> tuple[list[dict[str, Any]], dict[str, tuple[McpServer, str]]]:
    """Fetch tools from every server and merge them into one public surface."""
    advertised: list[tuple[McpServer, str, dict[str, Any]]] = []
    for server in servers:
        try:
            result = _rpc(server, "tools/list", {})
        except RuntimeError as exc:
            # One unreachable server must not hide the other's tools.
            _log.warning("MCP[%s] tools/list failed: %s", server.alias, exc)
            continue

        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            continue

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            if not isinstance(name, str) or not name:
                continue
            if server.allowed is not None and name not in server.allowed:
                continue
            advertised.append((server, name, tool))

    counts: dict[str, int] = {}
    for _, name, _ in advertised:
        counts[name] = counts.get(name, 0) + 1

    tools_out: list[dict[str, Any]] = []
    routes: dict[str, tuple[McpServer, str]] = {}
    for server, name, tool in advertised:
        public_name = name if counts[name] == 1 else f"{server.alias}_{name}"
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        tools_out.append(
            {
                "type": "function",
                "function": {
                    "name": public_name,
                    "description": tool.get("description") or "",
                    "parameters": schema,
                },
            }
        )
        routes[public_name] = (server, name)

    return tools_out, routes


def list_tools(*, force: bool = False) -> list[dict[str, Any]]:
    """Return merged MCP tools as OpenAI function-calling tool dicts."""
    servers = _servers()
    if not servers:
        return []

    key = _config_key(servers)
    now = time.time()
    with _CACHE_LOCK:
        cached = (
            not force
            and _TOOLS_CACHE["key"] == key
            and now - _TOOLS_CACHE["ts"] < _TOOLS_TTL
        )
        if cached:
            return list(_TOOLS_CACHE["tools"])

    tools, routes = _collect_tools(servers)

    with _CACHE_LOCK:
        _TOOLS_CACHE.update(key=key, ts=now, tools=tools, routes=routes)
    return list(tools)


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Execute an MCP tool on the server that advertised it."""
    servers = _servers()
    if not servers:
        return "MCP not configured."

    key = _config_key(servers)
    if _TOOLS_CACHE["key"] != key:
        list_tools(force=True)

    route = _TOOLS_CACHE["routes"].get(name)
    if route is None:
        # Cache may be empty or stale (first call, server restarted).
        list_tools(force=True)
        route = _TOOLS_CACHE["routes"].get(name)
    if route is None:
        return f"Unknown tool: {name}"

    server, remote_name = route
    try:
        result = _rpc(
            server,
            "tools/call",
            {"name": remote_name, "arguments": arguments or {}},
        )
    except RuntimeError as exc:
        return f"Tool error: {exc}"

    # Extract text from content array
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif "text" in item:
                        parts.append(str(item["text"]))
            if parts:
                return "\n".join(parts)
        # Fallback
        if "text" in result:
            return str(result["text"])
    return str(result)


def server_status() -> list[dict[str, Any]]:
    """Per-server configuration snapshot for /llm/status (never raises)."""
    servers = _servers()
    if not servers:
        return []
    try:
        list_tools()
    except Exception:  # pragma: no cover - defensive; list_tools swallows RPC errors
        pass

    counts: dict[str, int] = {}
    for server, _remote_name in _TOOLS_CACHE["routes"].values():
        counts[server.alias] = counts.get(server.alias, 0) + 1

    return [
        {
            "name": server.alias,
            "configured": True,
            "url": server.url,
            "tools": counts.get(server.alias, 0),
        }
        for server in servers
    ]
