from __future__ import annotations

import json
import os
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib import request

from note_refinery_simple.config import PROVIDER_BASE_URLS

DEFAULT_BASE_URL = PROVIDER_BASE_URLS["deepseek"]
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_REVIEW_MAX_TOKENS = 2000
DEFAULT_PATCH_MAX_TOKENS = 12000
DEFAULT_VERIFY_MAX_TOKENS = 2000
DEFAULT_IMAGE_MAX_TOKENS = 800
SYSTEM_PROMPT = (
    "You are careful and concise. Follow requested output format exactly. "
    "Do not wrap JSON in markdown fences unless asked."
)
IMAGE_SYSTEM_PROMPT = (
    "You describe charts, diagrams, and drawings extracted from lecture notes. "
    "Prefer visible facts. If something is unclear, say so. Return JSON only."
)


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    review_model: str = DEFAULT_MODEL
    patch_model: str = DEFAULT_MODEL
    verify_model: str = DEFAULT_MODEL
    image_model: str = DEFAULT_MODEL
    timeout_seconds: int = 180

    @classmethod
    def from_env(
        cls,
        base_url: str | None = None,
        review_model: str | None = None,
        patch_model: str | None = None,
        verify_model: str | None = None,
        image_model: str | None = None,
        timeout_seconds: int = 180,
    ) -> "LLMConfig":
        return cls.from_mapping(
            os.environ,
            base_url=base_url,
            review_model=review_model,
            patch_model=patch_model,
            verify_model=verify_model,
            image_model=image_model,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_mapping(
        cls,
        env: Mapping[str, str],
        base_url: str | None = None,
        review_model: str | None = None,
        patch_model: str | None = None,
        verify_model: str | None = None,
        image_model: str | None = None,
        timeout_seconds: int = 180,
    ) -> "LLMConfig":
        api_key = (
            env.get("OPENAI_API_KEY")
            or env.get("DEEPSEEK_API_KEY")
            or env.get("OPENAI_COMPATIBLE_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "Set OPENAI_API_KEY, DEEPSEEK_API_KEY, or OPENAI_COMPATIBLE_API_KEY before running this tool"
            )
        resolved_base_url = (
            base_url
            or env.get("OPENAI_BASE_URL")
            or env.get("DEEPSEEK_BASE_URL")
            or env.get("OPENAI_COMPATIBLE_BASE_URL")
            or provider_base_url(env.get("OPENAI_COMPATIBLE_PROVIDER"))
            or DEFAULT_BASE_URL
        )
        default_model = (
            env.get("OPENAI_MODEL")
            or env.get("DEEPSEEK_MODEL")
            or env.get("OPENAI_COMPATIBLE_MODEL")
            or DEFAULT_MODEL
        )
        return cls(
            api_key=api_key,
            base_url=resolved_base_url.rstrip("/"),
            review_model=review_model or default_model,
            patch_model=patch_model or default_model,
            verify_model=verify_model or default_model,
            image_model=image_model or env.get("OPENAI_COMPATIBLE_IMAGE_MODEL") or default_model,
            timeout_seconds=timeout_seconds,
        )


def provider_base_url(provider_name: str | None) -> str | None:
    if provider_name is None:
        return None
    return PROVIDER_BASE_URLS.get(provider_name.strip().lower())


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def run_agent(self, agent_name: str, prompt: str) -> str:
        model = self._model_for(agent_name)
        body = json.dumps(
            build_request_payload(
                model=model,
                prompt=prompt,
                max_tokens=self._max_tokens_for(agent_name),
            )
        ).encode("utf-8")
        req = request.Request(
            url=build_chat_completions_url(self._config.base_url),
            data=body,
            headers=build_headers(self._config.api_key),
            method="POST",
        )
        with request.urlopen(req, timeout=self._config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"])

    def describe_image(self, *, image_path: Path, markdown_file: str, nearby_heading: str | None) -> dict[str, object]:
        prompt = build_image_prompt(markdown_file=markdown_file, nearby_heading=nearby_heading)
        body = json.dumps(
            build_image_request_payload(
                model=self._config.image_model,
                prompt=prompt,
                image_data_url=build_image_data_url(image_path),
                max_tokens=DEFAULT_IMAGE_MAX_TOKENS,
            )
        ).encode("utf-8")
        req = request.Request(
            url=build_chat_completions_url(self._config.base_url),
            data=body,
            headers=build_headers(self._config.api_key),
            method="POST",
        )
        with request.urlopen(req, timeout=self._config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = str(payload["choices"][0]["message"].get("content", "{}"))
        return parse_image_response_content(content)

    def _model_for(self, agent_name: str) -> str:
        if agent_name == "reviewer":
            return self._config.review_model
        if agent_name == "patcher":
            return self._config.patch_model
        if agent_name == "verifier":
            return self._config.verify_model
        raise ValueError(f"Unknown agent name: {agent_name}")

    def _max_tokens_for(self, agent_name: str) -> int:
        if agent_name == "reviewer":
            return DEFAULT_REVIEW_MAX_TOKENS
        if agent_name == "patcher":
            return DEFAULT_PATCH_MAX_TOKENS
        if agent_name == "verifier":
            return DEFAULT_VERIFY_MAX_TOKENS
        raise ValueError(f"Unknown agent name: {agent_name}")


def build_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "note-refinery-simple/0.1 (+python urllib)",
    }


def build_request_payload(model: str, prompt: str, max_tokens: int) -> dict[str, object]:
    return {
        "model": model,
        "thinking": {"type": "disabled"},
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }


def build_image_request_payload(
    model: str,
    prompt: str,
    image_data_url: str,
    max_tokens: int,
) -> dict[str, object]:
    return {
        "model": model,
        "thinking": {"type": "disabled"},
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": IMAGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
    }


def build_image_prompt(markdown_file: str, nearby_heading: str | None) -> str:
    heading_text = nearby_heading or "none"
    return (
        f"Describe image from markdown lecture notes. Markdown file: {markdown_file}. Nearby heading: {heading_text}.\n"
        "Return JSON only with keys: detected_type, summary, visible_text, chart_structure, possible_risks, confidence.\n"
        "Use short lists. If text is unreadable, say so in possible_risks."
    )


def build_image_data_url(image_path: Path) -> str:
    mime_type = guess_mime_type(image_path)
    encoded = b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def guess_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def extract_json_object_text(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def parse_image_response_content(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(extract_json_object_text(content))
    except json.JSONDecodeError:
        return {
            "detected_type": "unknown",
            "summary": content.strip(),
            "visible_text": [],
            "chart_structure": {},
            "possible_risks": [
                "Image model returned malformed JSON; summary kept as best-effort raw output."
            ],
            "confidence": "low",
        }
    if not isinstance(parsed, dict):
        raise ValueError("Image enricher must return a JSON object")
    return parsed
