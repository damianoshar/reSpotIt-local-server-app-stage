"""Tests for the Open WebUI LLM proxy.

Mocked only: these tests never touch Open WebUI, llama-server or the network.

Run from the server directory:

    python -m pytest tests/test_llm_service.py -q
"""
import os
import unittest
from unittest.mock import Mock, patch

import requests

from api.services import llm_service


def _response(status: int = 200, payload=None, text: str = "") -> Mock:
    resp = Mock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = text
    return resp


class LLMServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "OPENWEBUI_URL": "http://webui.test",
                "OPENWEBUI_API_KEY": "sk-test",
            },
        )
        self.env.start()
        os.environ.pop("OPENWEBUI_MODEL", None)

    def tearDown(self):
        self.env.stop()

    def test_status_without_key_reports_disabled(self):
        with patch.dict(os.environ, {"OPENWEBUI_API_KEY": ""}):
            result = llm_service.status()

        self.assertFalse(result["configured"])
        self.assertFalse(result["available"])
        self.assertIn("OPENWEBUI_API_KEY", result["error"])

    @patch("api.services.llm_service.requests.request")
    def test_list_models_parses_and_trims(self, request):
        request.return_value = _response(
            payload={
                "data": [
                    {"id": "model-a", "name": "Model A", "owned_by": "llamacpp"},
                    {"id": "model-b"},
                    {"name": "no-id"},
                ]
            }
        )

        models = llm_service.list_models()

        self.assertEqual(
            models,
            [
                {"id": "model-a", "name": "Model A", "owned_by": "llamacpp"},
                {"id": "model-b", "name": "model-b", "owned_by": ""},
            ],
        )
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1], "http://webui.test/api/models")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")

    @patch("api.services.llm_service.requests.request")
    def test_chat_resolves_first_model_and_normalizes(self, request):
        request.side_effect = [
            _response(payload={"data": [{"id": "model-a", "name": "Model A"}]}),
            _response(
                payload={
                    "model": "model-a",
                    "choices": [
                        {
                            "message": {
                                "content": "hello",
                                "reasoning_content": "thinking",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 7},
                }
            ),
        ]

        result = llm_service.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["reasoning_content"], "thinking")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["model"], "model-a")
        self.assertEqual(result["usage"], {"total_tokens": 7})

        body = request.call_args_list[1].kwargs["json"]
        self.assertEqual(body["model"], "model-a")
        self.assertFalse(body["stream"])
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])

    @patch("api.services.llm_service.requests.request")
    def test_chat_honours_model_override_without_listing(self, request):
        request.return_value = _response(
            payload={"choices": [{"message": {"content": "ok"}}]}
        )
        with patch.dict(os.environ, {"OPENWEBUI_MODEL": "chosen-model"}):
            llm_service.chat([{"role": "user", "content": "hi"}])

        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["json"]["model"], "chosen-model")

    @patch("api.services.llm_service.requests.request")
    def test_upstream_error_becomes_llm_upstream_error(self, request):
        request.return_value = _response(status=500, payload={"detail": "boom"})

        with self.assertRaises(llm_service.LLMUpstreamError) as ctx:
            llm_service.list_models()

        self.assertIn("500", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    @patch("api.services.llm_service.requests.request")
    def test_timeout_becomes_llm_timeout(self, request):
        request.side_effect = requests.Timeout("slow")

        with self.assertRaises(llm_service.LLMTimeout):
            llm_service.chat(
                [{"role": "user", "content": "hi"}], model="model-a"
            )

    @patch("api.services.llm_service.requests.request")
    def test_connection_error_becomes_llm_unavailable(self, request):
        request.side_effect = requests.ConnectionError("down")

        with self.assertRaises(llm_service.LLMUnavailable):
            llm_service.list_models()

    @patch("api.services.llm_service.requests.request")
    def test_no_connected_model_is_unavailable(self, request):
        request.return_value = _response(payload={"data": []})

        with self.assertRaises(llm_service.LLMUnavailable):
            llm_service.resolve_model()

    @patch("api.services.llm_service.requests.request")
    def test_trace_logs_prompt_and_response_when_enabled(self, request):
        request.return_value = _response(
            payload={"choices": [{"message": {"content": "hi"}}]}
        )

        with patch.dict(os.environ, {"LLM_TRACE": "1"}):
            with self.assertLogs("llm", level="INFO") as logs:
                llm_service.chat(
                    [{"role": "user", "content": "secret-prompt"}], model="m"
                )

        output = "\n".join(logs.output)
        self.assertIn("LLM TRACE -> POST /api/chat/completions", output)
        self.assertIn("secret-prompt", output)
        self.assertIn("LLM TRACE <- 200 /api/chat/completions", output)

    @patch("api.services.llm_service.requests.request")
    def test_trace_is_silent_when_disabled(self, request):
        request.return_value = _response(payload={"data": [{"id": "m"}]})

        with patch.dict(os.environ, {"LLM_TRACE": ""}):
            with self.assertNoLogs("llm", level="INFO"):
                llm_service.list_models()


if __name__ == "__main__":
    unittest.main()
