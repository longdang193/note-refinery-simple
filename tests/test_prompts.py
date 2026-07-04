from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from note_refinery_simple.prompts import load_prompt_set, render_prompt_template


class PromptLoadingTest(unittest.TestCase):
    def test_loaded_prompt_profiles_describe_lecture_source_files(self) -> None:
        for profile in ("default", "strict"):
            prompt_set = load_prompt_set(
                project_root=Path(r"C:\Users\HOANG PHI LONG DANG\repos\note-refinery-simple"),
                prompt_root_dir=Path("prompts"),
                prompt_profile=profile,
            )

            self.assertIn("lecture source files", prompt_set.review_prompt)
            self.assertIn("lecture source files", prompt_set.patch_prompt)
            self.assertIn("lecture source files", prompt_set.verify_prompt)
            self.assertIn("lecture source", prompt_set.synthesize_prompt)

    def test_load_prompt_set_reads_markdown_prompt_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_root = root / "prompts"
            (prompt_root / "base").mkdir(parents=True)
            (prompt_root / "profiles" / "strict").mkdir(parents=True)

            (prompt_root / "base" / "system.md").write_text("# System\n\nBase system prompt.", encoding="utf-8")
            (prompt_root / "base" / "image_system.md").write_text("# Image System\n\nImage system prompt.", encoding="utf-8")
            (prompt_root / "profiles" / "strict" / "review.md").write_text("# Review\n\n{{notes_block}}\n\n{{image_context_block}}", encoding="utf-8")
            (prompt_root / "profiles" / "strict" / "patch.md").write_text("# Patch\n\n{{review_markdown}}\n\n{{notes_block}}\n\n{{patch_mode_instructions}}\n\n{{image_context_block}}", encoding="utf-8")
            (prompt_root / "profiles" / "strict" / "verify.md").write_text("# Verify\n\n{{review_markdown}}\n\n{{original_notes_block}}\n\n{{patched_notes_block}}\n\n{{image_context_block}}", encoding="utf-8")
            (prompt_root / "profiles" / "strict" / "synthesize.md").write_text("# Synthesize\n\n{{review_markdown}}\n\n{{verify_markdown}}\n\n{{patched_notes_block}}", encoding="utf-8")
            (prompt_root / "profiles" / "strict" / "image_user.md").write_text("# Image User\n\n{{markdown_file}}\n\n{{nearby_heading}}", encoding="utf-8")

            prompt_set = load_prompt_set(project_root=root, prompt_root_dir=Path("prompts"), prompt_profile="strict")

            self.assertIn("Base system prompt.", prompt_set.system_prompt)
            self.assertIn("{{notes_block}}", prompt_set.review_prompt)
            self.assertIn("{{markdown_file}}", prompt_set.image_user_prompt)

    def test_default_profile_prompts_require_latex_math(self) -> None:
        prompt_set = load_prompt_set(
            project_root=Path(r"C:\Users\HOANG PHI LONG DANG\repos\note-refinery-simple"),
            prompt_root_dir=Path("prompts"),
            prompt_profile="default",
        )

        self.assertIn("LaTeX", prompt_set.patch_prompt)
        self.assertIn("LaTeX", prompt_set.synthesize_prompt)
    def test_render_prompt_template_replaces_required_placeholders(self) -> None:
        rendered = render_prompt_template(
            "# Review\n\n{{notes_block}}\n\n{{image_context_block}}",
            {
                "notes_block": "<<<FILE:a.md>>>\nBody\n<<<END FILE>>>",
                "image_context_block": "",
            },
        )

        self.assertIn("<<<FILE:a.md>>>", rendered)
        self.assertNotIn("{{notes_block}}", rendered)

    def test_load_prompt_set_rejects_missing_required_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_root = root / "prompts"
            (prompt_root / "base").mkdir(parents=True)
            (prompt_root / "profiles" / "default").mkdir(parents=True)

            (prompt_root / "base" / "system.md").write_text("# System\n", encoding="utf-8")
            (prompt_root / "base" / "image_system.md").write_text("# Image System\n", encoding="utf-8")
            (prompt_root / "profiles" / "default" / "review.md").write_text("# Review\n\nNo placeholders here.", encoding="utf-8")
            (prompt_root / "profiles" / "default" / "patch.md").write_text("{{review_markdown}}\n\n{{notes_block}}\n\n{{patch_mode_instructions}}", encoding="utf-8")
            (prompt_root / "profiles" / "default" / "verify.md").write_text("{{review_markdown}}\n\n{{original_notes_block}}\n\n{{patched_notes_block}}\n\n{{image_context_block}}", encoding="utf-8")
            (prompt_root / "profiles" / "default" / "synthesize.md").write_text("{{review_markdown}}\n\n{{verify_markdown}}\n\n{{patched_notes_block}}", encoding="utf-8")
            (prompt_root / "profiles" / "default" / "image_user.md").write_text("{{markdown_file}}\n\n{{nearby_heading}}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "review.md"):
                load_prompt_set(project_root=root, prompt_root_dir=Path("prompts"), prompt_profile="default")


if __name__ == "__main__":
    unittest.main()

