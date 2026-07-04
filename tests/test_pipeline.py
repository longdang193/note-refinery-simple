from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from note_refinery_simple.pipeline import (
    PipelinePaths,
    ReviewPipeline,
    build_patch_prompt,
    build_review_prompt,
    build_synthesis_prompt,
    collect_review_note_dirs,
    collect_image_tasks,
    clean_patched_markdown,
    parse_patch_payload,
    parse_synthesis_payload,
    read_notes,
)
from note_refinery_simple.prompts import PromptSet


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []

    def run_agent(self, agent_name: str, prompt: str) -> str:
        with self._lock:
            self.calls.append((agent_name, prompt))
            return self._responses.pop(0)


class RoutingFakeLLMClient:
    def __init__(self, response_by_file: dict[str, list[str]], verify_responses: list[str] | None = None) -> None:
        self._response_by_file = {key: list(value) for key, value in response_by_file.items()}
        self._verify_responses = list(verify_responses or [])
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []
        self.patch_active = 0
        self.saw_parallel_patch = False

    def run_agent(self, agent_name: str, prompt: str) -> str:
        with self._lock:
            self.calls.append((agent_name, prompt))
        if agent_name == "verifier":
            with self._lock:
                return self._verify_responses.pop(0)
        if agent_name != "patcher":
            raise AssertionError(f"Unexpected agent: {agent_name}")
        note_name = extract_prompt_file_name(prompt)
        if note_name is None:
            raise AssertionError("Patch prompt did not contain a file marker")
        with self._lock:
            self.patch_active += 1
            if self.patch_active > 1:
                self.saw_parallel_patch = True
        time.sleep(0.02)
        try:
            with self._lock:
                responses = self._response_by_file[note_name]
                return responses.pop(0)
        finally:
            with self._lock:
                self.patch_active -= 1


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

class SlowImageEnricher:
    def __init__(self, delay_seconds: float = 0.1) -> None:
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[str, str, str | None]] = []
        self._lock = threading.Lock()

    def describe_image(self, *, image_path: Path, markdown_file: str, nearby_heading: str | None) -> dict[str, object]:
        with self._lock:
            self.calls.append((str(image_path), markdown_file, nearby_heading))
        time.sleep(self.delay_seconds)
        return {
            "image_path": image_path.name,
            "markdown_file": markdown_file,
            "nearby_heading": nearby_heading,
            "summary": "Slow chart summary.",
            "confidence": "high",
        }


class FailingImageEnricher:
    def describe_image(self, *, image_path: Path, markdown_file: str, nearby_heading: str | None) -> dict[str, object]:
        raise RuntimeError("temporary 502")

class ProgressAbort:
    def __init__(self, target_message: str) -> None:
        self.target_message = target_message
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)
        if message == self.target_message:
            raise RuntimeError("stop-after-first-image")

def extract_prompt_file_name(prompt: str) -> str | None:
    marker = "<<<FILE:"
    start = prompt.find(marker)
    if start < 0:
        return None
    end = prompt.find(">>>", start)
    if end < 0:
        return None
    return prompt[start + len(marker) : end]


class ReviewPipelineTest(unittest.TestCase):
    def test_read_notes_loads_supported_source_types_with_canonical_logical_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir)
            (notes_dir / "lesson.md").write_text("# Lesson\n\nBody\n", encoding="utf-8")
            (notes_dir / "solver.py").write_text("print('hello')\n", encoding="utf-8")
            (notes_dir / "lab.ipynb").write_text(
                json.dumps(
                    {
                        "cells": [
                            {"cell_type": "markdown", "metadata": {}, "source": ["# Lab\n"]},
                            {"cell_type": "code", "metadata": {}, "execution_count": 1, "outputs": [], "source": ["x = 1\n"]},
                        ],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5,
                    }
                ),
                encoding="utf-8",
            )

            notes = read_notes(notes_dir)

            self.assertEqual(set(notes), {"lesson.md", "solver.py.md", "lab.ipynb.md"})
            self.assertIn("print('hello')", notes["solver.py.md"])
            self.assertIn("# Lab", notes["lab.ipynb.md"])

    def test_collect_review_note_dirs_includes_child_folders_with_python_or_notebook_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir)
            folder_a = notes_dir / "folder-a"
            folder_b = notes_dir / "folder-b"
            folder_a.mkdir(parents=True)
            folder_b.mkdir(parents=True)
            (folder_a / "solver.py").write_text("print('a')\n", encoding="utf-8")
            (folder_b / "lab.ipynb").write_text(
                json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}),
                encoding="utf-8",
            )

            review_dirs = collect_review_note_dirs(notes_dir)

            self.assertEqual(review_dirs, [folder_a, folder_b])

    def test_collect_review_note_dirs_rejects_mixed_root_and_child_source_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir)
            (notes_dir / "lesson.md").write_text("# Root\n", encoding="utf-8")
            folder_a = notes_dir / "folder-a"
            folder_a.mkdir(parents=True)
            (folder_a / "solver.py").write_text("print('a')\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "mixed"):
                collect_review_note_dirs(notes_dir)

    def test_read_notes_and_batch_detection_ignore_generated_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir)
            folder_a = notes_dir / "folder-a"
            folder_a.mkdir(parents=True)
            (folder_a / "lesson.md").write_text("# Lesson\n", encoding="utf-8")
            checkpoint_dir = notes_dir / ".ipynb_checkpoints"
            checkpoint_dir.mkdir(parents=True)
            (checkpoint_dir / "shadow.ipynb").write_text(
                json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}),
                encoding="utf-8",
            )
            venv_dir = notes_dir / ".venv" / "lib"
            venv_dir.mkdir(parents=True)
            (venv_dir / "noise.py").write_text("print('noise')\n", encoding="utf-8")

            review_dirs = collect_review_note_dirs(notes_dir)
            notes = read_notes(notes_dir)

            self.assertEqual(review_dirs, [folder_a])
            self.assertEqual(set(notes), {"folder-a/lesson.md"})

    def test_read_notes_normalizes_notebook_plain_text_outputs_in_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir)
            (notes_dir / "lab.ipynb").write_text(
                json.dumps(
                    {
                        "cells": [
                            {"cell_type": "markdown", "metadata": {}, "source": ["# Lab\n"]},
                            {
                                "cell_type": "code",
                                "metadata": {},
                                "execution_count": 1,
                                "source": ["print('hi')\n"],
                                "outputs": [
                                    {"output_type": "stream", "name": "stdout", "text": ["hi\n"]},
                                    {"output_type": "execute_result", "data": {"text/plain": ["42"]}, "metadata": {}, "execution_count": 1},
                                ],
                            },
                        ],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5,
                    }
                ),
                encoding="utf-8",
            )

            notes = read_notes(notes_dir)

            notebook_text = notes["lab.ipynb.md"]
            self.assertIn("# Lab", notebook_text)
            self.assertIn("```python\nprint('hi')", notebook_text)
            self.assertIn("```text\nhi\n```", notebook_text)
            self.assertIn("```text\n42\n```", notebook_text)

    def test_read_notes_omits_unsupported_notebook_rich_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir)
            (notes_dir / "lab.ipynb").write_text(
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "code",
                                "metadata": {},
                                "execution_count": 1,
                                "source": ["display('x')\n"],
                                "outputs": [
                                    {"output_type": "display_data", "data": {"image/png": "abc", "text/html": ["<b>x</b>"]}, "metadata": {}},
                                ],
                            },
                        ],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5,
                    }
                ),
                encoding="utf-8",
            )

            notes = read_notes(notes_dir)

            notebook_text = notes["lab.ipynb.md"]
            self.assertNotIn("image/png", notebook_text)
            self.assertNotIn("<b>x</b>", notebook_text)

    def test_write_review_writes_batch_manifest_for_folder_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name in ("folder-a", "folder-b"):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text(f"# {folder_name}\n\nBody\n", encoding="utf-8")

            client = FakeLLMClient(["# Review\n\n- A.", "# Review\n\n- B."])
            pipeline = ReviewPipeline(client, review_folder_concurrency=2)
            paths = PipelinePaths.for_root(root / "out")

            pipeline.write_review(notes_dir=notes_dir, paths=paths)

            manifest = json.loads((paths.root / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest,
                {
                    "folders": [
                        {
                            "folder_id": "folder-a",
                            "source_rel_path": "folder-a",
                            "output_rel_path": "folder-a",
                        },
                        {
                            "folder_id": "folder-b",
                            "source_rel_path": "folder-b",
                            "output_rel_path": "folder-b",
                        },
                    ]
                },
            )

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
                    "# Verify\n\n## Possible Regressions\n\nNone.\n\n## Overall Verdict\n\nPass.",
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
            self.assertIn("patch: loaded 1 markdown file(s)", messages)
            self.assertIn("patch: file 1/1 [queueing.md]", messages)
            self.assertIn("patch: wrote 1 patched file(s)", messages)
            self.assertIn("verify: done", messages)
            self.assertIn("synthesize: done", messages)

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
            self.assertIn("review: image 1/1", messages)

    def test_write_review_can_process_note_folders_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            first_dir = notes_dir / "folder-a"
            second_dir = notes_dir / "folder-b"
            for folder in (first_dir, second_dir):
                images_dir = folder / "images"
                images_dir.mkdir(parents=True)
                (images_dir / "chart.jpg").write_bytes(b"fake-jpg")
                (folder / "full.md").write_text("# Topic\n\n![](images/chart.jpg)\n", encoding="utf-8")

            client = FakeLLMClient(["# Review\n\n- A.", "# Review\n\n- B."])
            image_enricher = SlowImageEnricher(delay_seconds=0.1)
            pipeline = ReviewPipeline(
                client,
                image_enricher=image_enricher,
                review_folder_concurrency=2,
            )
            paths = PipelinePaths.for_root(root / "out")

            started = time.perf_counter()
            pipeline.write_review(notes_dir=notes_dir, paths=paths)
            elapsed = time.perf_counter() - started

            self.assertLess(elapsed, 0.18)
            self.assertTrue((paths.root / "folder-a" / "reports" / "REVIEW.md").exists())
            self.assertTrue((paths.root / "folder-b" / "reports" / "REVIEW.md").exists())
            self.assertFalse((paths.reports_dir / "REVIEW.md").exists())

    def test_write_review_keeps_image_order_sequential_within_each_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            first_dir = notes_dir / "folder-a"
            second_dir = notes_dir / "folder-b"
            (first_dir / "images").mkdir(parents=True)
            (second_dir / "images").mkdir(parents=True)
            (first_dir / "images" / "chart-1.jpg").write_bytes(b"fake-jpg")
            (first_dir / "images" / "chart-2.jpg").write_bytes(b"fake-jpg")
            (second_dir / "images" / "chart.jpg").write_bytes(b"fake-jpg")
            (first_dir / "full.md").write_text(
                "# Topic A\n\n![](images/chart-1.jpg)\n![](images/chart-2.jpg)\n",
                encoding="utf-8",
            )
            (second_dir / "full.md").write_text("# Topic B\n\n![](images/chart.jpg)\n", encoding="utf-8")

            client = FakeLLMClient(["# Review\n\n- A.", "# Review\n\n- B."])
            image_enricher = FakeImageEnricher()
            pipeline = ReviewPipeline(
                client,
                image_enricher=image_enricher,
                review_folder_concurrency=2,
            )
            paths = PipelinePaths.for_root(root / "out")

            pipeline.write_review(notes_dir=notes_dir, paths=paths)

            first_folder_calls = [call[0] for call in image_enricher.calls if "folder-a" in call[0]]
            self.assertEqual(
                [Path(call).name for call in first_folder_calls],
                ["chart-1.jpg", "chart-2.jpg"],
            )

    def test_write_review_reports_folder_context_during_batch_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name in ("folder-a", "folder-b"):
                folder = notes_dir / folder_name
                images_dir = folder / "images"
                images_dir.mkdir(parents=True)
                (images_dir / "chart.jpg").write_bytes(b"fake-jpg")
                (folder / "full.md").write_text("# Topic\n\n![](images/chart.jpg)\n", encoding="utf-8")

            messages: list[str] = []
            client = FakeLLMClient(["# Review\n\n- A.", "# Review\n\n- B."])
            pipeline = ReviewPipeline(
                client,
                image_enricher=FakeImageEnricher(),
                review_folder_concurrency=2,
                progress_callback=messages.append,
            )

            pipeline.write_review(notes_dir=notes_dir, paths=PipelinePaths.for_root(root / "out"))

            self.assertTrue(any(message == "review [1/2 folder-a] start" for message in messages))
            self.assertTrue(any(message.startswith("review [folder-a]") for message in messages))
            self.assertTrue(any(message.startswith("review [folder-b]") for message in messages))

    def test_write_review_shortens_long_folder_scope_in_progress_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            folder_name = "26_1_OPT_II_Introduction.pdf-308ecce5-31c0-4b3f-8d45-4e1a1cb63b4d"
            folder = notes_dir / folder_name
            images_dir = folder / "images"
            images_dir.mkdir(parents=True)
            (images_dir / "chart.jpg").write_bytes(b"fake-jpg")
            (folder / "full.md").write_text("# Topic\n\n![](images/chart.jpg)\n", encoding="utf-8")

            messages: list[str] = []
            client = FakeLLMClient(["# Review\n\n- A."])
            pipeline = ReviewPipeline(
                client,
                image_enricher=FakeImageEnricher(),
                review_folder_concurrency=1,
                progress_callback=messages.append,
            )

            pipeline.write_review(notes_dir=notes_dir, paths=PipelinePaths.for_root(root / "out"))

            self.assertIn("review [1/1 26_1_OPT_II_Introduction] start", messages)
            self.assertTrue(any(message.startswith("review [26_1_OPT_II_Introduction] image 1/1") for message in messages))

    def test_write_review_rejects_shared_cached_image_context_for_batch_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name in ("folder-a", "folder-b"):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text("# Topic\n\nBody\n", encoding="utf-8")

            pipeline = ReviewPipeline(FakeLLMClient([]), review_folder_concurrency=2)

            with self.assertRaisesRegex(ValueError, "shared cached image context"):
                pipeline.write_review(
                    notes_dir=notes_dir,
                    paths=PipelinePaths.for_root(root / "out"),
                    cached_image_contexts=[{"markdown_file": "full.md", "image_path": "images/chart.jpg"}],
                )

    def test_review_keeps_running_when_one_image_enrichment_fails(self) -> None:
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

            client = FakeLLMClient(["# Review\n\n- Continue despite image failure."])
            pipeline = ReviewPipeline(client, image_enricher=FailingImageEnricher())
            paths = PipelinePaths.for_root(root)

            pipeline.write_review(notes_dir=notes_dir, paths=paths)

            image_contexts = json.loads((paths.reports_dir / "image_context.json").read_text(encoding="utf-8"))
            self.assertEqual(image_contexts[0]["confidence"], "low")
            self.assertIn("temporary 502", image_contexts[0]["possible_risks"][0])
            self.assertEqual((paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"), "# Review\n\n- Continue despite image failure.\n")

    def test_review_persists_partial_image_cache_before_later_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            images_dir = notes_dir / "images"
            images_dir.mkdir(parents=True)
            (images_dir / "chart-1.jpg").write_bytes(b"fake-jpg")
            (images_dir / "chart-2.jpg").write_bytes(b"fake-jpg")
            (notes_dir / "full.md").write_text(
                "# Parallel movement\n\n![](images/chart-1.jpg)\n![](images/chart-2.jpg)\n",
                encoding="utf-8",
            )

            progress = ProgressAbort("review: image 2/2")
            client = FakeLLMClient(["# Review\n\n- Unused because abort happens first."])
            pipeline = ReviewPipeline(
                client,
                image_enricher=FakeImageEnricher(),
                progress_callback=progress,
            )
            paths = PipelinePaths.for_root(root)

            with self.assertRaisesRegex(RuntimeError, "stop-after-first-image"):
                pipeline.write_review(notes_dir=notes_dir, paths=paths)

            image_context_path = paths.reports_dir / "image_context.json"
            self.assertTrue(image_context_path.exists())
            payload = json.loads(image_context_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["image_path"], "images/chart-1.jpg")

    def test_write_review_can_reuse_cached_image_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "full.md").write_text("# Topic\n\nBody\n", encoding="utf-8")

            cached_image_contexts: list[dict[str, object]] = [
                {
                    "image_path": "images/chart.jpg",
                    "markdown_file": "full.md",
                    "nearby_heading": "Topic",
                    "summary": "Cached chart summary.",
                    "confidence": "high",
                }
            ]
            client = FakeLLMClient(["# Review\n\n- Used cached image context."])
            image_enricher = FakeImageEnricher()
            pipeline = ReviewPipeline(client, image_enricher=image_enricher)
            paths = PipelinePaths.for_root(root)

            pipeline.write_review(
                notes_dir=notes_dir,
                paths=paths,
                cached_image_contexts=cached_image_contexts,
            )

            self.assertEqual(image_enricher.calls, [])
            self.assertEqual(
                json.loads((paths.reports_dir / "image_context.json").read_text(encoding="utf-8")),
                cached_image_contexts,
            )
            review_prompt = client.calls[0][1]
            self.assertIn("Cached chart summary.", review_prompt)

    def test_write_review_reuses_partial_cached_image_context_and_enriches_missing_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            images_dir = notes_dir / "images"
            images_dir.mkdir(parents=True)
            (images_dir / "chart-1.jpg").write_bytes(b"fake-jpg")
            (images_dir / "chart-2.jpg").write_bytes(b"fake-jpg")
            (notes_dir / "full.md").write_text(
                "# Parallel movement\n\n![](images/chart-1.jpg)\n![](images/chart-2.jpg)\n",
                encoding="utf-8",
            )

            cached_image_contexts: list[dict[str, object]] = [
                {
                    "image_path": "images/chart-1.jpg",
                    "markdown_file": "full.md",
                    "nearby_heading": "Parallel movement",
                    "summary": "Cached first chart.",
                    "confidence": "high",
                }
            ]
            client = FakeLLMClient(["# Review\n\n- Used mixed cache and fresh image context."])
            image_enricher = FakeImageEnricher()
            pipeline = ReviewPipeline(client, image_enricher=image_enricher)
            paths = PipelinePaths.for_root(root)

            pipeline.write_review(
                notes_dir=notes_dir,
                paths=paths,
                cached_image_contexts=cached_image_contexts,
            )

            payload = json.loads((paths.reports_dir / "image_context.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 2)
            self.assertEqual(payload[0]["image_path"], "images/chart-1.jpg")
            self.assertEqual(payload[0]["summary"], "Cached first chart.")
            self.assertEqual(len(image_enricher.calls), 1)
            self.assertTrue(image_enricher.calls[0][0].endswith("chart-2.jpg"))
            self.assertIn("Cached first chart.", client.calls[0][1])
            self.assertIn("Line chart showing inventory rising then falling.", client.calls[0][1])

    def test_run_can_process_folder_collection_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name in ("folder-a", "folder-b"):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text("# Topic\n\nBody\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    "# Review\n\n- A.",
                    "# Review\n\n- B.",
                    json.dumps({"files": {"full.md": "# Topic\n\nPatched A.\n"}}),
                    json.dumps({"files": {"full.md": "# Topic\n\nPatched B.\n"}}),
                    "# Verify\n\n## Overall Verdict\n\nPass.\n",
                    json.dumps(
                        {
                            "synthesis_markdown": "# Synthesis\n\nBatch ready.\n",
                            "concept_map": {"concepts": [], "relationships": []},
                        }
                    ),
                ]
            )
            pipeline = ReviewPipeline(client, review_folder_concurrency=2, patch_concurrency=1)
            paths = PipelinePaths.for_root(root / "out")

            pipeline.run(notes_dir=notes_dir, paths=paths)

            self.assertTrue((paths.root / "batch_manifest.json").exists())
            self.assertTrue((paths.root / "folder-a" / "reports" / "REVIEW.md").exists())
            self.assertTrue((paths.root / "folder-b" / "reports" / "REVIEW.md").exists())
            self.assertTrue((paths.root / "folder-a" / "patched_notes" / "full.md").exists())
            self.assertTrue((paths.root / "folder-b" / "patched_notes" / "full.md").exists())
            self.assertEqual((paths.reports_dir / "VERIFY.md").read_text(encoding="utf-8"), "# Verify\n\n## Overall Verdict\n\nPass.\n")
            self.assertEqual((paths.reports_dir / "SYNTHESIS.md").read_text(encoding="utf-8"), "# Synthesis\n\nBatch ready.\n")

    def test_run_can_reuse_cached_review_without_calling_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nOriginal queueing text.\n", encoding="utf-8")

            cached_image_contexts: list[dict[str, object]] = [
                {
                    "image_path": "images/chart.jpg",
                    "markdown_file": "queueing.md",
                    "nearby_heading": "Queueing",
                    "summary": "Cached chart summary.",
                    "confidence": "medium",
                }
            ]
            client = FakeLLMClient(
                [
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nPatched queueing."}}),
                    "# Verify\n\n## Possible Regressions\n\nNone.\n\n## Overall Verdict\n\nPass.",
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\nReady.",
                            "concept_map": {"concepts": [], "relationships": []},
                        }
                    ),
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root)

            pipeline.run(
                notes_dir=notes_dir,
                paths=paths,
                reuse_review_markdown="# Review\n\n- Reused cached review.",
                cached_image_contexts=cached_image_contexts,
            )

            self.assertEqual((paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"), "# Review\n\n- Reused cached review.\n")
            self.assertEqual(
                json.loads((paths.reports_dir / "image_context.json").read_text(encoding="utf-8")),
                cached_image_contexts,
            )
            self.assertEqual([name for name, _ in client.calls], ["patcher", "verifier", "synthesizer"])

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
                    "# Verify\n\n## Possible Regressions\n\nNone.\n\n## Overall Verdict\n\nPass.",
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

    def test_patch_prompt_conservative_mode_avoids_clean_teaching_rewrite_rules(self) -> None:
        prompt = build_patch_prompt(
            notes={"full.md": "# Topic\n\nOriginal text."},
            review_markdown="# Review\n\n- Fix notation.",
            patch_mode="conservative",
        )

        self.assertNotIn("Rewrite each file into a clean teaching note", prompt)
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
        self.assertIn("### Core idea", cleaned)

    def test_clean_patched_markdown_preserves_fenced_code_indentation(self) -> None:
        cleaned = clean_patched_markdown(
            """
## Example

```python
def act(state: dict) -> bool:
    if state["Item"].weight <= state["Cur_Cap"]:
        return True
    return False
```
"""
        )

        self.assertIn("```python", cleaned)
        self.assertIn("    if state[\"Item\"].weight <= state[\"Cur_Cap\"]:", cleaned)
        self.assertIn("        return True", cleaned)
        self.assertIn("```", cleaned)

    def test_patch_prompt_requests_short_code_snippets_for_illustration(self) -> None:
        prompt = build_patch_prompt(
            notes={"full.py.md": "# Example\n\n```python\nprint('x')\n```\n"},
            review_markdown="# Review\n\n- Clarify policy behavior.",
            patch_mode="clean-teaching",
        )

        self.assertIn("Include short code snippets", prompt)

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
                    "# Verify\n\n## Possible Regressions\n\nNone.\n\n## Overall Verdict\n\nPass.",
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

    def test_write_synthesis_recovers_from_malformed_json(self) -> None:
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
                    "{\n  \"synthesis_markdown\": \"# Course Synthesis\",\n  \"concept_map\": {\n",
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
                                "relationships": [],
                            },
                        }
                    ),
                ]
            )
            pipeline = ReviewPipeline(client)

            target = pipeline.write_synthesis(notes_dir=notes_dir, paths=paths)

            self.assertEqual(target.name, "SYNTHESIS.md")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Course Synthesis\n\n## Concept Index\n\n- Little's Law\n")
            self.assertEqual([name for name, _ in client.calls], ["synthesizer", "synthesizer"])

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
                                "relationships": [],
                            },
                        }
                    )
                ]
            )
            pipeline = ReviewPipeline(client)

            target = pipeline.write_synthesis(notes_dir=notes_dir, paths=paths)

            self.assertEqual(target.name, "SYNTHESIS.md")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Course Synthesis\n\n## Concept Index\n\n- Little's Law\n")

    def test_write_patched_notes_patches_each_file_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nOriginal queueing text.", encoding="utf-8")
            (notes_dir / "inventory.md").write_text("# Inventory\n\nOriginal inventory text.", encoding="utf-8")

            client = RoutingFakeLLMClient(
                {
                    "queueing.md": [json.dumps({"files": {"queueing.md": "# Queueing\n\nPatched queueing."}})],
                    "inventory.md": [json.dumps({"files": {"inventory.md": "# Inventory\n\nPatched inventory."}})],
                }
            )
            pipeline = ReviewPipeline(client, patch_concurrency=1)
            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            patch_calls = [prompt for name, prompt in client.calls if name == "patcher"]
            self.assertEqual(len(patch_calls), 2)
            self.assertEqual(sum("<<<FILE:queueing.md>>>" in prompt for prompt in patch_calls), 1)
            self.assertEqual(sum("<<<FILE:inventory.md>>>" in prompt for prompt in patch_calls), 1)
            for prompt in patch_calls:
                self.assertNotEqual(
                    "<<<FILE:queueing.md>>>" in prompt,
                    "<<<FILE:inventory.md>>>" in prompt,
                )

    def test_write_patched_notes_retries_rejected_topic_for_one_file_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            note_name = "ACT2026_10_Variable Neighborhood Search/full.md"
            target_note = notes_dir / note_name
            target_note.parent.mkdir(parents=True, exist_ok=True)
            target_note.write_text("# Variable Neighborhood Search\n\nOriginal note.", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps({"files": {note_name: "# Optimization and Linear Programming\n\nWrong topic."}}),
                    json.dumps({"files": {note_name: "# Variable Neighborhood Search\n\nCorrect topic."}}),
                ]
            )
            messages: list[str] = []
            pipeline = ReviewPipeline(client, patch_concurrency=1, progress_callback=messages.append)
            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertEqual(
                (paths.patched_notes_dir / note_name).read_text(encoding="utf-8"),
                "# Variable Neighborhood Search\n\nCorrect topic.\n",
            )
            self.assertIn("patch: topic guard failed -> ACT2026_10_Variable Neighborhood Search/full.md", messages)
            self.assertEqual([name for name, _ in client.calls], ["patcher", "patcher"])

    def test_run_repatches_only_flagged_files_after_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nOriginal queueing text.", encoding="utf-8")
            (notes_dir / "inventory.md").write_text("# Inventory\n\nOriginal inventory text.", encoding="utf-8")

            messages: list[str] = []
            client = FakeLLMClient(
                [
                    "# Review\n",
                    json.dumps({"files": {"inventory.md": "# Inventory\n\nPatched inventory."}}),
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nFirst queueing patch."}}),
                    "# VERIFY.md\n\n## Possible Regressions\n- `queueing.md` still drifts from source topic.\n\n## Overall Verdict\nPartial pass.\n",
                    json.dumps({"files": {"queueing.md": "# Queueing\n\nSecond queueing patch."}}),
                    "# VERIFY.md\n\n## Possible Regressions\nNone.\n\n## Overall Verdict\nPass.\n",
                    json.dumps(
                        {
                            "synthesis_markdown": "# Course Synthesis\n\nReady.",
                            "concept_map": {"concepts": [], "relationships": []},
                        }
                    ),
                ]
            )
            pipeline = ReviewPipeline(client, patch_concurrency=1, progress_callback=messages.append)
            paths = PipelinePaths.for_root(root)

            pipeline.run(notes_dir=notes_dir, paths=paths)

            self.assertEqual(
                (paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"),
                "# Queueing\n\nSecond queueing patch.\n",
            )
            self.assertEqual(
                (paths.patched_notes_dir / "inventory.md").read_text(encoding="utf-8"),
                "# Inventory\n\nPatched inventory.\n",
            )
            self.assertIn("patch: repairing 1 flagged file(s) after verify", messages)
            self.assertEqual([name for name, _ in client.calls].count("patcher"), 3)

    def test_write_patched_notes_uses_concurrency_without_output_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "queueing.md").write_text("# Queueing\n\nOriginal queueing text.", encoding="utf-8")
            (notes_dir / "inventory.md").write_text("# Inventory\n\nOriginal inventory text.", encoding="utf-8")

            client = RoutingFakeLLMClient(
                {
                    "queueing.md": [json.dumps({"files": {"queueing.md": "# Queueing\n\nPatched queueing."}})],
                    "inventory.md": [json.dumps({"files": {"inventory.md": "# Inventory\n\nPatched inventory."}})],
                }
            )
            pipeline = ReviewPipeline(client, patch_concurrency=2)
            paths = PipelinePaths.for_root(root)
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertTrue(client.saw_parallel_patch)
            self.assertEqual((paths.patched_notes_dir / "queueing.md").read_text(encoding="utf-8"), "# Queueing\n\nPatched queueing.\n")
            self.assertEqual((paths.patched_notes_dir / "inventory.md").read_text(encoding="utf-8"), "# Inventory\n\nPatched inventory.\n")

    def test_write_patched_notes_can_patch_all_manifest_listed_folders_from_batch_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name, heading in (("folder-a", "Queueing"), ("folder-b", "Inventory")):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text(f"# {heading}\n\nOriginal text.\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps({"files": {"full.md": "# Queueing\n\nPatched queueing.\n"}}),
                    json.dumps({"files": {"full.md": "# Inventory\n\nPatched inventory.\n"}}),
                ]
            )
            pipeline = ReviewPipeline(client, patch_concurrency=1)
            paths = PipelinePaths.for_root(root / "out")
            (paths.root / "folder-a" / "reports").mkdir(parents=True, exist_ok=True)
            (paths.root / "folder-b" / "reports").mkdir(parents=True, exist_ok=True)
            (paths.root / "folder-a" / "reports" / "REVIEW.md").write_text("# Review A\n", encoding="utf-8")
            (paths.root / "folder-b" / "reports" / "REVIEW.md").write_text("# Review B\n", encoding="utf-8")
            (paths.root / "batch_manifest.json").write_text(
                json.dumps(
                    {
                        "folders": [
                            {
                                "folder_id": "folder-a",
                                "source_rel_path": "folder-a",
                                "output_rel_path": "folder-a",
                            },
                            {
                                "folder_id": "folder-b",
                                "source_rel_path": "folder-b",
                                "output_rel_path": "folder-b",
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            pipeline.write_patched_notes(notes_dir=notes_dir, paths=paths)

            self.assertEqual(
                (paths.root / "folder-a" / "patched_notes" / "full.md").read_text(encoding="utf-8"),
                "# Queueing\n\nPatched queueing.\n",
            )
            self.assertEqual(
                (paths.root / "folder-b" / "patched_notes" / "full.md").read_text(encoding="utf-8"),
                "# Inventory\n\nPatched inventory.\n",
            )

    def test_write_verify_rejects_incomplete_batch_manifest_before_global_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name in ("folder-a", "folder-b"):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text(f"# {folder_name}\n\nOriginal text.\n", encoding="utf-8")

            client = FakeLLMClient([])
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root / "out")
            (paths.root / "folder-a" / "patched_notes").mkdir(parents=True, exist_ok=True)
            (paths.root / "folder-a" / "patched_notes" / "full.md").write_text("# folder-a\n\nPatched.\n", encoding="utf-8")
            (paths.root / "folder-a" / "reports").mkdir(parents=True, exist_ok=True)
            (paths.root / "folder-a" / "reports" / "REVIEW.md").write_text("# Review A\n", encoding="utf-8")
            (paths.root / "batch_manifest.json").write_text(
                json.dumps(
                    {
                        "folders": [
                            {
                                "folder_id": "folder-a",
                                "source_rel_path": "folder-a",
                                "output_rel_path": "folder-a",
                            },
                            {
                                "folder_id": "folder-b",
                                "source_rel_path": "folder-b",
                                "output_rel_path": "folder-b",
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "folder-b"):
                pipeline.write_verify(notes_dir=notes_dir, paths=paths)

    def test_write_verify_writes_one_root_report_for_batch_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name, heading in (("folder-a", "Queueing"), ("folder-b", "Inventory")):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text(f"# {heading}\n\nOriginal text.\n", encoding="utf-8")

            client = FakeLLMClient(["# Verify\n\n## Overall Verdict\n\nPass.\n"])
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root / "out")
            for folder_name, heading in (("folder-a", "Queueing"), ("folder-b", "Inventory")):
                (paths.root / folder_name / "reports").mkdir(parents=True, exist_ok=True)
                (paths.root / folder_name / "reports" / "REVIEW.md").write_text(f"# Review {heading}\n", encoding="utf-8")
                (paths.root / folder_name / "patched_notes").mkdir(parents=True, exist_ok=True)
                (paths.root / folder_name / "patched_notes" / "full.md").write_text(
                    f"# {heading}\n\nPatched text.\n",
                    encoding="utf-8",
                )
            (paths.root / "batch_manifest.json").write_text(
                json.dumps(
                    {
                        "folders": [
                            {
                                "folder_id": "folder-a",
                                "source_rel_path": "folder-a",
                                "output_rel_path": "folder-a",
                            },
                            {
                                "folder_id": "folder-b",
                                "source_rel_path": "folder-b",
                                "output_rel_path": "folder-b",
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            target = pipeline.write_verify(notes_dir=notes_dir, paths=paths)

            self.assertEqual(target, paths.reports_dir / "VERIFY.md")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Verify\n\n## Overall Verdict\n\nPass.\n")
            self.assertFalse((paths.root / "folder-a" / "reports" / "VERIFY.md").exists())
            self.assertFalse((paths.root / "folder-b" / "reports" / "VERIFY.md").exists())

    def test_write_synthesis_writes_one_root_report_for_batch_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            for folder_name, heading in (("folder-a", "Queueing"), ("folder-b", "Inventory")):
                folder = notes_dir / folder_name
                folder.mkdir(parents=True)
                (folder / "full.md").write_text(f"# {heading}\n\nOriginal text.\n", encoding="utf-8")

            client = FakeLLMClient(
                [
                    json.dumps(
                        {
                            "synthesis_markdown": "# Synthesis\n\nMerged batch note.",
                            "concept_map": {"concepts": [], "relationships": []},
                        }
                    )
                ]
            )
            pipeline = ReviewPipeline(client)
            paths = PipelinePaths.for_root(root / "out")
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "VERIFY.md").write_text("# Verify\n\nPass.\n", encoding="utf-8")
            for folder_name, heading in (("folder-a", "Queueing"), ("folder-b", "Inventory")):
                (paths.root / folder_name / "reports").mkdir(parents=True, exist_ok=True)
                (paths.root / folder_name / "reports" / "REVIEW.md").write_text(f"# Review {heading}\n", encoding="utf-8")
                (paths.root / folder_name / "patched_notes").mkdir(parents=True, exist_ok=True)
                (paths.root / folder_name / "patched_notes" / "full.md").write_text(
                    f"# {heading}\n\nPatched text.\n",
                    encoding="utf-8",
                )
            (paths.root / "batch_manifest.json").write_text(
                json.dumps(
                    {
                        "folders": [
                            {
                                "folder_id": "folder-a",
                                "source_rel_path": "folder-a",
                                "output_rel_path": "folder-a",
                            },
                            {
                                "folder_id": "folder-b",
                                "source_rel_path": "folder-b",
                                "output_rel_path": "folder-b",
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            target = pipeline.write_synthesis(notes_dir=notes_dir, paths=paths)

            self.assertEqual(target, paths.reports_dir / "SYNTHESIS.md")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Synthesis\n\nMerged batch note.\n")
            self.assertFalse((paths.root / "folder-a" / "reports" / "SYNTHESIS.md").exists())
            self.assertFalse((paths.root / "folder-b" / "reports" / "SYNTHESIS.md").exists())


if __name__ == "__main__":
    unittest.main()
