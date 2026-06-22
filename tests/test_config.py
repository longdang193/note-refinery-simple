from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from note_refinery_simple.config import load_runtime_settings


class RuntimeConfigTest(unittest.TestCase):
    def test_load_runtime_settings_uses_project_config_as_ssot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "note_refinery.yaml").write_text(
                "provider: opencode\n"
                "models:\n"
                "  review: deepseek-v4-pro\n"
                "  patch: deepseek-v4-pro\n"
                "  verify: deepseek-v4-pro\n"
                "  image: minimax-m3\n"
                "patch_mode: clean-teaching\n"
                "timeout_seconds: 300\n",
                encoding="utf-8",
            )

            settings = load_runtime_settings(cwd=root, env={"OPENAI_COMPATIBLE_API_KEY": "secret"}, cli_overrides={})

            self.assertEqual(settings.provider, "opencode")
            self.assertEqual(settings.base_url, "https://opencode.ai/zen/go/v1")
            self.assertEqual(settings.review_model, "deepseek-v4-pro")
            self.assertEqual(settings.image_model, "minimax-m3")
            self.assertEqual(settings.patch_mode, "clean-teaching")
            self.assertEqual(settings.timeout_seconds, 300)

    def test_cli_overrides_take_precedence_over_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "note_refinery.yaml").write_text(
                "provider: opencode\n"
                "models:\n"
                "  patch: deepseek-v4-pro\n",
                encoding="utf-8",
            )

            settings = load_runtime_settings(
                cwd=root,
                env={"OPENAI_COMPATIBLE_API_KEY": "secret"},
                cli_overrides={"patch_model": "deepseek-chat", "patch_mode": "conservative"},
            )

            self.assertEqual(settings.patch_model, "deepseek-chat")
            self.assertEqual(settings.patch_mode, "conservative")

    def test_custom_provider_requires_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "note_refinery.yaml").write_text(
                "provider: custom\n"
                "models:\n"
                "  review: deepseek-v4-pro\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "base_url"):
                load_runtime_settings(cwd=root, env={"OPENAI_COMPATIBLE_API_KEY": "secret"}, cli_overrides={})

    def test_explicit_config_path_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "my-run.yaml"
            config_path.write_text(
                "provider: custom\n"
                "base_url: https://example.invalid/v1\n"
                "models:\n"
                "  review: deepseek-v4-pro\n"
                "  patch: deepseek-v4-pro\n"
                "  verify: deepseek-v4-pro\n"
                "  image: minimax-m3\n",
                encoding="utf-8",
            )

            settings = load_runtime_settings(
                cwd=root,
                env={"OPENAI_COMPATIBLE_API_KEY": "secret"},
                cli_overrides={"config_path": config_path},
            )

            self.assertEqual(settings.provider, "custom")
            self.assertEqual(settings.base_url, "https://example.invalid/v1")


if __name__ == "__main__":
    unittest.main()
