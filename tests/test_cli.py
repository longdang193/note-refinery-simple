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

    def test_parser_accepts_config_path(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            config_path = root / "note_refinery.yaml"

            args = parser.parse_args(["run", "--notes-dir", str(notes_dir), "--config", str(config_path)])

            self.assertEqual(args.config, config_path)

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
