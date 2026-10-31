"""Tests for the multi-server MCP client.

Mocked only: these tests never touch a real MCP server.

Run from the server directory:

    python -m pytest tests/test_mcp_service.py -q
"""
import os
import unittest
from unittest.mock import patch

from api.services import mcp_service


def _tool(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "inputSchema": {"type": "object", "properties": {}},
    }


def _reset_cache() -> None:
    mcp_service._TOOLS_CACHE.update(key=None, ts=0.0, tools=[], routes={})


class McpServiceTests(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        self.env = patch.dict(
            os.environ,
            {
                "SPOTIFY_MCP_URL": "http://spotify.test/mcp",
                "SPOTIFY_MCP_TOKEN": "spotify-token",
                "MCP_TOOLS": "",
                "RESPOTIT_MCP_URL": "http://respotit.test/mcp",
                "RESPOTIT_MCP_TOKEN": "respotit-token",
                "RESPOTIT_MCP_TOOLS": "",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        _reset_cache()

    def test_not_configured_without_tokens(self):
        with patch.dict(os.environ, {"SPOTIFY_MCP_TOKEN": "", "RESPOTIT_MCP_TOKEN": ""}):
            self.assertFalse(mcp_service.is_configured())
            self.assertEqual(mcp_service.list_tools(force=True), [])
            self.assertEqual(mcp_service.server_status(), [])

    def test_merges_tools_from_both_servers(self):
        def fake_rpc(server, method, params=None):
            self.assertEqual(method, "tools/list")
            if server.alias == "spotify":
                return {"tools": [_tool("search"), _tool("get_now_playing")]}
            return {"tools": [_tool("library_stats"), _tool("playlist_list")]}

        with patch.object(mcp_service, "_rpc", side_effect=fake_rpc):
            tools = mcp_service.list_tools(force=True)

        names = {t["function"]["name"] for t in tools}
        self.assertEqual(
            names,
            {"search", "get_now_playing", "library_stats", "playlist_list"},
        )

    def test_routes_tool_calls_to_owning_server(self):
        calls = []

        def fake_rpc(server, method, params=None):
            if method == "tools/list":
                if server.alias == "spotify":
                    return {"tools": [_tool("search")]}
                return {"tools": [_tool("library_stats")]}
            calls.append((server.alias, method, params))
            return {"content": [{"type": "text", "text": "42 albums"}]}

        with patch.object(mcp_service, "_rpc", side_effect=fake_rpc):
            mcp_service.list_tools(force=True)
            result = mcp_service.call_tool("library_stats", {"limit": 1})

        self.assertEqual(result, "42 albums")
        self.assertEqual(calls[0][0], "respotit")
        self.assertEqual(calls[0][2]["name"], "library_stats")

    def test_colliding_names_are_prefixed(self):
        with patch.dict(
            os.environ, {"MCP_TOOLS": "search", "RESPOTIT_MCP_TOOLS": "search"}
        ):
            def fake_rpc(server, method, params=None):
                if method == "tools/list":
                    return {"tools": [_tool("search")]}
                return {"content": [{"type": "text", "text": server.alias}]}

            with patch.object(mcp_service, "_rpc", side_effect=fake_rpc):
                tools = mcp_service.list_tools(force=True)
                names = {t["function"]["name"] for t in tools}
                self.assertEqual(names, {"spotify_search", "respotit_search"})
                self.assertEqual(mcp_service.call_tool("respotit_search", {}), "respotit")
                self.assertEqual(mcp_service.call_tool("spotify_search", {}), "spotify")

    def test_one_server_down_keeps_the_other(self):
        def fake_rpc(server, method, params=None):
            if server.alias == "spotify":
                raise RuntimeError("MCP[spotify] unreachable: down")
            return {"tools": [_tool("library_stats")]}

        with patch.object(mcp_service, "_rpc", side_effect=fake_rpc):
            tools = mcp_service.list_tools(force=True)

        self.assertEqual(
            [t["function"]["name"] for t in tools], ["library_stats"]
        )

    def test_default_respotit_set_excludes_destructive_tools(self):
        def fake_rpc(server, method, params=None):
            if server.alias == "spotify":
                return {"tools": []}
            return {
                "tools": [
                    _tool("library_stats"),
                    _tool("playlist_create"),
                    _tool("playlist_delete"),
                    _tool("library_clear"),
                ]
            }

        with patch.object(mcp_service, "_rpc", side_effect=fake_rpc):
            tools = mcp_service.list_tools(force=True)

        names = {t["function"]["name"] for t in tools}
        self.assertEqual(names, {"library_stats", "playlist_create"})

    def test_server_status_reports_per_server_counts(self):
        def fake_rpc(server, method, params=None):
            if server.alias == "spotify":
                return {"tools": [_tool("search"), _tool("pause")]}
            return {"tools": [_tool("library_stats")]}

        with patch.object(mcp_service, "_rpc", side_effect=fake_rpc):
            status = mcp_service.server_status()

        by_name = {row["name"]: row for row in status}
        self.assertEqual(by_name["spotify"]["tools"], 2)
        self.assertEqual(by_name["respotit"]["tools"], 1)
        self.assertEqual(by_name["spotify"]["url"], "http://spotify.test/mcp")


if __name__ == "__main__":
    unittest.main()
