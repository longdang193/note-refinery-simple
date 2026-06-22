from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from note_refinery_simple.pipeline import (
    PipelinePaths,
    ReviewPipeline,
    build_review_prompt,
    build_patch_prompt,
    collect_image_tasks,
    clean_patched_markdown,
    parse_patch_payload,
)


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def run_agent(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        return self._responses.pop(0)


class FakeImageEnricher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def describe_image(self, *, image_path: Path, markdown_file: str, nearby_heading: str | None) -> dict[str, object]:
        self.calls.append((str(image_path), markdown_file, nearby_heading))
        return {
            "image_path": image_path.name,
            "markdown_file": markdown_file,
            "nearby_heading": nearby_heading,
            "summary": "Line chart showing inventory rising then falling.",
            "confidence": "high",
        }


class ReviewPipelineTest(unittest.TestCase):
    def test_collect_image_tasks_finds_local_markdown_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            images_dir = notes_dir / "images"
            images_dir.mkdir(parents=True)
            (images_dir / "chart.jpg").write_bytes(b"fake-jpg")
            (notes_dir / "full.md").write_text(
                "# Parallel movement\n\n![](images/chart.jpg)\n",
                encoding="utf-8",
            )

            tasks = collect_image_tasks(notes_dir)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].markdown_file, "full.md")
            self.assertEqual(tasks[0].image_markdown_path, "images/chart.jpg")
            self.assertEqual(tasks[0].nearby_heading, "Parallel movement")

    def test_review_prompt_includes_image_context(self) -> None:
        prompt = build_review_prompt(
            {"full.md": "# Topic\n\n![](images/chart.jpg)"},
            image_contexts=[
                {
                    "image_path": "images/chart.jpg",
                    "markdown_file": "full.md",
                    "nearby_heading": "Topic",
                    "summary": "Line chart showing inventory rising then falling.",
                    "confidence": "high",
                }
            ],
        )

        self.assertIn("IMAGE_CONTEXT", prompt)
        self.assertIn("Line chart showing inventory rising then falling.", prompt)
        self.assertIn("images/chart.jpg", prompt)

    def test_patch_prompt_uses_filtered_image_context(self) -> None:
        prompt = build_patch_prompt(
            notes={"full.md": "# Topic\n\n![](images/chart.jpg)"},
            review_markdown="# Review\n\n- Fix chart/text mismatch.",
            image_contexts=[
                {
                    "image_path": "images/chart.jpg",
                    "markdown_file": "full.md",
                    "nearby_heading": "Topic",
                    "summary": "Line chart showing inventory rising then falling.",
                    "visible_text": ["I_max", "t_p", "t_d"],
                    "possible_risks": ["best-effort raw output from malformed JSON"],
                    "confidence": "high",
                }
            ],
        )

        self.assertIn("PATCH_IMAGE_CONTEXT", prompt)
        self.assertIn("Line chart showing inventory rising then falling.", prompt)
        self.assertIn('visible_text: ["I_max", "t_p", "t_d"]', prompt)
        self.assertNotIn("<<<IMAGE_CONTEXT>>>", prompt)
        self.assertNotIn("best-effort raw output", prompt)

    def test_patch_prompt_requests_clean_teaching_note_output(self) -> None:
        prompt = build_patch_prompt(
            notes={"full.md": "OTTO VON GUERICKE\n\n![](images/chart.jpg)\n\n## Topic"},
            review_markdown="# Review\n\n- Clean OCR noise.",
            patch_mode="clean-teaching",
        )

        self.assertIn("Rewrite each file into a clean teaching note", prompt)
        self.assertIn("Remove page headers, footers, branding", prompt)
        self.assertIn("Drop image markdown placeholders", prompt)
        self.assertIn("Merge duplicate headings", prompt)
        self.assertIn("Do not invent new algebra", prompt)
        self.assertIn("preserve formula meaning exactly", prompt)
        self.assertIn("Prefer short explanatory prose", prompt)
        self.assertIn("Drop auxiliary derivation symbols", prompt)

    def test_patch_prompt_conservative_mode_avoids_clean_teaching_rewrite_rules(self) -> None:
        prompt = build_patch_prompt(
            notes={"full.md": "# Topic\n\nOriginal text."},
            review_markdown="# Review\n\n- Fix notation.",
            patch_mode="conservative",
        )

        self.assertNotIn("Rewrite each file into a clean teaching note", prompt)
        self.assertNotIn("Drop auxiliary derivation symbols", prompt)
        self.assertIn("Preserve headings and teaching style where possible", prompt)

    def test_clean_patched_markdown_removes_footer_and_image_noise(self) -> None:
        cleaned = clean_patched_markdown(
            """
OTTO VON GUERICKE      Production Planning and Scheduling

![](images/chart.jpg)

## EPQ with Transport Batches
## EPQ with Transport Batches

Inventory

### Core idea
Good teaching text.
"""
        )

        self.assertNotIn("OTTO VON GUERICKE", cleaned)
        self.assertNotIn("![](images/chart.jpg)", cleaned)
        self.assertEqual(cleaned.count("## EPQ with Transport Batches"), 1)
        self.assertNotIn("\nInventory\n", cleaned)
        self.assertIn("### Core idea", cleaned)

    def test_write_patched_notes_applies_cleanup_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "full.md").write_text("# Topic\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps(
                        {
                            "files": {
                                "full.md": "OTTO VON GUERICKE      Production Planning and Scheduling\n\n![](images/chart.jpg)\n\n## Topic\n## Topic\n\nClean explanation."
                            }
                        }
                    )
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)
            (paths.reports_dir).mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            patched = (paths.patched_notes_dir / "full.md").read_text(encoding="utf-8")
            self.assertNotIn("OTTO VON GUERICKE", patched)
            self.assertNotIn("![](images/chart.jpg)", patched)
            self.assertEqual(patched.count("## Topic"), 1)
            self.assertIn("Clean explanation.", patched)

    def test_parse_patch_payload_accepts_fenced_json_with_trailing_text(self) -> None:
        payload = parse_patch_payload(
            "```json\n{\"files\":{\"full.md\":\"# Topic\\n\\nClean note.\"}}\n```\n\nDone.\n"
        )

        self.assertEqual(payload["full.md"], "# Topic\n\nClean note.")

    def test_run_writes_image_context_artifact_when_images_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            images_dir = notes_dir / "images"
            images_dir.mkdir(parents=True)
            (images_dir / "chart.jpg").write_bytes(b"fake-jpg")
            (notes_dir / "full.md").write_text(
                "# Parallel movement\n\n![](images/chart.jpg)\n",
                encoding="utf-8",
            )

            client = FakeLLMClient(
                [
                    "# Review\n\n- Cross-check chart with text.",
                    json.dumps({"files": {"full.md": "# Parallel movement\n\nCorrected notes.\n"}}),
                    "# Verify\n\n- Verified.",
                ]
            )
            image_enricher = FakeImageEnricher()
            pipeline = ReviewPipeline(client, image_enricher=image_enricher)
            paths = PipelinePaths.for_root(root)

            pipeline.run(notes_dir=notes_dir, paths=paths)

            image_context_path = paths.reports_dir / "image_context.json"
            self.assertTrue(image_context_path.exists())
            payload = json.loads(image_context_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["markdown_file"], "full.md")
            self.assertEqual(payload[0]["confidence"], "high")
            self.assertEqual(len(image_enricher.calls), 1)

    def test_review_prompt_requires_cross_file_inconsistency_scan(self) -> None:
        prompt = build_review_prompt(
            {
                "lecture_a.md": "# A\n\nLet lambda be arrival rate.",
                "lecture_b.md": "# B\n\nLet lambda be service rate.",
            }
        )

        self.assertIn("cross-file consistency", prompt)
        self.assertIn("Cross-file inconsistency", prompt)
        self.assertIn("symbols defined differently across files", prompt)

    def test_run_writes_review_patched_notes_and_verify_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nW = L", encoding="utf-8")
            (notes_dir / "stats.md").write_text("# Stats\n\nVar(X+Y)=Var(X)+Var(Y)", encoding="utf-8")

            patch_payload = json.dumps(
                {
                    "files": {
                        "queueing.md": "# Queueing\n\nW = L / lambda",
                        "stats.md": "# Stats\n\nVar(X+Y)=Var(X)+Var(Y)+2Cov(X,Y)",
                    }
                }
            )
            client = FakeLLMClient(
                [
                    "# Review\n\n- Fix Little's Law context.",
                    patch_payload,
                    "# Verify\n\n- All requested fixes present.",
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)

            pipeline.run(notes_dir=notes_dir, paths=paths)

            self.assertEqual((paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"), "# Review\n\n- Fix Little's Law context.\n")
            self.assertEqual((paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"), "# Queueing\n\nW = L / lambda\n")
            self.assertEqual((paths.reports_dir / "VERIFY.md").read_text(encoding="utf-8"), "# Verify\n\n- All requested fixes present.\n")
            self.assertEqual([name for name, _ in client.calls], ["reviewer", "patcher", "verifier"])

    def test_write_patched_notes_retries_missing_files_with_narrower_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n", encoding="utf-8")
            (notes_dir / "stats.md").write_text("# Stats\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nPatched queueing."}}),
                    json.dumps({"files": {"stats.md": "# Stats\n\nPatched stats."}}),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertEqual((paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"), "# Queueing\n\nPatched queueing.\n")
            self.assertEqual((paths.patched_notes_dir / "stats.md").read_text(encoding="utf-8"), "# Stats\n\nPatched stats.\n")
            self.assertEqual([name for name, _ in client.calls], ["patcher", "patcher"])
            self.assertIn("missing files", client.calls[1][1].lower())

    def test_patcher_rejects_missing_file_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    "# Review\n",
                    json.dumps({"files": {}}),
                    json.dumps({"files": {}}),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)

            pipeline.write_review(notes_dir=notes_dir, paths=paths)

            with self.assertRaisesRegex(ValueError, "Missing patched content"):
                pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)


if __name__ == "__main__":
    unittest.main()
