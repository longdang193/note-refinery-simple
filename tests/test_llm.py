from __future__ import annotations

import unittest

from note_refinery_simple.llm import (
    LLMConfig,
    build_chat_completions_url,
    build_headers,
    build_image_request_payload,
    build_request_payload,
    extract_json_object_text,
    parse_image_response_content,
)


class LLMConfigTest(unittest.TestCase):
    def test_from_env_uses_openai_compatible_variables(self) -> None:
        env = {
            "OPENAI_COMPATIBLE_API_KEY": "secret",
            "OPENAI_COMPATIBLE_BASE_URL": "https://opencode.ai/zen/go/v1/chat/completions",
            "OPENAI_COMPATIBLE_MODEL": "deepseek-v4-pro",
        }

        config = LLMConfig.from_mapping(env)

        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.base_url, "https://opencode.ai/zen/go/v1/chat/completions")
        self.assertEqual(config.review_model, "deepseek-v4-pro")

    def test_from_env_infers_opencode_base_url_from_provider_name(self) -> None:
        env = {
            "OPENAI_COMPATIBLE_API_KEY": "secret",
            "OPENAI_COMPATIBLE_PROVIDER": "opencode",
            "OPENAI_COMPATIBLE_MODEL": "deepseek-v4-pro",
        }

        config = LLMConfig.from_mapping(env)

        self.assertEqual(config.base_url, "https://opencode.ai/zen/go/v1")
        self.assertEqual(config.review_model, "deepseek-v4-pro")


class EndpointUrlTest(unittest.TestCase):
    def test_explicit_chat_completions_url_is_not_modified(self) -> None:
        url = build_chat_completions_url("https://opencode.ai/zen/go/v1/chat/completions")

        self.assertEqual(url, "https://opencode.ai/zen/go/v1/chat/completions")

    def test_base_v1_url_appends_chat_completions(self) -> None:
        url = build_chat_completions_url("https://api.deepseek.com")

        self.assertEqual(url, "https://api.deepseek.com/chat/completions")


class HeaderTest(unittest.TestCase):
    def test_headers_include_accept_and_user_agent(self) -> None:
        headers = build_headers("secret")

        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertIn("User-Agent", headers)


class PayloadTest(unittest.TestCase):
    def test_payload_disables_thinking(self) -> None:
        payload = build_request_payload(model="deepseek-v4-pro", prompt="Reply with OK", max_tokens=321)

        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 321)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["content"], "Reply with OK")

    def test_image_payload_contains_text_and_image_url_parts(self) -> None:
        payload = build_image_request_payload(
            model="minimax-m3",
            prompt="Describe chart",
            image_data_url="data:image/jpeg;base64,ZmFrZQ==",
            max_tokens=222,
        )

        self.assertEqual(payload["model"], "minimax-m3")
        self.assertEqual(payload["max_tokens"], 222)
        message_content = payload["messages"][1]["content"]
        self.assertEqual(message_content[0]["type"], "text")
        self.assertEqual(message_content[1]["type"], "image_url")
        self.assertEqual(message_content[1]["image_url"]["url"], "data:image/jpeg;base64,ZmFrZQ==")


class ResponseParsingTest(unittest.TestCase):
    def test_extract_json_object_text_handles_fenced_json(self) -> None:
        content = "```json\n{\n  \"summary\": \"ok\"\n}\n```"

        parsed = extract_json_object_text(content)

        self.assertEqual(parsed, '{\n  "summary": "ok"\n}')

    def test_parse_image_response_content_falls_back_for_invalid_json(self) -> None:
        content = "```json\n{\n  \"summary\": \"broken \"quote\" example\"\n}\n```"

        parsed = parse_image_response_content(content)

        self.assertEqual(parsed["detected_type"], "unknown")
        self.assertEqual(parsed["confidence"], "low")
        self.assertIn("best-effort", parsed["possible_risks"][0])


if __name__ == "__main__":
    unittest.main()
