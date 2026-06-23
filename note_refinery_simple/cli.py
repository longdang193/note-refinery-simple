from __future__ import annotations

import argparse
import os
from pathlib import Path

from note_refinery_simple.config import load_runtime_settings
from note_refinery_simple.llm import LLMConfig, OpenAICompatibleClient
from note_refinery_simple.pipeline import PipelinePaths, ReviewPipeline


def print_progress(message: str) -> None:
    print(message, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review, patch, and verify markdown class notes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("run", "review", "patch", "verify"):
        subparser = subparsers.add_parser(command_name)
        subparser.add_argument("--notes-dir", type=Path, required=True)
        subparser.add_argument("--output-root", type=Path, default=Path.cwd())
        subparser.add_argument("--config", type=Path)
        subparser.add_argument("--provider")
        subparser.add_argument("--base-url")
        subparser.add_argument("--mode", choices=("clean-teaching", "conservative"), default="clean-teaching")
        subparser.add_argument("--review-model")
        subparser.add_argument("--patch-model")
        subparser.add_argument("--verify-model")
        subparser.add_argument("--image-model")
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
            "review_model": args.review_model,
            "patch_model": args.patch_model,
            "verify_model": args.verify_model,
            "image_model": args.image_model,
            "timeout_seconds": args.timeout_seconds,
        },
    )
    config = LLMConfig.from_env(
        base_url=runtime_settings.base_url,
        review_model=runtime_settings.review_model,
        patch_model=runtime_settings.patch_model,
        verify_model=runtime_settings.verify_model,
        image_model=runtime_settings.image_model,
        timeout_seconds=runtime_settings.timeout_seconds,
    )
    client = OpenAICompatibleClient(config)
    pipeline = ReviewPipeline(
        client,
        image_enricher=client,
        patch_mode=runtime_settings.patch_mode,
        progress_callback=print_progress,
    )
    paths = PipelinePaths.for_root(args.output_root)

    if args.command == "run":
        pipeline.run(notes_dir=args.notes_dir, paths=paths)
    elif args.command == "review":
        pipeline.write_review(notes_dir=args.notes_dir, paths=paths)
    elif args.command == "patch":
        pipeline.write_patched_notes(notes_dir=args.notes_dir, paths=paths)
    elif args.command == "verify":
        pipeline.write_verify(notes_dir=args.notes_dir, paths=paths)
    else:
        parser.error(f"Unknown command: {args.command}")
    return 0
