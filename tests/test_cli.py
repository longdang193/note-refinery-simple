from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from note_refinery_simple.cli import build_parser, load_dotenv


class CliParserTest(unittest.TestCase):
    def test_parser_uses_current_directory_as_default_output_root(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(["run", "--notes-dir", str(notes_dir)])

            self.assertEqual(args.notes_dir, notes_dir)
            self.assertEqual(args.output_root, Path.cwd())

    def test_parser_defaults_to_clean_teaching_mode(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(["run", "--notes-dir", str(notes_dir)])

            self.assertEqual(args.mode, "clean-teaching")

    def test_parser_accepts_conservative_mode(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(["patch", "--notes-dir", str(notes_dir), "--mode", "conservative"])

            self.assertEqual(args.mode, "conservative")

    def test_parser_accepts_cached_rerun_flags(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            cache_root = root / "cache"
            cache_root.mkdir()

            args = parser.parse_args(
                [
                    "run",
                    "--notes-dir",
                    str(notes_dir),
                    "--reuse-review-from",
                    str(cache_root),
                    "--reuse-image-context-from",
                    str(cache_root),
                ]
            )

            self.assertEqual(args.reuse_review_from, cache_root)
            self.assertEqual(args.reuse_image_context_from, cache_root)
    def test_parser_accepts_patch_concurrency(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(["run", "--notes-dir", str(notes_dir), "--patch-concurrency", "4"])

            self.assertEqual(args.patch_concurrency, 4)

    def test_parser_accepts_review_folder_concurrency(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(["run", "--notes-dir", str(notes_dir), "--review-folder-concurrency", "3"])

            self.assertEqual(args.review_folder_concurrency, 3)

    def test_parser_accepts_config_path(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            config_path = root / "note_refinery.yaml"

            args = parser.parse_args(["run", "--notes-dir", str(notes_dir), "--config", str(config_path)])

            self.assertEqual(args.config, config_path)

    def test_parser_accepts_synthesize_command_and_model_override(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(
                [
                    "synthesize",
                    "--notes-dir",
                    str(notes_dir),
                    "--synthesize-model",
                    "deepseek-v4-pro",
                ]
            )

            self.assertEqual(args.command, "synthesize")
            self.assertEqual(args.synthesize_model, "deepseek-v4-pro")

    def test_parser_accepts_prompt_profile_overrides(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            args = parser.parse_args(
                [
                    "run",
                    "--notes-dir",
                    str(notes_dir),
                    "--prompt-profile",
                    "strict",
                    "--prompt-root-dir",
                    "custom-prompts",
                ]
            )

            self.assertEqual(args.prompt_profile, "strict")
            self.assertEqual(args.prompt_root_dir, "custom-prompts")

    def test_load_dotenv_sets_missing_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "OPENAI_COMPATIBLE_API_KEY=test-key\nOPENAI_COMPATIBLE_BASE_URL=https://example.invalid/v1\n",
                encoding="utf-8",
            )

            env = {"OPENAI_COMPATIBLE_BASE_URL": "https://keep.invalid/v1"}

            load_dotenv(env_path, env)

            self.assertEqual(env["OPENAI_COMPATIBLE_API_KEY"], "test-key")
            self.assertEqual(env["OPENAI_COMPATIBLE_BASE_URL"], "https://keep.invalid/v1")


if __name__ == "__main__":
    unittest.main()

