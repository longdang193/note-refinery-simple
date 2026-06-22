from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from note_refinery_simple.llm import extract_json_object_text

PatchMode = Literal["clean-teaching", "conservative"]


class LLMClient(Protocol):
    def run_agent(self, agent_name: str, prompt: str) -> str: ...


class ImageEnricher(Protocol):
    def describe_image(self, *, image_path: Path, markdown_file: str, nearby_heading: str | None) -> dict[str, object]: ...


IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
HEADER_FOOTER_PATTERN = re.compile(
    r"^(OTTO VON GUERICKE\s+Production Planning and Scheduling|Production Planning and Scheduling)$",
    re.IGNORECASE,
)
STANDALONE_NOISE_PATTERN = re.compile(r"^(Inventory|Formulary)$", re.IGNORECASE)


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


class ReviewPipeline:
    def __init__(
        self,
        client: LLMClient,
        image_enricher: ImageEnricher | None = None,
        patch_mode: PatchMode = "clean-teaching",
    ) -> None:
        self._client = client
        self._image_enricher = image_enricher
        self._patch_mode = patch_mode

    def run(self, notes_dir: Path, paths: PipelinePaths) -> None:
        self.write_review(notes_dir=notes_dir, paths=paths)
        self.write_patched_notes(notes_dir=notes_dir, paths=paths)
        self.write_verify(notes_dir=notes_dir, paths=paths)

    def write_review(self, notes_dir: Path, paths: PipelinePaths) -> Path:
        paths.ensure()
        notes = read_notes(notes_dir)
        image_contexts = build_image_contexts(notes_dir=notes_dir, image_enricher=self._image_enricher)
        if image_contexts:
            (paths.reports_dir / "image_context.json").write_text(
                json.dumps(image_contexts, indent=2) + "\n",
                encoding="utf-8",
            )
        prompt = build_review_prompt(notes, image_contexts=image_contexts)
        content = self._client.run_agent("reviewer", prompt)
        target = paths.reports_dir / "REVIEW.md"
        target.write_text(ensure_trailing_newline(content), encoding="utf-8")
        return target

    def write_patched_notes(self, notes_dir: Path, paths: PipelinePaths) -> None:
        paths.ensure()
        notes = read_notes(notes_dir)
        review = (paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8")
        image_contexts = load_image_contexts(paths.reports_dir / "image_context.json")
        payload = self._collect_patched_files(
            notes=notes,
            review_markdown=review,
            image_contexts=image_contexts,
        )
        for note_path, note_content in notes.items():
            patched_content = payload.get(note_path)
            if patched_content is None:
                raise ValueError(f"Missing patched content for {note_path}")
            target = paths.patched_notes_dir / note_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(ensure_trailing_newline(clean_patched_markdown(patched_content)), encoding="utf-8")

    def _collect_patched_files(
        self,
        notes: dict[str, str],
        review_markdown: str,
        image_contexts: list[dict[str, object]],
    ) -> dict[str, str]:
        prompt = build_patch_prompt(
            notes=notes,
            review_markdown=review_markdown,
            image_contexts=image_contexts,
            patch_mode=self._patch_mode,
        )
        payload = parse_patch_payload(self._client.run_agent("patcher", prompt))
        missing_notes = {name: content for name, content in notes.items() if name not in payload}
        if not missing_notes:
            return payload
        retry_prompt = build_missing_patch_prompt(
            missing_notes=missing_notes,
            review_markdown=review_markdown,
            image_contexts=image_contexts,
            patch_mode=self._patch_mode,
        )
        retry_payload = parse_patch_payload(self._client.run_agent("patcher", retry_prompt))
        payload.update(retry_payload)
        return payload

    def write_verify(self, notes_dir: Path, paths: PipelinePaths) -> Path:
        paths.ensure()
        prompt = build_verify_prompt(
            original_notes=read_notes(notes_dir),
            patched_notes=read_notes(paths.patched_notes_dir),
            review_markdown=(paths.reports_dir / "REVIEW.md").read_text(encoding="utf-8"),
            image_contexts=load_image_contexts(paths.reports_dir / "image_context.json"),
        )
        content = self._client.run_agent("verifier", prompt)
        target = paths.reports_dir / "VERIFY.md"
        target.write_text(ensure_trailing_newline(content), encoding="utf-8")
        return target


def read_notes(notes_dir: Path) -> dict[str, str]:
    if not notes_dir.exists():
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")
    notes = {
        str(path.relative_to(notes_dir)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in sorted(notes_dir.rglob("*.md"))
        if path.is_file()
    }
    if not notes:
        raise ValueError(f"No markdown files found in {notes_dir}")
    return notes


def ensure_trailing_newline(content: str) -> str:
    return content.rstrip() + "\n"


def parse_patch_payload(content: str) -> dict[str, str]:
    payload = json.loads(extract_first_json_object(content))
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("Patcher must return JSON object with top-level 'files' mapping")
    return {str(name): str(text) for name, text in files.items()}


def build_review_prompt(
    notes: dict[str, str],
    image_contexts: list[dict[str, object]] | None = None,
) -> str:
    image_context_block = render_image_contexts(image_contexts or [])
    return (
        "You are reviewer agent for markdown class notes.\n"
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
) -> str:
    patch_image_context_block = render_patch_image_contexts(image_contexts or [])
    instruction_block = build_patch_mode_instructions(patch_mode)
    return (
        "You are patcher agent for markdown class notes.\n"
        "Use REVIEW.md findings to create corrected versions of every note.\n"
        "Use patch image context only as supporting evidence for chart or diagram meaning.\n"
        "Do not omit files.\n"
        f"{instruction_block}"
        "If uncertain, prefer conservative clarification over confident invention.\n"
        "Return JSON only with shape: {\"files\": {\"relative/path.md\": \"full patched content\"}}.\n\n"
        f"REVIEW_MD\n{review_markdown}\n\n"
        f"ORIGINAL_NOTES\n{render_notes(notes)}{patch_image_context_block}"
    )


def build_verify_prompt(
    original_notes: dict[str, str],
    patched_notes: dict[str, str],
    review_markdown: str,
    image_contexts: list[dict[str, object]] | None = None,
) -> str:
    image_context_block = render_image_contexts(image_contexts or [])
    return (
        "You are verifier agent for markdown class notes.\n"
        "Check whether patched notes resolve REVIEW.md findings without adding obvious new contradictions.\n"
        "Include cross-file consistency in your checks when multiple files are present.\n"
        "Use image context when available to check whether chart or diagram meaning still matches the patched notes.\n"
        "Output Markdown for VERIFY.md with sections: Verified Resolved, Not Resolved, Possible Regressions, Overall Verdict.\n\n"
        f"REVIEW_MD\n{review_markdown}\n\n"
        f"ORIGINAL_NOTES\n{render_notes(original_notes)}\n\n"
        f"PATCHED_NOTES\n{render_notes(patched_notes)}{image_context_block}"
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


def build_image_contexts(notes_dir: Path, image_enricher: ImageEnricher | None) -> list[dict[str, object]]:
    if image_enricher is None:
        return []
    contexts: list[dict[str, object]] = []
    for task in collect_image_tasks(notes_dir):
        payload = image_enricher.describe_image(
            image_path=task.image_path,
            markdown_file=task.markdown_file,
            nearby_heading=task.nearby_heading,
        )
        if not isinstance(payload, dict):
            raise ValueError("Image enricher must return a dictionary payload")
        context = {
            "image_path": task.image_markdown_path,
            "markdown_file": task.markdown_file,
            "nearby_heading": task.nearby_heading,
            **payload,
        }
        contexts.append(context)
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


def load_image_contexts(image_context_path: Path) -> list[dict[str, object]]:
    if not image_context_path.exists():
        return []
    payload = json.loads(image_context_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("image_context.json must contain a list")
    return [context for context in payload if isinstance(context, dict)]


def build_missing_patch_prompt(
    missing_notes: dict[str, str],
    review_markdown: str,
    image_contexts: list[dict[str, object]] | None = None,
    patch_mode: PatchMode = "clean-teaching",
) -> str:
    return (
        build_patch_prompt(
            notes=missing_notes,
            review_markdown=review_markdown,
            image_contexts=image_contexts,
            patch_mode=patch_mode,
        )
        + "\n\nThe previous patch response omitted these missing files. Return JSON for every missing file only."
    )


def build_patch_mode_instructions(patch_mode: PatchMode) -> str:
    if patch_mode == "conservative":
        return (
            "Preserve headings and teaching style where possible.\n"
            "Do not rewrite structure more than needed to fix REVIEW.md findings.\n"
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
        "Drop auxiliary derivation symbols, repeated intermediate algebra, and low-value chart narration unless they are essential for understanding.\n"
        "Do not invent new algebra, new notation, or new assumptions unless REVIEW.md explicitly calls for that correction.\n"
        "When rewriting formulas, preserve formula meaning exactly and keep mathematically equivalent expressions only when you are certain.\n"
    )


def clean_patched_markdown(content: str) -> str:
    cleaned_lines: list[str] = []
    previous_heading: str | None = None
    blank_line_count = 0
    for raw_line in content.splitlines():
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


def extract_first_json_object(content: str) -> str:
    stripped = extract_json_object_text(content)
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(stripped)
    return json.dumps(payload)
