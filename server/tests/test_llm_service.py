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


class ExtractConcertsTests(unittest.TestCase):
    """Lineup splitting: one row per performer, never a wrong split."""

    def test_lineup_with_plus_becomes_two_rows(self):
        self.assertEqual(
            llm_service._split_lineup("The Gangtet + Vivid Arc"),
            ["The Gangtet", "Vivid Arc"],
        )

    def test_lineup_with_dashes_becomes_separate_performers(self):
        self.assertEqual(
            llm_service._split_lineup("Toni Sfinos - Antonella - The Playmates"),
            ["Toni Sfinos", "Antonella", "The Playmates"],
        )

    def test_ampersand_names_are_left_alone(self):
        # Splitting these would resolve "Simon" and "Garfunkel" separately.
        self.assertEqual(
            llm_service._split_lineup("Simon & Garfunkel"), ["Simon & Garfunkel"]
        )
        self.assertEqual(
            llm_service._split_lineup("Earth, Wind & Fire"), ["Earth, Wind & Fire"]
        )

    def test_single_artist_is_unchanged(self):
        self.assertEqual(llm_service._split_lineup("Napalm Death"), ["Napalm Death"])
        self.assertEqual(llm_service._split_lineup("Jay-Z"), ["Jay-Z"])

    def test_comma_list_becomes_one_row_per_artist(self):
        # The model returns the whole bill in one field.
        self.assertEqual(
            llm_service._split_lineup("Bloc Party, Interpol, and Heartworms"),
            ["Bloc Party", "Interpol", "Heartworms"],
        )
        self.assertEqual(
            llm_service._split_lineup("Yazmin Lacey, Jembaa Groove, SML, and Amy Gadiaga"),
            ["Yazmin Lacey", "Jembaa Groove", "SML", "Amy Gadiaga"],
        )

    def test_and_lineup_becomes_two_rows(self):
        self.assertEqual(
            llm_service._split_lineup("Lynnic and Its Arius"),
            ["Lynnic", "Its Arius"],
        )
        self.assertEqual(
            llm_service._split_lineup("Antonella and The Playmates"),
            ["Antonella", "The Playmates"],
        )
        self.assertEqual(
            llm_service._split_lineup("Mantra Machine and Cervus (NL)"),
            ["Mantra Machine", "Cervus (NL)"],
        )

    def test_names_that_look_like_a_list_are_left_alone(self):
        # A wrong split would resolve half a name on its own.
        self.assertEqual(
            llm_service._split_lineup("Tyler, The Creator"), ["Tyler, The Creator"]
        )
        self.assertEqual(
            llm_service._split_lineup("Florence and the Machine"), ["Florence and the Machine"]
        )

    def test_venue_glued_to_the_artist_is_dropped(self):
        self.assertEqual(
            llm_service._strip_venue_suffix("Kiya Tabassian Westerkerk", "Westerkerk"),
            "Kiya Tabassian",
        )
        self.assertEqual(
            llm_service._strip_venue_suffix("Maxwell Owin", "Bimhuis"), "Maxwell Owin"
        )

    @patch("api.services.llm_service.extract_structured")
    def test_extract_concerts_splits_a_lineup_row(self, structured):
        structured.return_value = {
            "concerts": [["The Gangtet + Vivid Arc", "2026-11-20", "Polychoros Soul skg"]]
        }

        out = llm_service.extract_concerts("page text")

        self.assertEqual([c["artist"] for c in out["concerts"]],
                         ["The Gangtet", "Vivid Arc"])
        self.assertTrue(all(c["date"] == "2026-11-20" for c in out["concerts"]))
        self.assertTrue(all(c["venue"] == "Polychoros Soul skg" for c in out["concerts"]))

    @patch("api.services.llm_service.extract_structured")
    def test_extract_concerts_splits_a_comma_bill(self, structured):
        structured.return_value = {
            "concerts": [["Bloc Party, Interpol, and Heartworms", "2026-11-17", "AFAS Live"]]
        }

        out = llm_service.extract_concerts("page text")

        self.assertEqual([c["artist"] for c in out["concerts"]],
                         ["Bloc Party", "Interpol", "Heartworms"])
        self.assertTrue(all(c["venue"] == "AFAS Live" for c in out["concerts"]))

    @patch("api.services.llm_service.extract_structured")
    def test_extract_concerts_drops_a_venue_glued_to_the_artist(self, structured):
        structured.return_value = {
            "concerts": [["Kiya Tabassian Westerkerk", "2026-11-23", "Westerkerk"]]
        }

        out = llm_service.extract_concerts("page text")

        self.assertEqual([c["artist"] for c in out["concerts"]], ["Kiya Tabassian"])


class ExtractAlbumsTests(unittest.TestCase):
    """Album extraction must survive a long WebView snapshot."""

    def test_split_for_extraction_overlaps_and_covers(self):
        text = "x" * 100
        chunks = llm_service._split_for_extraction(text, 40, 10)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 40 for c in chunks))
        self.assertEqual(chunks[0][-10:], chunks[1][:10])
        # The final window ends at the end of the source: nothing is dropped.
        self.assertEqual(chunks[-1], text[60:])

    def test_split_for_extraction_short_is_single(self):
        self.assertEqual(llm_service._split_for_extraction("short", 40, 10), ["short"])
        self.assertEqual(llm_service._split_for_extraction("", 40, 10), [])

    @patch("api.services.llm_service.extract_structured")
    def test_long_text_is_extracted_in_chunks_and_deduped(self, structured):
        # Two windows, each repeating one album because of the overlap.
        structured.side_effect = [
            {"albums": [{"artist": "Portishead", "album": "Dummy"}]},
            {"albums": [
                {"artist": "portishead", "album": "dummy"},
                {"artist": "Massive Attack", "album": "Mezzanine"},
            ]},
        ]
        text = "a" * (llm_service.ALBUM_CHUNK_CHARS + 500)

        out = llm_service.extract_albums(text)

        self.assertEqual(len(structured.call_args_list), 2)
        self.assertEqual(
            out["albums"],
            [
                {"artist": "Portishead", "album": "Dummy"},
                {"artist": "Massive Attack", "album": "Mezzanine"},
            ],
        )

    @patch("api.services.llm_service.extract_structured")
    def test_short_text_is_one_call(self, structured):
        structured.return_value = {"albums": [{"artist": "A", "album": "B"}]}

        out = llm_service.extract_albums("short page")

        self.assertEqual(len(structured.call_args_list), 1)
        self.assertEqual(structured.call_args.args[1], "short page")
        self.assertEqual(out["albums"], [{"artist": "A", "album": "B"}])

    @patch("api.services.llm_service.extract_structured")
    def test_failed_chunk_is_skipped_but_kept_others(self, structured):
        structured.side_effect = [
            llm_service.LLMTimeout("slow"),
            {"albums": [{"artist": "A", "album": "B"}]},
        ]
        text = "a" * (llm_service.ALBUM_CHUNK_CHARS + 500)

        out = llm_service.extract_albums(text)

        self.assertEqual(out["albums"], [{"artist": "A", "album": "B"}])

    @patch("api.services.llm_service.extract_structured")
    def test_single_chunk_failure_raises(self, structured):
        structured.side_effect = llm_service.LLMTimeout("slow")

        with self.assertRaises(llm_service.LLMTimeout):
            llm_service.extract_albums("short page")


if __name__ == "__main__":
    unittest.main()
