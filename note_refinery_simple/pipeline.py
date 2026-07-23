from __future__ import annotations

import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Callable, Literal, Protocol

from note_refinery_simple.llm import extract_json_object_text
from note_refinery_simple.prompts import PromptSet, render_prompt_template

PatchMode = Literal["clean-teaching", "conservative"]


class LLMClient(Protocol):
    def run_agent(self, agent_name: str, prompt: str) -> str: ...


class ImageEnricher(Protocol):
    def describe_image(self, *, image_path: Path, markdown_file: str, nearby_heading: str | None) -> dict[str, object]: ...


ProgressCallback = Callable[[str], None]

IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
HEADER_FOOTER_PATTERN = re.compile(
    r"^(OTTO VON GUERICKE\s+Production Planning and Scheduling|Production Planning and Scheduling)$",
    re.IGNORECASE,
)
STANDALONE_NOISE_PATTERN = re.compile(r"^(Inventory|Formulary)$", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[A-Za-z]{3,}")
TOPIC_STOPWORDS = {
    "full",
    "note",
    "notes",
    "lecture",
    "lectures",
    "chapter",
    "section",
    "page",
    "pages",
    "pdf",
    "production",
    "planning",
    "scheduling",
    "guericke",
    "von",
}
DEFAULT_PATCH_CONCURRENCY = 3
DEFAULT_REVIEW_FOLDER_CONCURRENCY = 1
MAX_PATCH_ATTEMPTS_PER_FILE = 3
MAX_VERIFY_REPAIR_ROUNDS = 2
BATCH_MANIFEST_FILE_NAME = "batch_manifest.json"
SOURCE_EXTENSIONS = {".md", ".py", ".ipynb"}
IGNORED_SOURCE_DIR_NAMES = {".git", ".ipynb_checkpoints", ".venv", "__pycache__"}


@dataclass(frozen=True)
class ImageTask:
    markdown_file: str
    image_markdown_path: str
    image_path: Path
    nearby_heading: str | None


@dataclass(frozen=True)
class PipelinePaths:
    root: Path
    reports_dir: Path
    patched_notes_dir: Path

    @classmethod
    def for_root(cls, root: Path) -> "PipelinePaths":
        return cls(
            root=root,
            reports_dir=root / "reports",
            patched_notes_dir=root / "patched_notes",
        )

    def ensure(self) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.patched_notes_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SynthesisPayload:
    synthesis_markdown: str
    concept_map: dict[str, object]

@dataclass(frozen=True)
class BatchFolder:
    folder_id: str
    source_rel_path: str
    output_rel_path: str


class ReviewPipeline:
    def __init__(
        self,
        client: LLMClient,
        image_enricher: ImageEnricher | None = None,
        patch_mode: PatchMode = "clean-teaching",
        patch_concurrency: int = DEFAULT_PATCH_CONCURRENCY,
        review_folder_concurrency: int = DEFAULT_REVIEW_FOLDER_CONCURRENCY,
        progress_callback: ProgressCallback | None = None,
        prompt_set: PromptSet | None = None,
    ) -> None:
        self._client = client
        self._image_enricher = image_enricher
        self._patch_mode = patch_mode
        self._patch_concurrency = max(1, patch_concurrency)
        self._review_folder_concurrency = max(1, review_folder_concurrency)
        self._progress_callback = progress_callback
        self._prompt_set = prompt_set

    def run(
        self,
        notes_dir: Path,
        paths: PipelinePaths,
        reuse_review_markdown: str | None = None,
        cached_image_contexts: list[dict[str, object]] | None = None,
    ) -> None:
        review_note_dirs = collect_review_note_dirs(notes_dir)
        is_batch_run = len(review_note_dirs) > 1 or review_note_dirs[0] != notes_dir
        if reuse_review_markdown is not None:
            paths.ensure()
            (paths.reports_dir / "REVIEW.md").write_text(
                ensure_trailing_newline(reuse_review_markdown),
                encoding="utf-8",
            )
            if cached_image_contexts is not None:
                write_json_file_atomic(paths.reports_dir / "image_context.json", cached_image_contexts)
            self._report_progress("review: reused cached REVIEW.md")
        else:
            self.write_review(
                notes_dir=notes_dir,
                paths=paths,
                cached_image_contexts=cached_image_contexts,
            )
        self.write_patched_notes(notes_dir=notes_dir, paths=paths)
        verify_path = self.write_verify(notes_dir=notes_dir, paths=paths)
        if not is_batch_run:
            note_names = set(read_notes(notes_dir))
            repair_round = 0
            flagged_files = extract_flagged_files_from_verify(verify_path.read_text(encoding="utf-8"), note_names)
            while flagged_files and repair_round < MAX_VERIFY_REPAIR_ROUNDS:
                repair_round += 1
                self._report_progress(f"patch: repairing {len(flagged_files)} flagged file(s) after verify")
                self.write_patched_notes(notes_dir=notes_dir, paths=paths, selected_note_names=flagged_files)
                verify_path = self.write_verify(notes_dir=notes_dir, paths=paths)
                flagged_files = extract_flagged_files_from_verify(verify_path.read_text(encoding="utf-8"), note_names)
        self.write_synthesis(notes_dir=notes_dir, paths=paths)

    def write_review(
        self,
        notes_dir: Path,
        paths: PipelinePaths,
        cached_image_contexts: list[dict[str, object]] | None = None,
    ) -> Path:
        review_note_dirs = collect_review_note_dirs(notes_dir)
        if len(review_note_dirs) == 1 and review_note_dirs[0] == notes_dir:
            return self._write_review_single(
                notes_dir=notes_dir,
                paths=paths,
                cached_image_contexts=cached_image_contexts,
                progress_callback=self._progress_callback,
            )
        if cached_image_contexts is not None:
            raise ValueError("Batch folder review does not accept a shared cached image context artifact")
        max_workers = min(self._review_folder_concurrency, len(review_note_dirs))
        write_batch_manifest(paths.root, notes_dir, review_note_dirs)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            total = len(review_note_dirs)
            for index, review_dir in enumerate(review_note_dirs, start=1):
                folder_label = str(review_dir.relative_to(notes_dir)).replace("\\", "/")
                self._report_progress(f"review [{index}/{total} {short_scope_label(folder_label)}] start")
                futures.append(
                    executor.submit(
                        self._write_review_single,
                        review_dir,
                        PipelinePaths.for_root(paths.root / folder_label),
                        None,
                        self._folder_progress_callback(folder_label),
                    )
                )
            for future in as_completed(futures):
                future.result()
        return paths.root

    def _write_review_single(
        self,
        notes_dir: Path,
        paths: PipelinePaths,
        cached_image_contexts: list[dict[str, object]] | None,
        progress_callback: ProgressCallback | None,
    ) -> Path:
        paths.ensure()
        notes = read_notes(notes_dir)
        if progress_callback is not None:
            progress_callback(f"review: loaded {len(notes)} source file(s)")
        if cached_image_contexts is None:
            image_contexts = build_image_contexts(
                notes_dir=notes_dir,
                image_enricher=self._image_enricher,
                progress_callback=progress_callback,
                image_context_path=paths.reports_dir / "image_context.json",
            )
        else:
            image_contexts = build_image_contexts(
                notes_dir=notes_dir,
                image_enricher=self._image_enricher,
                progress_callback=progress_callback,
                image_context_path=paths.reports_dir / "image_context.json",
                cached_contexts=cached_image_contexts,
            )
        if image_contexts or cached_image_contexts is not None:
            write_json_file_atomic(paths.reports_dir / "image_context.json", image_contexts)
        prompt = build_review_prompt(
            notes,
            image_contexts=image_contexts,
            template=None if self._prompt_set is None else self._prompt_set.review_prompt,
        )
        if progress_callback is not None:
            progress_callback("review: send reviewer")
        content = self._client.run_agent("reviewer", prompt)
        target = paths.reports_dir / "REVIEW.md"
        target.write_text(ensure_trailing_newline(content), encoding="utf-8")
        if progress_callback is not None:
            progress_callback("review: done")
        return target

    def write_patched_notes(
        self,
        notes_dir: Path,
        paths: PipelinePaths,
        selected_note_names: set[str] | None = None,
    ) -> None:
        batch_folders = resolve_batch_folders(notes_dir, paths.root)
        if batch_folders is not None:
            total = len(batch_folders)
            for index, (_, source_dir, folder_paths) in enumerate(batch_folders, start=1):
                folder_label = str(source_dir.relative_to(notes_dir)).replace("\\", "/")
                self._report_progress(f"patch [{index}/{total} {short_scope_label(folder_label)}] start")
                self._write_patched_notes_single(
                    notes_dir=source_dir,
                    paths=folder_paths,
                    selected_note_names=selected_note_names,
                )
            return
        self._write_patched_notes_single(
            notes_dir=notes_dir,
            paths=paths,
            selected_note_names=selected_note_names,
        )

    def _write_patched_notes_single(
        self,
        notes_dir: Path,
        paths: PipelinePaths,
        selected_note_names: set[str] | None = None,
    ) -> None:
        paths.ensure()
        notes = read_notes(notes_dir)
        if selected_note_names is not None:
            notes = {name: content for name, content in notes.items() if name in selected_note_names}
        self._report_progress(f"patch: loaded {len(notes)} source file(s)")
        if not notes:
            return
        review_markdown = (paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8")
        image_contexts = load_image_contexts(paths.reports_dir / "image_context.json")
        patched_notes = self._patch_notes(notes, review_markdown, image_contexts)
        for note_name, patched_content in patched_notes.items():
            target = paths.patched_notes_dir / note_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(ensure_trailing_newline(clean_patched_markdown(patched_content)), encoding="utf-8")
        self._report_progress(f"patch: wrote {len(notes)} patched file(s)")

    def _patch_notes(
        self,
        notes: dict[str, str],
        review_markdown: str,
        image_contexts: list[dict[str, object]],
    ) -> dict[str, str]:
        patched_notes: dict[str, str] = {}
        max_workers = min(self._patch_concurrency, len(notes))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            total = len(notes)
            for index, (note_name, note_content) in enumerate(notes.items(), start=1):
                self._report_progress(f"patch: file {index}/{total} [{note_name}]")
                futures[
                    executor.submit(
                        self._patch_one_note_with_retries,
                        note_name,
                        note_content,
                        review_markdown,
                        filter_image_contexts(image_contexts, note_name),
                    )
                ] = note_name
            for future in as_completed(futures):
                note_name = futures[future]
                patched_notes[note_name] = future.result()
        return patched_notes

    def _patch_one_note_with_retries(
        self,
        note_name: str,
        note_content: str,
        review_markdown: str,
        image_contexts: list[dict[str, object]],
    ) -> str:
        for attempt in range(1, MAX_PATCH_ATTEMPTS_PER_FILE + 1):
            if attempt > 1:
                self._report_progress(f"patch: retry {attempt}/{MAX_PATCH_ATTEMPTS_PER_FILE} -> {note_name}")
            prompt = build_patch_prompt(
                notes={note_name: note_content},
                review_markdown=review_markdown,
                image_contexts=image_contexts,
                patch_mode=self._patch_mode,
                template=None if self._prompt_set is None else self._prompt_set.patch_prompt,
            )
            payload = self._parse_or_repair_patch_payload(self._client.run_agent("patcher", prompt))
            patched_payload = remap_single_file_payload(note_name, payload)
            patched_content = patched_payload.get(note_name)
            if patched_content is None:
                continue
            if not topic_guard_passes(note_name, note_content, patched_content):
                self._report_progress(f"patch: topic guard failed -> {note_name}")
                continue
            return patched_content
        raise ValueError(f"Missing patched content for {note_name}")

    def _parse_or_repair_patch_payload(self, content: str) -> dict[str, str]:
        try:
            return parse_patch_payload(content)
        except (JSONDecodeError, ValueError):
            repair_prompt = build_patch_repair_prompt(content)
            repaired_content = self._client.run_agent("patcher", repair_prompt)
            return parse_patch_payload(repaired_content)

    def _parse_or_repair_synthesis_payload(self, content: str) -> SynthesisPayload:
        try:
            return parse_synthesis_payload(content)
        except (JSONDecodeError, ValueError):
            repair_prompt = build_synthesis_repair_prompt(content)
            repaired_content = self._client.run_agent("synthesizer", repair_prompt)
            return parse_synthesis_payload(repaired_content)

    def write_verify(self, notes_dir: Path, paths: PipelinePaths) -> Path:
        batch_folders = resolve_batch_folders(notes_dir, paths.root)
        if batch_folders is not None:
            return self._write_verify_batch(paths=paths, batch_folders=batch_folders)
        return self._write_verify_single(notes_dir=notes_dir, paths=paths)

    def _write_verify_single(self, notes_dir: Path, paths: PipelinePaths) -> Path:
        paths.ensure()
        prompt = build_verify_prompt(
            original_notes=read_notes(notes_dir),
            patched_notes=read_notes(paths.patched_notes_dir),
            review_markdown=(paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"),
            image_contexts=load_image_contexts(paths.reports_dir / "image_context.json"),
            template=None if self._prompt_set is None else self._prompt_set.verify_prompt,
        )
        self._report_progress("verify: sending notes to verifier")
        content = self._client.run_agent("verifier", prompt)
        target = paths.reports_dir / "VERIFY.md"
        target.write_text(ensure_trailing_newline(content), encoding="utf-8")
        self._report_progress("verify: done")
        return target

    def write_synthesis(self, notes_dir: Path, paths: PipelinePaths) -> Path:
        batch_folders = resolve_batch_folders(notes_dir, paths.root)
        if batch_folders is not None:
            return self._write_synthesis_batch(paths=paths, batch_folders=batch_folders)
        return self._write_synthesis_single(notes_dir=notes_dir, paths=paths)

    def _write_synthesis_single(self, notes_dir: Path, paths: PipelinePaths) -> Path:
        paths.ensure()
        patched_notes = read_notes(paths.patched_notes_dir)
        self._report_progress(f"synthesize: loaded {len(patched_notes)} patched markdown file(s)")
        prompt = build_synthesis_prompt(
            patched_notes=patched_notes,
            review_markdown=(paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"),
            verify_markdown=(paths.reports_dir / "VERIFY.md").read_text(encoding="utf-8"),
            template=None if self._prompt_set is None else self._prompt_set.synthesize_prompt,
        )
        self._report_progress("synthesize: sending patched notes to synthesizer")
        payload = self._parse_or_repair_synthesis_payload(self._client.run_agent("synthesizer", prompt))
        target = paths.reports_dir / "SYNTHESIS.md"
        target.write_text(ensure_trailing_newline(payload.synthesis_markdown), encoding="utf-8")
        write_json_file_atomic(paths.reports_dir / "concept_map.json", payload.concept_map)
        self._report_progress("synthesize: done")
        return target

    def _write_verify_batch(
        self,
        paths: PipelinePaths,
        batch_folders: list[tuple[BatchFolder, Path, PipelinePaths]],
    ) -> Path:
        paths.ensure()
        ensure_batch_patched_notes_ready(batch_folders)
        prompt = build_verify_prompt(
            original_notes=aggregate_batch_notes(batch_folders, use_patched_notes=False),
            patched_notes=aggregate_batch_notes(batch_folders, use_patched_notes=True),
            review_markdown=aggregate_batch_reviews(batch_folders),
            image_contexts=aggregate_batch_image_contexts(batch_folders),
            template=None if self._prompt_set is None else self._prompt_set.verify_prompt,
        )
        self._report_progress("verify: sending notes to verifier")
        content = self._client.run_agent("verifier", prompt)
        target = paths.reports_dir / "VERIFY.md"
        target.write_text(ensure_trailing_newline(content), encoding="utf-8")
        self._report_progress("verify: done")
        return target

    def _write_synthesis_batch(
        self,
        paths: PipelinePaths,
        batch_folders: list[tuple[BatchFolder, Path, PipelinePaths]],
    ) -> Path:
        paths.ensure()
        ensure_batch_patched_notes_ready(batch_folders)
        patched_notes = aggregate_batch_notes(batch_folders, use_patched_notes=True)
        self._report_progress(f"synthesize: loaded {len(patched_notes)} patched markdown file(s)")
        prompt = build_synthesis_prompt(
            patched_notes=patched_notes,
            review_markdown=aggregate_batch_reviews(batch_folders),
            verify_markdown=(paths.reports_dir / "VERIFY.md").read_text(encoding="utf-8"),
            template=None if self._prompt_set is None else self._prompt_set.synthesize_prompt,
        )
        self._report_progress("synthesize: sending patched notes to synthesizer")
        payload = self._parse_or_repair_synthesis_payload(self._client.run_agent("synthesizer", prompt))
        target = paths.reports_dir / "SYNTHESIS.md"
        target.write_text(ensure_trailing_newline(payload.synthesis_markdown), encoding="utf-8")
        write_json_file_atomic(paths.reports_dir / "concept_map.json", payload.concept_map)
        self._report_progress("synthesize: done")
        return target

    def _report_progress(self, message: str) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(message)

    def _folder_progress_callback(self, folder_label: str) -> ProgressCallback | None:
        callback = self._progress_callback
        if callback is None:
            return None
        short_label = short_scope_label(folder_label)
        return lambda message: callback(scope_progress_message(message, short_label))


def collect_review_note_dirs(notes_dir: Path) -> list[Path]:
    direct_source_files = list(iter_direct_source_files(notes_dir))
    review_dirs = [
        path
        for path in sorted(notes_dir.iterdir())
        if path.is_dir() and path.name not in IGNORED_SOURCE_DIR_NAMES and has_markdown_files(path)
    ]
    if direct_source_files and review_dirs:
        raise ValueError(f"Found mixed root and child source layout in {notes_dir}")
    if direct_source_files:
        return [notes_dir]
    return review_dirs or [notes_dir]

def iter_direct_source_files(notes_dir: Path) -> list[Path]:
    if not notes_dir.exists():
        return []
    return [path for path in sorted(notes_dir.iterdir()) if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS]

def iter_source_files(notes_dir: Path) -> list[Path]:
    if not notes_dir.exists():
        return []
    source_files: list[Path] = []
    for path in sorted(notes_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        relative_parts = path.relative_to(notes_dir).parts[:-1]
        if any(part in IGNORED_SOURCE_DIR_NAMES for part in relative_parts):
            continue
        source_files.append(path)
    return source_files

def write_batch_manifest(root: Path, notes_dir: Path, review_note_dirs: list[Path]) -> None:
    write_json_file_atomic(
        root / BATCH_MANIFEST_FILE_NAME,
        {
            "folders": [
                {
                    "folder_id": str(review_dir.relative_to(notes_dir)).replace("\\", "/"),
                    "source_rel_path": str(review_dir.relative_to(notes_dir)).replace("\\", "/"),
                    "output_rel_path": str(review_dir.relative_to(notes_dir)).replace("\\", "/"),
                }
                for review_dir in review_note_dirs
            ]
        },
    )

def load_batch_manifest(root: Path) -> list[BatchFolder] | None:
    path = root / BATCH_MANIFEST_FILE_NAME
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    folders = payload.get("folders")
    if not isinstance(folders, list):
        raise ValueError("batch_manifest.json must contain a 'folders' list")
    entries: list[BatchFolder] = []
    for item in folders:
        if not isinstance(item, dict):
            raise ValueError("batch_manifest.json folders must be objects")
        folder_id = item.get("folder_id")
        source_rel_path = item.get("source_rel_path")
        output_rel_path = item.get("output_rel_path")
        if not all(isinstance(value, str) and value for value in (folder_id, source_rel_path, output_rel_path)):
            raise ValueError("batch_manifest.json folder entries must include non-empty folder_id, source_rel_path, and output_rel_path")
        assert isinstance(folder_id, str)
        assert isinstance(source_rel_path, str)
        assert isinstance(output_rel_path, str)
        entries.append(
            BatchFolder(
                folder_id=folder_id,
                source_rel_path=source_rel_path,
                output_rel_path=output_rel_path,
            )
        )
    return entries

def resolve_batch_folders(notes_dir: Path, output_root: Path) -> list[tuple[BatchFolder, Path, PipelinePaths]] | None:
    manifest = load_batch_manifest(output_root)
    if manifest is None:
        return None
    return [
        (
            entry,
            notes_dir / Path(entry.source_rel_path),
            PipelinePaths.for_root(output_root / Path(entry.output_rel_path)),
        )
        for entry in manifest
    ]

def short_scope_label(label: str) -> str:
    scope = label.replace("\\", "/").split("/")[-1]
    scope = re.sub(r"\.pdf-[0-9a-f-]+$", "", scope, flags=re.IGNORECASE)
    return scope

def scope_progress_message(message: str, scope_label: str) -> str:
    if ": " not in message:
        return f"{message} [{scope_label}]"
    stage, detail = message.split(": ", 1)
    return f"{stage} [{scope_label}] {detail}"

def read_notes(notes_dir: Path) -> dict[str, str]:
    if not notes_dir.exists():
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")
    notes = {
        source_logical_name(path, notes_dir): read_source_file_as_markdown(path)
        for path in iter_source_files(notes_dir)
    }
    if not notes:
        raise ValueError(f"No supported source files found in {notes_dir}")
    return notes

def has_markdown_files(notes_dir: Path) -> bool:
    return bool(iter_source_files(notes_dir))

def source_logical_name(path: Path, notes_dir: Path) -> str:
    relative_path = str(path.relative_to(notes_dir)).replace("\\", "/")
    if path.suffix.lower() == ".md":
        return relative_path
    return f"{relative_path}.md"

def read_source_file_as_markdown(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return path.read_text(encoding="utf-8")
    if suffix == ".py":
        return render_python_source_as_markdown(path)
    if suffix == ".ipynb":
        return render_notebook_source_as_markdown(path)
    raise ValueError(f"Unsupported source file: {path}")

def render_python_source_as_markdown(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    return f"# {path.name}\n\n```python\n{source.rstrip()}\n```\n"

def render_notebook_source_as_markdown(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = payload.get("cells", [])
    if not isinstance(cells, list):
        raise ValueError(f"Notebook cells must be a list: {path}")
    blocks: list[str] = [f"# {path.name}"]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        cell_type = cell.get("cell_type")
        source = join_text_lines(cell.get("source"))
        if cell_type == "markdown":
            if source.strip():
                blocks.append(source.rstrip())
            continue
        if cell_type != "code":
            continue
        blocks.append(render_fenced_block("python", source))
        for output_text in iter_notebook_output_texts(cell.get("outputs")):
            blocks.append(render_fenced_block("text", output_text))
    return ensure_trailing_newline("\n\n".join(blocks).strip())

def iter_notebook_output_texts(outputs: object) -> list[str]:
    if not isinstance(outputs, list):
        return []
    collected: list[str] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        output_type = output.get("output_type")
        if output_type == "stream":
            text = join_text_lines(output.get("text")).rstrip()
            if text:
                collected.append(text)
            continue
        if output_type in {"execute_result", "display_data"}:
            text = extract_notebook_text_plain(output.get("data")).rstrip()
            if text:
                collected.append(text)
            continue
        if output_type == "error":
            text = join_text_lines(output.get("traceback")).rstrip()
            if text:
                collected.append(text)
    return collected

def extract_notebook_text_plain(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    return join_text_lines(data.get("text/plain"))

def join_text_lines(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item for item in value if isinstance(item, str))
    return ""

def render_fenced_block(language: str, content: str) -> str:
    fence = "```"
    if "```" in content:
        fence = "````"
    return f"{fence}{language}\n{content.rstrip()}\n{fence}"


def ensure_trailing_newline(content: str) -> str:
    return content.rstrip() + "\n"


def write_json_file_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def image_context_key(markdown_file: object, image_path: object) -> tuple[str, str] | None:
    if not isinstance(markdown_file, str) or not isinstance(image_path, str):
        return None
    return markdown_file, image_path


def parse_patch_payload(content: str) -> dict[str, str]:
    payload = json.loads(extract_first_json_object(content))
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("Patcher must return JSON object with top-level 'files' mapping")
    return {str(name): str(text) for name, text in files.items()}


def remap_single_file_payload(requested_note_name: str, payload: dict[str, str]) -> dict[str, str]:
    if requested_note_name in payload or len(payload) != 1:
        return payload
    only_content = next(iter(payload.values()))
    return {requested_note_name: only_content}


def parse_synthesis_payload(content: str) -> SynthesisPayload:
    payload = json.loads(extract_first_json_object(content))
    synthesis_markdown = payload.get("synthesis_markdown")
    concept_map = payload.get("concept_map")
    if not isinstance(synthesis_markdown, str):
        raise ValueError("Synthesizer must return string field 'synthesis_markdown'")
    if not isinstance(concept_map, dict):
        raise ValueError("Synthesizer must return object field 'concept_map'")
    return SynthesisPayload(synthesis_markdown=synthesis_markdown, concept_map=concept_map)

def ensure_batch_patched_notes_ready(batch_folders: list[tuple[BatchFolder, Path, PipelinePaths]]) -> None:
    missing = [
        folder.folder_id
        for folder, _, folder_paths in batch_folders
        if not has_markdown_files(folder_paths.patched_notes_dir)
    ]
    if missing:
        raise ValueError(f"Missing patched content for folder(s): {', '.join(missing)}")

def prefix_note_names(notes: dict[str, str], prefix: str) -> dict[str, str]:
    return {f"{prefix}/{name}": content for name, content in notes.items()}

def aggregate_batch_notes(
    batch_folders: list[tuple[BatchFolder, Path, PipelinePaths]],
    *,
    use_patched_notes: bool,
) -> dict[str, str]:
    aggregated: dict[str, str] = {}
    for folder, source_dir, folder_paths in batch_folders:
        note_root = folder_paths.patched_notes_dir if use_patched_notes else source_dir
        aggregated.update(prefix_note_names(read_notes(note_root), folder.source_rel_path))
    return aggregated

def aggregate_batch_reviews(batch_folders: list[tuple[BatchFolder, Path, PipelinePaths]]) -> str:
    sections = []
    for folder, _, folder_paths in batch_folders:
        sections.append(
            f"## {folder.folder_id}\n\n"
            f"{(folder_paths.reports_dir / 'REVIEW.md').read_text(encoding='utf-8').strip()}"
        )
    return "\n\n".join(sections)

def aggregate_batch_image_contexts(
    batch_folders: list[tuple[BatchFolder, Path, PipelinePaths]],
) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    for folder, _, folder_paths in batch_folders:
        for context in load_image_contexts(folder_paths.reports_dir / "image_context.json"):
            prefixed = dict(context)
            markdown_file = prefixed.get("markdown_file")
            if isinstance(markdown_file, str):
                prefixed["markdown_file"] = f"{folder.source_rel_path}/{markdown_file}"
            contexts.append(prefixed)
    return contexts


def build_review_prompt(
    notes: dict[str, str],
    image_contexts: list[dict[str, object]] | None = None,
    template: str | None = None,
) -> str:
    image_context_block = render_image_contexts(image_contexts or [])
    if template is not None:
        return render_prompt_template(
            template,
            {
                "notes_block": render_notes(notes),
                "image_context_block": image_context_block,
            },
        )
    return (
        "You are reviewer agent for lecture source files.\n"
        "Find incorrect formulas, missing assumptions, inconsistent notation, contradictions, and unclear statements.\n"
        "Also check cross-file consistency.\n"
        "Find symbols defined differently across files, contradictory assumptions across files, formulas that conflict between files, and terminology drift between files.\n"
        "Use image context when available to interpret charts, diagrams, and drawings that OCR may miss.\n"
        "Do not patch files. Output Markdown for REVIEW.md.\n"
        "When issue spans multiple files, set Type to Cross-file inconsistency and name every affected file.\n"
        "For each finding, include: File, Type, Severity, Confidence, Snippet, Problem, Recommendation.\n\n"
        f"NOTES\n{render_notes(notes)}{image_context_block}"
    )


def build_patch_prompt(
    notes: dict[str, str],
    review_markdown: str,
    image_contexts: list[dict[str, object]] | None = None,
    patch_mode: PatchMode = "clean-teaching",
    template: str | None = None,
) -> str:
    image_context_block = render_patch_image_contexts(image_contexts or [])
    instruction_block = build_patch_mode_instructions(patch_mode)
    if template is not None:
        return render_prompt_template(
            template,
            {
                "review_markdown": review_markdown,
                "notes_block": render_notes(notes),
                "patch_mode_instructions": instruction_block,
                "image_context_block": image_context_block,
            },
        )
    return (
        "You are patcher agent for lecture source files.\n"
        "Use REVIEW.md findings to create corrected versions of every note.\n"
        "Use patch image context only as supporting evidence for chart or diagram meaning.\n"
        "Do not omit files.\n"
        f"{instruction_block}"
        "If uncertain, prefer conservative clarification over confident invention.\n"
        "Return JSON only with shape: {\"files\": {\"relative/path.md\": \"full patched content\"}}.\n\n"
        f"REVIEW_MD\n{review_markdown}\n\n"
        f"ORIGINAL_NOTES\n{render_notes(notes)}{image_context_block}"
    )


def build_verify_prompt(
    original_notes: dict[str, str],
    patched_notes: dict[str, str],
    review_markdown: str,
    image_contexts: list[dict[str, object]] | None = None,
    template: str | None = None,
) -> str:
    image_context_block = render_image_contexts(image_contexts or [])
    if template is not None:
        return render_prompt_template(
            template,
            {
                "review_markdown": review_markdown,
                "original_notes_block": render_notes(original_notes),
                "patched_notes_block": render_notes(patched_notes),
                "image_context_block": image_context_block,
            },
        )
    return (
        "You are verifier agent for lecture source files.\n"
        "Check whether patched notes resolve REVIEW.md findings without adding obvious new contradictions.\n"
        "Include cross-file consistency in your checks when multiple files are present.\n"
        "Use image context when available to check whether chart or diagram meaning still matches the patched notes.\n"
        "If patched notes do not reconcile source-code bookkeeping or index-shift logic into one explicit mapping example with one concrete numeric example, leave bookkeeping or indexing findings unresolved.\n"
        "If a note mixes original and corrected code semantics in one example without explicit labels, keep that finding unresolved.\n"
        "Output Markdown for VERIFY.md with sections: Verified Resolved, Not Resolved, Possible Regressions, Overall Verdict.\n\n"
        f"REVIEW_MD\n{review_markdown}\n\n"
        f"ORIGINAL_NOTES\n{render_notes(original_notes)}\n\n"
        f"PATCHED_NOTES\n{render_notes(patched_notes)}{image_context_block}"
    )


def build_synthesis_prompt(
    patched_notes: dict[str, str],
    review_markdown: str,
    verify_markdown: str,
    template: str | None = None,
) -> str:
    if template is not None:
        return render_prompt_template(
            template,
            {
                "review_markdown": review_markdown,
                "verify_markdown": verify_markdown,
                "patched_notes_block": render_notes(patched_notes),
            },
        )
    return (
        "You are synthesizer agent for patched lecture source notes.\n"
        "Create one structured, interconnected teaching note across all patched sources.\n"
        "Make cross-source relationships explicit. Identify prerequisite chains, concept dependencies, consistent definitions, and remaining tensions.\n"
        "Prefer compact teaching language over verbose summaries.\n"
        "Ground every concept and relationship in the provided patched notes.\n"
        "Return JSON only with shape: {\"synthesis_markdown\": \"full markdown\", \"concept_map\": { ... }}.\n"
        "The concept_map must include top-level arrays named concepts and relationships.\n"
        "Each concept should include: name, sources, prerequisites.\n"
        "Each relationship should include: from, to, type, evidence.\n"
        "In synthesis_markdown, include sections: Concept Index, Unified Definitions, Cross-Source Relationships, Key Formulas With Assumptions, Minimal Study Path.\n\n"
        f"REVIEW_MD\n{review_markdown}\n\n"
        f"VERIFY_MD\n{verify_markdown}\n\n"
        f"PATCHED_NOTES\n{render_notes(patched_notes)}"
    )


def render_notes(notes: dict[str, str]) -> str:
    blocks = []
    for name, content in notes.items():
        blocks.append(f"<<<FILE:{name}>>>\n{content}\n<<<END FILE>>>")
    return "\n\n".join(blocks)


def collect_image_tasks(notes_dir: Path) -> list[ImageTask]:
    tasks: list[ImageTask] = []
    for markdown_path in sorted(notes_dir.rglob("*.md")):
        markdown_file = str(markdown_path.relative_to(notes_dir)).replace("\\", "/")
        current_heading: str | None = None
        for line in markdown_path.read_text(encoding="utf-8").splitlines():
            heading_match = HEADING_PATTERN.match(line.strip())
            if heading_match:
                current_heading = heading_match.group(2).strip()
            for match in IMAGE_PATTERN.finditer(line):
                image_markdown_path = match.group(1).strip()
                image_path = (markdown_path.parent / image_markdown_path).resolve()
                if not image_path.exists() or not image_path.is_file():
                    continue
                tasks.append(
                    ImageTask(
                        markdown_file=markdown_file,
                        image_markdown_path=image_markdown_path,
                        image_path=image_path,
                        nearby_heading=current_heading,
                    )
                )
    return tasks


def build_image_contexts(
    notes_dir: Path,
    image_enricher: ImageEnricher | None,
    progress_callback: ProgressCallback | None = None,
    image_context_path: Path | None = None,
    cached_contexts: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    tasks = collect_image_tasks(notes_dir)
    contexts: list[dict[str, object]] = []
    cached_keys: set[tuple[str, str]] = set()
    if cached_contexts is not None:
        for context in cached_contexts:
            key = image_context_key(context.get("markdown_file"), context.get("image_path"))
            if key is None or key in cached_keys:
                continue
            contexts.append(context)
            cached_keys.add(key)
        if progress_callback is not None and contexts:
            progress_callback(f"review: reused cached image context for {len(contexts)} image(s)")
        if image_context_path is not None and contexts:
            write_json_file_atomic(image_context_path, contexts)
    if image_enricher is None:
        return contexts
    if progress_callback is not None and tasks:
        progress_callback(f"review: enriching {len(tasks)} image(s)")
    for index, task in enumerate(tasks, start=1):
        if (task.markdown_file, task.image_markdown_path) in cached_keys:
            continue
        if progress_callback is not None:
            progress_callback(
                f"review: image {index}/{len(tasks)}"
            )
        try:
            payload = image_enricher.describe_image(
                image_path=task.image_path,
                markdown_file=task.markdown_file,
                nearby_heading=task.nearby_heading,
            )
            if not isinstance(payload, dict):
                raise ValueError("Image enricher must return a dictionary payload")
        except Exception as error:
            if progress_callback is not None:
                progress_callback(f"review: image {index}/{len(tasks)} failed")
            payload = {
                "detected_type": "unknown",
                "summary": "Image enrichment failed.",
                "visible_text": [],
                "chart_structure": {},
                "possible_risks": [f"Image enrichment failed: {error}"],
                "confidence": "low",
            }
        contexts.append(
            {
                **payload,
                "image_path": task.image_markdown_path,
                "markdown_file": task.markdown_file,
                "nearby_heading": task.nearby_heading,
            }
        )
        if image_context_path is not None:
            write_json_file_atomic(image_context_path, contexts)
    return contexts


def render_image_contexts(image_contexts: list[dict[str, object]]) -> str:
    if not image_contexts:
        return ""
    blocks = []
    for context in image_contexts:
        blocks.append(
            "<<<IMAGE_CONTEXT>>>\n"
            f"markdown_file: {context.get('markdown_file', '')}\n"
            f"image_path: {context.get('image_path', '')}\n"
            f"nearby_heading: {context.get('nearby_heading', '')}\n"
            f"summary: {context.get('summary', '')}\n"
            f"visible_text: {json.dumps(context.get('visible_text', []), ensure_ascii=False)}\n"
            f"chart_structure: {json.dumps(context.get('chart_structure', {}), ensure_ascii=False)}\n"
            f"possible_risks: {json.dumps(context.get('possible_risks', []), ensure_ascii=False)}\n"
            f"confidence: {context.get('confidence', '')}\n"
            "<<<END IMAGE_CONTEXT>>>"
        )
    return "\n\nIMAGE_CONTEXTS\n" + "\n\n".join(blocks)


def render_patch_image_contexts(image_contexts: list[dict[str, object]]) -> str:
    if not image_contexts:
        return ""
    blocks = []
    for context in image_contexts:
        lines = [
            "<<<PATCH_IMAGE_CONTEXT>>>",
            f"markdown_file: {context.get('markdown_file', '')}",
            f"image_path: {context.get('image_path', '')}",
            f"nearby_heading: {context.get('nearby_heading', '')}",
            f"summary: {context.get('summary', '')}",
            f"confidence: {context.get('confidence', '')}",
        ]
        visible_text = context.get("visible_text", [])
        if isinstance(visible_text, list) and visible_text:
            lines.append(f"visible_text: {json.dumps(visible_text, ensure_ascii=False)}")
        lines.append("<<<END PATCH_IMAGE_CONTEXT>>>")
        blocks.append("\n".join(lines))
    return "\n\nPATCH_IMAGE_CONTEXTS\n" + "\n\n".join(blocks)


def filter_image_contexts(image_contexts: list[dict[str, object]], note_name: str) -> list[dict[str, object]]:
    return [context for context in image_contexts if context.get("markdown_file") == note_name]


def load_image_contexts(image_context_path: Path) -> list[dict[str, object]]:
    if not image_context_path.exists():
        return []
    payload = json.loads(image_context_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("image_context.json must contain a list")
    return [context for context in payload if isinstance(context, dict)]


def build_patch_repair_prompt(invalid_response: str) -> str:
    return (
        "Repair malformed patcher output into valid JSON only.\n"
        "Do not change note content beyond escaping and JSON repair.\n"
        "Return exactly one JSON object with shape: {\"files\": {\"relative/path.md\": \"full patched content\"}}.\n"
        "Do not add markdown fences, commentary, or extra keys.\n\n"
        f"MALFORMED_RESPONSE\n{invalid_response}"
    )


def build_synthesis_repair_prompt(invalid_response: str) -> str:
    return (
        "Repair malformed synthesizer output into valid JSON only.\n"
        "Do not change synthesis meaning beyond escaping and JSON repair.\n"
        "Return exactly one JSON object with shape: {\"synthesis_markdown\": \"full markdown\", \"concept_map\": {\"concepts\": [], \"relationships\": []}}.\n"
        "Do not add markdown fences, commentary, or extra keys.\n\n"
        f"MALFORMED_RESPONSE\n{invalid_response}"
    )


def build_patch_mode_instructions(patch_mode: PatchMode) -> str:
    if patch_mode == "conservative":
        return (
            "Preserve headings and teaching style where possible.\n"
            "Do not rewrite structure more than needed to fix REVIEW.md findings.\n"
            "Include short code snippets for illustration when they clarify logic.\n"
            "Keep fenced code blocks syntactically correct and preserve Python indentation inside them.\n"
            "For bookkeeping, index shifts, or RL return alignment, derive one explicit step-by-step mapping from source code with one concrete numeric example instead of vague intent language.\n"
            "If you show both original and safer variants of code, label them explicitly as original code versus corrected code, and do not merge their semantics into one snippet.\n"
            "Do not invent new algebra, new notation, or new assumptions unless REVIEW.md explicitly calls for that correction.\n"
            "When rewriting formulas, preserve formula meaning exactly and keep mathematically equivalent expressions only when you are certain.\n"
        )
    return (
        "Rewrite each file into a clean teaching note, not a line-by-line OCR preservation.\n"
        "Remove page headers, footers, branding, repeated titles, OCR garbage, and isolated labels that add no teaching value.\n"
        "Drop image markdown placeholders unless you convert image meaning into useful teaching text.\n"
        "Merge duplicate headings and restructure freely when original structure is noisy.\n"
        "Prefer compact explanations, clear derivations, and readable sectioning over preserving original layout.\n"
        "Prefer short explanatory prose and keep only equations that materially help a student learn the topic.\n"
        "Include short code snippets for illustration when they clarify logic.\n"
        "Keep fenced code blocks syntactically correct and preserve Python indentation inside them.\n"
        "For bookkeeping, index shifts, or RL return alignment, derive one explicit step-by-step mapping from source code with one concrete numeric example instead of vague intent language.\n"
        "If you show both original and safer variants of code, label them explicitly as original code versus corrected code, and do not merge their semantics into one snippet.\n"
        "Drop auxiliary derivation symbols, repeated intermediate algebra, and low-value chart narration unless they are essential for understanding.\n"
        "Do not invent new algebra, new notation, or new assumptions unless REVIEW.md explicitly calls for that correction.\n"
        "When rewriting formulas, preserve formula meaning exactly and keep mathematically equivalent expressions only when you are certain.\n"
    )


def clean_patched_markdown(content: str) -> str:
    cleaned_lines: list[str] = []
    previous_heading: str | None = None
    blank_line_count = 0
    in_fenced_code_block = False
    for raw_line in content.splitlines():
        stripped_line = raw_line.strip()
        if stripped_line.startswith("```"):
            cleaned_lines.append(stripped_line)
            previous_heading = None
            blank_line_count = 0
            in_fenced_code_block = not in_fenced_code_block
            continue
        if in_fenced_code_block:
            cleaned_lines.append(raw_line.rstrip())
            blank_line_count = 0
            continue
        line = raw_line.strip()
        if not line:
            if cleaned_lines and blank_line_count == 0:
                cleaned_lines.append("")
            blank_line_count += 1
            continue
        blank_line_count = 0
        if HEADER_FOOTER_PATTERN.match(line):
            continue
        if IMAGE_PATTERN.fullmatch(line):
            continue
        if STANDALONE_NOISE_PATTERN.match(line):
            continue
        heading_match = HEADING_PATTERN.match(line)
        if heading_match:
            normalized_heading = f"{heading_match.group(1)} {heading_match.group(2).strip()}"
            if normalized_heading == previous_heading:
                continue
            previous_heading = normalized_heading
            cleaned_lines.append(normalized_heading)
            continue
        previous_heading = None
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def topic_guard_passes(note_name: str, original_content: str, patched_content: str) -> bool:
    source_tokens = extract_topic_tokens(note_name) | extract_topic_tokens(extract_heading_and_preview(original_content))
    if not source_tokens:
        return True
    patched_tokens = extract_topic_tokens(extract_heading_and_preview(patched_content))
    return bool(source_tokens & patched_tokens)


def extract_heading_and_preview(content: str) -> str:
    lines = content.splitlines()[:20]
    return "\n".join(lines)


def extract_topic_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(text.replace("_", " ").replace("/", " "))
        if token.lower() not in TOPIC_STOPWORDS
    }


def extract_flagged_files_from_verify(verify_markdown: str, note_names: set[str]) -> set[str]:
    section_match = re.search(
        r"^## Possible Regressions\s*(.*?)(?:^## |\Z)",
        verify_markdown,
        re.MULTILINE | re.DOTALL,
    )
    if section_match is None:
        return set()
    section_text = section_match.group(1)
    return {
        match
        for match in re.findall(r"`([^`]+\.md)`", section_text)
        if match in note_names
    }


def extract_first_json_object(content: str) -> str:
    stripped = extract_json_object_text(content)
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(stripped)
    return json.dumps(payload)
