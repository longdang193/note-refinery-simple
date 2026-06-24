from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_PROMPT_PROFILE = "default"
DEFAULT_PROMPT_ROOT_DIR = Path("prompts")
PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z_]+)\}\}")

REQUIRED_PLACEHOLDERS = {
    "review.md": {"notes_block", "image_context_block"},
    "patch.md": {"review_markdown", "notes_block", "patch_mode_instructions", "image_context_block"},
    "verify.md": {"review_markdown", "original_notes_block", "patched_notes_block", "image_context_block"},
    "synthesize.md": {"review_markdown", "verify_markdown", "patched_notes_block"},
    "image_user.md": {"markdown_file", "nearby_heading"},
}


@dataclass(frozen=True)
class PromptSet:
    system_prompt: str
    image_system_prompt: str
    review_prompt: str
    patch_prompt: str
    verify_prompt: str
    synthesize_prompt: str
    image_user_prompt: str


def load_prompt_set(project_root: Path, prompt_root_dir: Path, prompt_profile: str) -> PromptSet:
    prompt_root = (project_root / prompt_root_dir).resolve()
    base_dir = prompt_root / "base"
    profile_dir = prompt_root / "profiles" / prompt_profile

    system_prompt = read_prompt_file(base_dir / "system.md", prompt_root)
    image_system_prompt = read_prompt_file(base_dir / "image_system.md", prompt_root)
    review_prompt = read_and_validate_prompt_file(profile_dir / "review.md", prompt_root)
    patch_prompt = read_and_validate_prompt_file(profile_dir / "patch.md", prompt_root)
    verify_prompt = read_and_validate_prompt_file(profile_dir / "verify.md", prompt_root)
    synthesize_prompt = read_and_validate_prompt_file(profile_dir / "synthesize.md", prompt_root)
    image_user_prompt = read_and_validate_prompt_file(profile_dir / "image_user.md", prompt_root)

    return PromptSet(
        system_prompt=system_prompt,
        image_system_prompt=image_system_prompt,
        review_prompt=review_prompt,
        patch_prompt=patch_prompt,
        verify_prompt=verify_prompt,
        synthesize_prompt=synthesize_prompt,
        image_user_prompt=image_user_prompt,
    )


def read_and_validate_prompt_file(prompt_path: Path, prompt_root: Path) -> str:
    content = read_prompt_file(prompt_path, prompt_root)
    validate_prompt_placeholders(prompt_path.name, content)
    return content


def read_prompt_file(prompt_path: Path, prompt_root: Path) -> str:
    if prompt_path.suffix.lower() != ".md":
        raise ValueError(f"Prompt file must use .md extension: {prompt_path}")
    resolved_path = prompt_path.resolve()
    try:
        resolved_path.relative_to(prompt_root)
    except ValueError as error:
        raise ValueError(f"Prompt path must stay under prompt root: {prompt_path}") from error
    if not resolved_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return resolved_path.read_text(encoding="utf-8")


def validate_prompt_placeholders(file_name: str, content: str) -> None:
    required_placeholders = REQUIRED_PLACEHOLDERS[file_name]
    present_placeholders = set(PLACEHOLDER_PATTERN.findall(content))
    missing_placeholders = sorted(required_placeholders - present_placeholders)
    if missing_placeholders:
        raise ValueError(f"Prompt file {file_name} is missing placeholders: {', '.join(missing_placeholders)}")


def render_prompt_template(template: str, replacements: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in replacements:
            raise ValueError(f"Unknown prompt placeholder: {key}")
        return replacements[key]

    return PLACEHOLDER_PATTERN.sub(replace, template)
