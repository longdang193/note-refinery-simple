from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, cast

from note_refinery_simple.prompts import DEFAULT_PROMPT_PROFILE, DEFAULT_PROMPT_ROOT_DIR

PatchMode = Literal["clean-teaching", "conservative"]

DEFAULT_PROVIDER = "opencode"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_CONFIG_FILE_NAME = "note_refinery.yaml"
PROVIDER_BASE_URLS = {
    "opencode": "https://opencode.ai/zen/go/v1",
    "deepseek": "https://api.deepseek.com",
}


@dataclass(frozen=True)
class RuntimeSettings:
    provider: str
    base_url: str
    review_model: str | None
    patch_model: str | None
    verify_model: str | None
    synthesize_model: str | None
    image_model: str | None
    prompt_profile: str
    prompt_root_dir: Path
    patch_mode: PatchMode
    timeout_seconds: int
    config_path: Path | None


def load_runtime_settings(
    *,
    cwd: Path,
    env: Mapping[str, str],
    cli_overrides: Mapping[str, object],
) -> RuntimeSettings:
    config_path = resolve_config_path(cwd=cwd, cli_overrides=cli_overrides)
    file_config = load_project_config(config_path) if config_path is not None else {}

    provider = str(
        first_non_none(
            cli_overrides.get("provider"),
            file_config.get("provider"),
            env.get("OPENAI_COMPATIBLE_PROVIDER"),
            DEFAULT_PROVIDER,
        )
    )
    base_url = resolve_base_url(
        provider=provider,
        cli_base_url=as_optional_str(cli_overrides.get("base_url")),
        file_base_url=as_optional_str(file_config.get("base_url")),
        env_base_url=env.get("OPENAI_COMPATIBLE_BASE_URL") or env.get("OPENAI_BASE_URL") or env.get("DEEPSEEK_BASE_URL"),
    )
    model_config = file_config.get("models")
    if not isinstance(model_config, dict):
        model_config = {}
    prompt_config = file_config.get("prompts")
    if not isinstance(prompt_config, dict):
        prompt_config = {}

    patch_mode_value = first_non_none(
        cli_overrides.get("patch_mode"),
        cli_overrides.get("mode"),
        file_config.get("patch_mode"),
        "clean-teaching",
    )
    timeout_value = first_non_none(
        cli_overrides.get("timeout_seconds"),
        file_config.get("timeout_seconds"),
        env.get("OPENAI_COMPATIBLE_TIMEOUT_SECONDS"),
        DEFAULT_TIMEOUT_SECONDS,
    )

    return RuntimeSettings(
        provider=provider,
        base_url=base_url,
        review_model=pick_model(cli_overrides.get("review_model"), model_config.get("review"), env),
        patch_model=pick_model(cli_overrides.get("patch_model"), model_config.get("patch"), env),
        verify_model=pick_model(cli_overrides.get("verify_model"), model_config.get("verify"), env),
        synthesize_model=pick_model(
            cli_overrides.get("synthesize_model"),
            model_config.get("synthesize"),
            env,
            fallback_model=pick_model(cli_overrides.get("review_model"), model_config.get("review"), env),
        ),
        image_model=pick_model(cli_overrides.get("image_model"), model_config.get("image"), env, image=True),
        prompt_profile=str(first_non_none(cli_overrides.get("prompt_profile"), prompt_config.get("profile"), DEFAULT_PROMPT_PROFILE)),
        prompt_root_dir=resolve_prompt_root_dir(cli_overrides.get("prompt_root_dir"), prompt_config.get("root_dir")),
        patch_mode=normalize_patch_mode(str(patch_mode_value)),
        timeout_seconds=parse_timeout_seconds(timeout_value),
        config_path=config_path,
    )


def resolve_config_path(cwd: Path, cli_overrides: Mapping[str, object]) -> Path | None:
    override = cli_overrides.get("config_path") or cli_overrides.get("config")
    if isinstance(override, Path):
        return override
    if isinstance(override, str) and override.strip():
        return Path(override)
    default_path = cwd / DEFAULT_CONFIG_FILE_NAME
    if default_path.exists():
        return default_path
    return None


def load_project_config(config_path: Path) -> dict[str, object]:
    payload = parse_simple_yaml(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain a mapping: {config_path}")
    return payload


def parse_simple_yaml(content: str) -> dict[str, object]:
    root: dict[str, object] = {}
    current_section: dict[str, object] | None = None
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            key, raw_value = split_key_value(stripped)
            if raw_value == "":
                current_section = {}
                root[key] = current_section
                continue
            current_section = None
            root[key] = parse_scalar(raw_value)
            continue
        if indent == 2 and current_section is not None:
            key, raw_value = split_key_value(stripped)
            current_section[key] = parse_scalar(raw_value)
            continue
        raise ValueError("Unsupported YAML structure. Use top-level keys and one nested mapping level.")
    return root


def split_key_value(line: str) -> tuple[str, str]:
    key, separator, value = line.partition(":")
    if not separator:
        raise ValueError(f"Invalid config line: {line}")
    return key.strip(), value.strip()


def parse_scalar(value: str) -> object:
    if value in {"", "null", "Null", "NULL", "~"}:
        return None
    if value.isdigit():
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def resolve_base_url(
    *,
    provider: str,
    cli_base_url: str | None,
    file_base_url: str | None,
    env_base_url: str | None,
) -> str:
    override_base_url = first_non_none(cli_base_url, file_base_url, env_base_url)
    normalized_provider = provider.strip().lower()
    if override_base_url is not None:
        return str(override_base_url).rstrip("/")
    if normalized_provider == "custom":
        raise ValueError("provider 'custom' requires base_url")
    base_url = PROVIDER_BASE_URLS.get(normalized_provider)
    if base_url is None:
        raise ValueError(f"Unknown provider: {provider}")
    return base_url


def pick_model(
    cli_value: object,
    file_value: object,
    env: Mapping[str, str],
    *,
    fallback_model: str | None = None,
    image: bool = False,
) -> str | None:
    env_default = env.get("OPENAI_COMPATIBLE_IMAGE_MODEL") if image else env.get("OPENAI_COMPATIBLE_MODEL")
    value = first_non_none(cli_value, file_value, env_default, env.get("OPENAI_MODEL"), env.get("DEEPSEEK_MODEL"), fallback_model)
    return None if value is None else str(value)


def first_non_none(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_patch_mode(value: str) -> PatchMode:
    if value not in {"clean-teaching", "conservative"}:
        raise ValueError(f"Unsupported patch_mode: {value}")
    return cast(PatchMode, value)


def parse_timeout_seconds(value: object | None) -> int:
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, (int, str)):
        return int(value)
    raise ValueError(f"Unsupported timeout_seconds value: {value!r}")


def as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_prompt_root_dir(cli_value: object, file_value: object) -> Path:
    value = first_non_none(cli_value, file_value, DEFAULT_PROMPT_ROOT_DIR)
    if isinstance(value, Path):
        return value
    return Path(str(value))
