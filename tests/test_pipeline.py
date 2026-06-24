from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from note_refinery_simple.pipeline import (
    PipelinePaths,
    ReviewPipeline,
    build_patch_prompt,
    build_review_prompt,
    build_synthesis_prompt,
    collect_image_tasks,
    clean_patched_markdown,
    parse_patch_payload,
    parse_synthesis_payload,
)
from note_refinery_simple.prompts import PromptSet


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
    def test_run_reports_stage_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nW = L", encoding="utf-8")

            messages: list[str] = []
            client = FakeLLMClient(
                [
                    "# Review\n\n- Fix Little's Law context.",
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nW = L / lambda"}}),
                    "# Verify\n\n- All requested fixes present.",
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\n## Unified Definitions\n\n- Little's Law needs stable system assumptions.",
                            "concept_map": {
                                "concepts": [
                                    {
                                        "name": "Little's Law",
                                        "sources": ["queueing.md"],
                                        "prerequisites": [],
                                    }
                                ],
                                "relationships": [],
                            },
                        }
                    ),
                ]
            )
            pipeline = ReviewPipeline(client, progress_callback=messages.append)
            paths = PipelinePaths.for_root(root)

            pipeline.run(notes_dir=notes_dir, paths=paths)

            self.assertIn("review: loaded 1 markdown file(s)", messages)
            self.assertIn("review: sending notes to reviewer", messages)
            self.assertIn("review: wrote REVIEW.md", messages)
            self.assertIn("patch: loaded 1 markdown file(s)", messages)
            self.assertIn("patch: sending notes to patcher", messages)
            self.assertIn("patch: wrote 1 patched file(s)", messages)
            self.assertIn("verify: sending notes to verifier", messages)
            self.assertIn("verify: wrote VERIFY.md", messages)
            self.assertIn("synthesize: loaded 1 patched markdown file(s)", messages)
            self.assertIn("synthesize: sending patched notes to synthesizer", messages)
            self.assertIn("synthesize: wrote SYNTHESIS.md and concept_map.json", messages)

    def test_review_reports_image_enrichment_progress(self) -> None:
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

            messages: list[str] = []
            client = FakeLLMClient(["# Review\n\n- Cross-check chart with text."])
            pipeline = ReviewPipeline(client, image_enricher=FakeImageEnricher(), progress_callback=messages.append)
            paths = PipelinePaths.for_root(root)

            pipeline.write_review(notes_dir=notes_dir, paths=paths)

            self.assertIn("review: enriching 1 image(s)", messages)
            self.assertIn("review: image 1/1 -> full.md (images/chart.jpg)", messages)

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

    def test_review_prompt_uses_external_markdown_template(self) -> None:
        prompt = build_review_prompt(
            {"full.md": "# Topic\n\nBody"},
            template="# Review Prompt\n\nCustom review instructions.\n\n{{notes_block}}\n\n{{image_context_block}}",
        )

        self.assertIn("Custom review instructions.", prompt)
        self.assertIn("<<<FILE:full.md>>>", prompt)

    def test_pipeline_uses_prompt_set_for_agent_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nW = L", encoding="utf-8")

            client = FakeLLMClient(
                [
                    "# Review\n\n- Fix Little's Law context.",
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nW = L / lambda"}}),
                    "# Verify\n\n- All requested fixes present.",
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\n## Unified Definitions\n\n- Little's Law needs stable system assumptions.",
                            "concept_map": {"concepts": [], "relationships": []},
                        }
                    ),
                ]
            )
            prompt_set = PromptSet(
                system_prompt="# System\n\nGlobal system rules.",
                image_system_prompt="# Image System\n\nImage system rules.",
                review_prompt="# Review Prompt\n\nCustom review instructions.\n\n{{notes_block}}\n\n{{image_context_block}}",
                patch_prompt="# Patch Prompt\n\nCustom patch instructions.\n\n{{review_markdown}}\n\n{{notes_block}}\n\n{{patch_mode_instructions}}\n\n{{image_context_block}}",
                verify_prompt="# Verify Prompt\n\nCustom verify instructions.\n\n{{review_markdown}}\n\n{{original_notes_block}}\n\n{{patched_notes_block}}\n\n{{image_context_block}}",
                synthesize_prompt="# Synthesize Prompt\n\nCustom synth instructions.\n\n{{review_markdown}}\n\n{{verify_markdown}}\n\n{{patched_notes_block}}",
                image_user_prompt="# Image Prompt\n\n{{markdown_file}}\n\n{{nearby_heading}}",
            )
            pipeline = ReviewPipeline(client, prompt_set=prompt_set)
            paths = PipelinePaths.for_root(root)

            pipeline.run(notes_dir=notes_dir, paths=paths)

            prompts_by_agent = {name: prompt for name, prompt in client.calls}
            self.assertIn("Custom review instructions.", prompts_by_agent["reviewer"])
            self.assertIn("Custom patch instructions.", prompts_by_agent["patcher"])
            self.assertIn("Custom verify instructions.", prompts_by_agent["verifier"])
            self.assertIn("Custom synth instructions.", prompts_by_agent["synthesizer"])

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
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\n## Cross-Source Relationships\n\n- Parallel movement chart aligns with corrected note.",
                            "concept_map": {
                                "concepts": [
                                    {
                                        "name": "Parallel movement",
                                        "sources": ["full.md"],
                                        "prerequisites": [],
                                    }
                                ],
                                "relationships": [],
                            },
                        }
                    ),
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

    def test_synthesis_prompt_requests_cross_source_relationships(self) -> None:
        prompt = build_synthesis_prompt(
            patched_notes={
                "lecture_a.md": "# Queueing\n\nLittle's Law links W, L, and lambda.",
                "lecture_b.md": "# Inventory\n\nEPQ depends on production and demand rates.",
            },
            review_markdown="# Review\n\n- Clarify assumptions.",
            verify_markdown="# Verify\n\n- Review findings resolved.",
        )

        self.assertIn("structured, interconnected teaching note", prompt)
        self.assertIn("prerequisite", prompt)
        self.assertIn("cross-source", prompt)
        self.assertIn("concept_map", prompt)

    def test_parse_synthesis_payload_accepts_fenced_json_with_trailing_text(self) -> None:
        payload = parse_synthesis_payload(
            "```json\n"
            '{"synthesis_markdown":"# Course Synthesis","concept_map":{"concepts":[],"relationships":[]}}\n'
            "```\n\nDone."
        )

        self.assertEqual(payload.synthesis_markdown, "# Course Synthesis")
        self.assertEqual(payload.concept_map["concepts"], [])

    def test_write_synthesis_creates_note_and_concept_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n", encoding="utf-8")

            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            paths.patched_notes_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n\n- Clarify assumptions.\n", encoding="utf-8")
            (paths.reports_dir / "VERIFY.md").write_text("# Verify\n\n- Looks consistent.\n", encoding="utf-8")
            (paths.patched_notes_dir / "queueing.md").write_text(
                "# Queueing\n\nLittle's Law needs stable assumptions.\n",
                encoding="utf-8",
            )

            client = FakeLLMClient(
                [
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\n## Concept Index\n\n- Little's Law",
                            "concept_map": {
                                "concepts": [
                                    {
                                        "name": "Little's Law",
                                        "sources": ["queueing.md"],
                                        "prerequisites": [],
                                    }
                                ],
                                "relationships": [
                                    {
                                        "from": "Little's Law",
                                        "to": "Stable system assumption",
                                        "type": "depends_on",
                                        "evidence": ["queueing.md"],
                                    }
                                ],
                            },
                        }
                    )
                ]
            )
            pipeline = ReviewPipeline(client)

            target = pipeline.write_synthesis(notes_dir=notes_dir, paths=paths)

            self.assertEqual(target.name, "SYNTHESIS.md")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Course Synthesis\n\n## Concept Index\n\n- Little's Law\n")
            concept_map = json.loads((paths.reports_dir / "concept_map.json").read_text(encoding="utf-8"))
            self.assertEqual(concept_map["concepts"][0]["name"], "Little's Law")
            self.assertEqual([name for name, _ in client.calls], ["synthesizer"])

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
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\n## Minimal Study Path\n\n1. Queueing basics\n2. Variance assumptions",
                            "concept_map": {
                                "concepts": [
                                    {"name": "Little's Law", "sources": ["queueing.md"], "prerequisites": []},
                                    {"name": "Covariance", "sources": ["stats.md"], "prerequisites": []},
                                ],
                                "relationships": [],
                            },
                        }
                    ),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)

            pipeline.run(notes_dir=notes_dir, paths=paths)

            self.assertEqual((paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"), "# Review\n\n- Fix Little's Law context.\n")
            self.assertEqual((paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"), "# Queueing\n\nW = L / lambda\n")
            self.assertEqual((paths.reports_dir / "VERIFY.md").read_text(encoding="utf-8"), "# Verify\n\n- All requested fixes present.\n")
            self.assertEqual((paths.reports_dir / "SYNTHESIS.md").read_text(encoding="utf-8"), "# Course Synthesis\n\n## Minimal Study Path\n\n1. Queueing basics\n2. Variance assumptions\n")
            self.assertEqual([name for name, _ in client.calls], ["reviewer", "patcher", "verifier", "synthesizer"])

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

    def test_write_patched_notes_retries_missing_files_multiple_times(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n", encoding="utf-8")
            (notes_dir / "stats.md").write_text("# Stats\n", encoding="utf-8")
            (notes_dir / "inventory.md").write_text("# Inventory\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nPatched queueing."}}),
                    json.dumps({"files": {"stats.md": "# Stats\n\nPatched stats."}}),
                    json.dumps({"files": {"inventory.md": "# Inventory\n\nPatched inventory."}}),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertEqual((paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"), "# Queueing\n\nPatched queueing.\n")
            self.assertEqual((paths.patched_notes_dir / "stats.md").read_text(encoding="utf-8"), "# Stats\n\nPatched stats.\n")
            self.assertEqual((paths.patched_notes_dir / "inventory.md").read_text(encoding="utf-8"), "# Inventory\n\nPatched inventory.\n")
            self.assertEqual([name for name, _ in client.calls], ["patcher", "patcher", "patcher"])

    def test_write_patched_notes_repairs_malformed_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    '{"files": {"queueing.md": "# Queueing\n\nBroken quote }}',
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nPatched queueing."}}),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertEqual((paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"), "# Queueing\n\nPatched queueing.\n")
            self.assertEqual([name for name, _ in client.calls], ["patcher", "patcher"])
            self.assertIn("repair", client.calls[1][1].lower())

    def test_write_patched_notes_falls_back_to_single_file_prompts_after_batch_stalls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n", encoding="utf-8")
            (notes_dir / "stats.md").write_text("# Stats\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps({"files": {}}),
                    json.dumps({"files": {}}),
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
            self.assertEqual([name for name, _ in client.calls], ["patcher", "patcher", "patcher", "patcher"])
            self.assertIn("missing files", client.calls[1][1].lower())
            self.assertIn("queueing.md", client.calls[2][1])
            self.assertIn("stats.md", client.calls[3][1])

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
                    json.dumps({"files": {}}),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)

            pipeline.write_review(notes_dir=notes_dir, paths=paths)

            with self.assertRaisesRegex(ValueError, "Missing patched content"):
                pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertEqual([name for name, _ in client.calls], ["reviewer", "patcher", "patcher", "patcher"])
            self.assertIn("missing files", client.calls[2][1].lower())
            self.assertIn("queueing.md", client.calls[3][1])

if __name__ == "__main__":
    unittest.main()




