from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from note_refinery_simple.config import load_runtime_settings
from note_refinery_simple.llm import LLMConfig, OpenAICompatibleClient
from note_refinery_simple.pipeline import PipelinePaths, ReviewPipeline
from note_refinery_simple.prompts import load_prompt_set


REPORTS_DIR_NAME = "reports"
REVIEW_FILE_NAME = "REVIEW.md"
IMAGE_CONTEXT_FILE_NAME = "image_context.json"


def print_progress(message: str) -> None:
    print(message, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review, patch, verify, and synthesize markdown class notes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("run", "review", "patch", "verify", "synthesize"):
        subparser = subparsers.add_parser(command_name)
        subparser.add_argument("--notes-dir", type=Path, required=True)
        subparser.add_argument("--output-root", type=Path, default=Path.cwd())
        subparser.add_argument("--config", type=Path)
        subparser.add_argument("--provider")
        subparser.add_argument("--base-url")
        subparser.add_argument("--mode", choices=("clean-teaching", "conservative"), default="clean-teaching")
        subparser.add_argument("--patch-concurrency", type=int)
        subparser.add_argument("--reuse-review-from", type=Path)
        subparser.add_argument("--reuse-image-context-from", type=Path)
        subparser.add_argument("--review-model")
        subparser.add_argument("--patch-model")
        subparser.add_argument("--verify-model")
        subparser.add_argument("--synthesize-model")
        subparser.add_argument("--image-model")
        subparser.add_argument("--prompt-profile")
        subparser.add_argument("--prompt-root-dir")
        subparser.add_argument("--timeout-seconds", type=int, default=180)

    return parser


def load_dotenv(dotenv_path: Path, env: dict[str, str] | os._Environ[str]) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env.setdefault(key.strip(), value.strip())


def load_cached_review_markdown(output_root: Path | None) -> str | None:
    if output_root is None:
        return None
    review_path = output_root / REPORTS_DIR_NAME / REVIEW_FILE_NAME
    if not review_path.exists():
        raise FileNotFoundError(f"Cached review not found: {review_path}")
    return review_path.read_text(encoding="utf-8")


def load_cached_image_contexts(output_root: Path | None) -> list[dict[str, object]] | None:
    if output_root is None:
        return None
    image_context_path = output_root / REPORTS_DIR_NAME / IMAGE_CONTEXT_FILE_NAME
    if not image_context_path.exists():
        raise FileNotFoundError(f"Cached image context not found: {image_context_path}")
    payload = json.loads(image_context_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Cached image context must be a list: {image_context_path}")
    return [item for item in payload if isinstance(item, dict)]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", os.environ)
    runtime_settings = load_runtime_settings(
        cwd=Path.cwd(),
        env=os.environ,
        cli_overrides={
            "config_path": args.config,
            "provider": args.provider,
            "base_url": args.base_url,
            "mode": args.mode,
            "patch_concurrency": args.patch_concurrency,
            "review_model": args.review_model,
            "patch_model": args.patch_model,
            "verify_model": args.verify_model,
            "synthesize_model": args.synthesize_model,
            "image_model": args.image_model,
            "prompt_profile": args.prompt_profile,
            "prompt_root_dir": args.prompt_root_dir,
            "timeout_seconds": args.timeout_seconds,
        },
    )
    config = LLMConfig.from_env(
        base_url=runtime_settings.base_url,
        review_model=runtime_settings.review_model,
        patch_model=runtime_settings.patch_model,
        verify_model=runtime_settings.verify_model,
        synthesize_model=runtime_settings.synthesize_model,
        image_model=runtime_settings.image_model,
        timeout_seconds=runtime_settings.timeout_seconds,
    )
    prompt_set = load_prompt_set(
        project_root=Path.cwd(),
        prompt_root_dir=runtime_settings.prompt_root_dir,
        prompt_profile=runtime_settings.prompt_profile,
    )
    client = OpenAICompatibleClient(config, prompt_set=prompt_set)
    pipeline = ReviewPipeline(
        client,
        image_enricher=client,
        patch_mode=runtime_settings.patch_mode,
        patch_concurrency=runtime_settings.patch_concurrency,
        progress_callback=print_progress,
        prompt_set=prompt_set,
    )
    paths = PipelinePaths.for_root(args.output_root)
    reuse_review_markdown = load_cached_review_markdown(args.reuse_review_from)
    cached_image_contexts = load_cached_image_contexts(args.reuse_image_context_from)

    if args.command == "run":
        pipeline.run(
            notes_dir=args.notes_dir,
            paths=paths,
            reuse_review_markdown=reuse_review_markdown,
            cached_image_contexts=cached_image_contexts,
        )
    elif args.command == "review":
        pipeline.write_review(
            notes_dir=args.notes_dir,
            paths=paths,
            cached_image_contexts=cached_image_contexts,
        )
    elif args.command == "patch":
        if reuse_review_markdown is not None:
            paths.ensure()
            (paths.reports_dir / REVIEW_FILE_NAME).write_text(reuse_review_markdown, encoding="utf-8")
        if cached_image_contexts is not None:
            paths.ensure()
            (paths.reports_dir / IMAGE_CONTEXT_FILE_NAME).write_text(json.dumps(cached_image_contexts, indent=2) + "\n", encoding="utf-8")
        pipeline.write_patched_notes(notes_dir=args.notes_dir, paths=paths)
    elif args.command == "verify":
        pipeline.write_verify(notes_dir=args.notes_dir, paths=paths)
    elif args.command == "synthesize":
        pipeline.write_synthesis(notes_dir=args.notes_dir, paths=paths)
    else:
        parser.error(f"Unknown command: {args.command}")
    return 0
