---
layer: change
artifact_type: spec
status: proposed
template_id: detailed-specification
name: lecture-source-input-expansion
parent_workstream: none
targets:
  - note_refinery_simple/pipeline.py
  - note_refinery_simple/cli.py
  - tests/test_pipeline.py
  - tests/test_cli.py
  - README.md
related_features: []
related_stages: []
---

# Lecture Source Input Expansion For `.md`, `.py`, And `.ipynb`

## Goal

Extend pipeline input contract from markdown-only lecture notes to lecture source files in `.md`, `.py`, and `.ipynb` while keeping output contract unchanged: pipeline still produces markdown notes plus existing report artifacts.

### Triage

```text
Layer: change
Feature type: MODIFY
Summary: Expand input discovery and read boundary so markdown, python, and notebooks can all act as lecture-source inputs for existing note-refinement pipeline.
Reasoning: Product goal is not source-to-source rewriting. Inputs are lecture artifacts. Outputs are our own markdown study notes. Smallest safe change is to normalize all supported inputs into one markdown-like internal representation before review.
Invariants:
  - outputs remain markdown reports and markdown patched notes
  - downstream pipeline stages do not branch on input source type
  - one normalization boundary owns source-type awareness
  - batch behavior stays scope-based, not extension-specific
  - existing markdown inputs keep working unchanged
Dependencies:
  - existing review -> patch -> verify -> synthesize stage flow
  - existing prompt contract based on rendered note blocks
  - existing batch manifest and per-folder processing rules
Affected stages:
  - none
Affected features:
  - none
Primary lens: cross-cutting
Affected docs:
  feature_source: none
  feature_yaml: none
  feature_lineage: none
  feature_history: none
  stage_source: none
  stage_contract: none
  feature_docs:
  cross_cutting_docs:
    - README.md
  readme: README.md
  generated:
    - none
Generated refresh required: no
Capability IDs:
  - none
Invariant IDs:
  - none
Spec needed: yes
Plan needed: yes
```

## Key Deliverables

### One expanded source discovery contract

Define one canonical supported-extension set for lecture-source inputs: `.md`, `.py`, `.ipynb`.

### One SSOT source reader contract

Define one authoritative `SOURCE_EXTENSIONS` constant and one authoritative discovery helper such as `iter_source_files()` that own supported extensions, ignore rules, and recursion semantics for single-folder mode, batch detection, and readiness checks.

### One normalization boundary

Define one read-layer normalization flow that converts every supported source file into markdown text before review.

### One downstream text contract

Keep `review`, `patch`, `verify`, and `synthesize` operating on rendered markdown text only, without source-type branching.

### One stable output contract

Keep `reports/REVIEW.md`, `reports/VERIFY.md`, `reports/SYNTHESIS.md`, `reports/concept_map.json`, and `patched_notes/*.md` as canonical outputs.

## Task/Wave Breakdown

### Wave 1: Source boundary definition

**Purpose:**
- define exactly where source-type awareness begins and ends

**Steps:**
- [ ] define supported source extensions and batch discovery rules
- [ ] define canonical source identity and output-relative naming rules
- [ ] define ignore rules for generated and non-lecture directories
- [ ] define normalized internal text shape for supported source files
- [ ] define no-branch downstream contract

**Verification:**
- [ ] design shows only discovery/read layer needs source-type logic

**Exit Criteria:**
- no downstream stage requires `.py` or `.ipynb` conditionals

### Wave 2: Normalization decisions

**Purpose:**
- define minimal, deterministic normalization for `.py` and `.ipynb`

**Steps:**
- [ ] define `.md` passthrough behavior
- [ ] define `.py` to markdown normalization
- [ ] define `.ipynb` to markdown normalization
- [ ] define notebook output subtype handling and newline joining rules
- [ ] define skipped notebook output types for first pass

**Verification:**
- [ ] normalization rules are deterministic and stdlib-only

**Exit Criteria:**
- implementation can flatten all supported inputs into one markdown-text map

### Wave 3: Validation proof shape

**Purpose:**
- define tests and docs needed before implementation planning

**Steps:**
- [ ] define mixed-extension discovery tests
- [ ] define `.py` normalization tests
- [ ] define `.ipynb` normalization tests
- [ ] define batch and naming-collision tests
- [ ] define README proof for new input contract

**Verification:**
- [ ] proof targets cover correctness, invariants, and user-facing contract

**Exit Criteria:**
- spec is ready for bounded implementation planning

## Design Decisions

### Decision: Input expansion happens only at source boundary

- context: current pipeline is markdown-only because discovery and reading only load `*.md`
- choice: source-type awareness lives only in discovery/read helpers; downstream stages receive normalized markdown text
- alternatives considered:
  - branch per source type inside each stage
  - add separate pipeline for code and notebooks
- impact:
  - shortest safe diff
  - keeps prompt contract stable
  - future input expansion adds one new normalizer, not four new stage branches

### Decision: One helper owns discovery, recursion, and ignore rules

- context: current pipeline spreads markdown assumptions across directory detection, file loading, and readiness checks
- choice: one helper such as `iter_source_files()` owns recursive discovery, supported extensions, and ignore rules; batch detection and readiness checks must call that helper rather than re-implementing extension logic
- alternatives considered:
  - duplicate extension checks in each helper
  - add extension support only to current markdown readers
- impact:
  - enforces SSOT
  - prevents drift between single-folder mode, batch mode, and readiness checks
  - keeps future source additions bounded to one place

### Decision: Internal contract stays text-first

- context: product output is markdown notes, not transformed source files
- choice: normalize every supported source into `logical_name -> markdown_text`, where `logical_name` is canonical downstream identity and output-relative key
- alternatives considered:
  - pass structured payloads with file kind, cells, AST data, or output trees through full pipeline
  - preserve raw notebook JSON through later stages
- impact:
  - review, patch, verify, and synthesize stay simple
  - tests stay focused on text rendering behavior
  - implementation avoids generic multi-format framework

### Decision: `logical_name` is canonical downstream identity

- context: review snippets, patch payload keys, verify matching, batch aggregation, and output paths all need one stable key
- choice: define `logical_name` as source-relative path with markdown output suffix semantics applied once at normalization boundary:
  - `.md` input keeps same relative path, e.g. `unit1/lesson.md -> unit1/lesson.md`
  - `.py` input appends `.md`, e.g. `unit1/solver.py -> unit1/solver.py.md`
  - `.ipynb` input appends `.md`, e.g. `unit1/lab.ipynb -> unit1/lab.ipynb.md`
- alternatives considered:
  - use bare stem names
  - use source-relative path without markdown output suffix
  - derive separate IDs for prompts and outputs
- impact:
  - removes ambiguity from patch payload keys and output filenames
  - preserves same-stem uniqueness without extra folders
  - keeps downstream stages keyed on one invariant identity

### Decision: Mixed root-source and child-folder batch input is invalid

- context: root can contain supported source files while child folders also contain supported source files
- choice: fail fast when both are present instead of guessing single-folder or batch behavior
- alternatives considered:
  - root wins silently
  - child folders win silently
  - merge root files into batch implicitly
- impact:
  - keeps discovery reproducible
  - prevents accidental mode flips from stray files
  - forces user-visible intent when input tree is ambiguous

### Decision: Generated and non-lecture directories are excluded explicitly

- context: recursive discovery can accidentally ingest notebook checkpoints, caches, and environment folders
- choice: first-pass ignore set excludes at minimum `.ipynb_checkpoints`, `__pycache__`, `.venv`, and `.git`
- alternatives considered:
  - no ignore rules
  - ad hoc exclusions only in tests
- impact:
  - avoids duplicate or irrelevant lecture sources
  - keeps batch membership stable
  - reduces noisy review findings

### Decision: `.md` remains passthrough

- context: existing users already depend on markdown handling
- choice: `.md` files are read unchanged into internal markdown map
- alternatives considered:
  - rewrap markdown files into synthetic headers by default
- impact:
  - preserves current behavior
  - avoids churn in existing tests and outputs

### Decision: `.py` normalizes to markdown wrapper with full code block

- context: python files are lecture artifacts, not target code to patch in-place
- choice: normalize `.py` into markdown with filename heading, optional module docstring when present, then full source in fenced `python` block
- alternatives considered:
  - AST-derived summaries only
  - function-by-function splitting
  - source-to-source rewrite mode
- impact:
  - smallest faithful representation
  - no new dependency required
  - preserves full teaching signal even when comments/docstrings are sparse

### Decision: `.ipynb` normalizes to flattened markdown document

- context: notebooks mix markdown, code, and outputs; first pass should preserve teaching signal without rich renderer complexity
- choice: normalize notebook cells in order using markdown cells as-is, code cells as fenced `python`, and selected plain-text outputs as fenced `text`
- alternatives considered:
  - keep notebook JSON raw
  - render HTML outputs
  - extract notebook images in first pass
- impact:
  - preserves lecture sequence
  - stdlib `json` is sufficient
  - avoids brittle HTML or image rendering in v1

### Decision: Notebook plain-text output handling is explicit and deterministic

- context: notebook outputs appear in multiple shapes and can be serialized inconsistently
- choice: include only these output forms, joined with newline preservation:
  - `stream.text`
  - `execute_result.data["text/plain"]`
  - `display_data.data["text/plain"]`
  - `error.traceback`
  Arrays of lines are joined with `\n`; unsupported output mime types are ignored. If normalized content contains triple backticks, fence length must be increased deterministically so rendered markdown stays valid.
- alternatives considered:
  - free-form serialization of any text-like field
  - include all notebook output objects verbatim
- impact:
  - makes notebook normalization reproducible
  - bounds implementation complexity
  - keeps tests exact rather than interpretive

### Decision: Rich notebook outputs are explicit non-goal for v1

- context: notebooks may contain plots, HTML tables, widgets, and images
- choice: skip non-text outputs in first pass; keep only plain-text outputs
- alternatives considered:
  - support every notebook mime type immediately
- impact:
  - keeps first version bounded
  - leaves clear upgrade path if text-only notebook flattening proves insufficient

### Decision: Output names stay markdown and preserve source extension when needed

- context: `lesson.md`, `lesson.py`, and `lesson.ipynb` can collide if all collapse to `lesson.md`
- choice: output naming follows `logical_name` exactly, so non-markdown sources preserve original extension in markdown stem and markdown sources keep existing relative path
- alternatives considered:
  - always drop original extension
  - create extension-specific output folders
- impact:
  - avoids collisions without adding folder complexity
  - makes provenance obvious in patched outputs

### Decision: Prompt and CLI wording should become source-neutral

- context: current wording says “markdown class notes” even though supported input scope will widen
- choice: update user-facing strings to “lecture source files” or equivalent source-neutral language where contract is described
- alternatives considered:
  - leave wording stale and rely on docs only
- impact:
  - product contract matches behavior
  - less confusion about `.py` and `.ipynb` acceptance

## Invariants

- supported input discovery is defined by one canonical extension set and one canonical discovery helper
- `.md`, `.py`, and `.ipynb` are normalized before review begins
- `logical_name` is stable from normalization through patch output write
- downstream stages do not branch on source extension
- downstream prompts consume normalized markdown text only
- outputs remain markdown notes plus existing report artifacts
- batch semantics depend on discovered lecture-source sets, not on extension type
- existing markdown-only flows remain valid after change
- notebook cell order is preserved during normalization
- first-pass notebook normalization includes plain-text outputs only
- mixed root-source and child-folder batch inputs fail fast rather than guessing mode
- ignored generated directories do not contribute lecture sources or batch membership

## Acceptance Criteria

- source discovery treats `.md`, `.py`, and `.ipynb` as valid lecture-source files
- folder with supported source files and no batch ambiguity is processed as single lecture set
- batch discovery treats child folders containing any supported source file as batch members
- run fails clearly when root contains supported source files and child folders with supported source files also exist
- discovery ignores at minimum `.ipynb_checkpoints`, `__pycache__`, `.venv`, and `.git`
- markdown inputs keep existing behavior unchanged
- python input normalizes into markdown text that includes filename context and full fenced code block
- notebook input normalizes into markdown text that preserves markdown cells, code cells, and selected plain-text outputs in source order with deterministic newline joining
- patch output remains markdown-only for every supported input kind
- no downstream stage contains behavior that branches on `.py` or `.ipynb`
- output naming avoids collisions between same-stem source files of different types
- README and CLI help describe expanded lecture-source input contract clearly

## Non-Goals

- rewriting `.py` files back into `.py`
- rewriting `.ipynb` files back into notebook JSON
- AST-aware code critique mode
- syntax-preserving code transformation mode
- notebook HTML rendering
- notebook image extraction or plot OCR in first pass
- generic plugin architecture for arbitrary future source types

## Risks and Mitigations

- risk: normalized code-heavy inputs may be too noisy for reviewer
  - mitigation: keep normalization deterministic and full-fidelity first; tune prompts later only if evidence shows quality issues
- risk: notebook rich outputs may contain key teaching signal that plain text misses
  - mitigation: make rich-output skipping explicit non-goal and add upgrade path only if real notebooks require it
- risk: output filename collisions across same-stem inputs
  - mitigation: preserve original source extension in output markdown stem for non-markdown inputs
- risk: implementation leaks source-type branching into later stages
  - mitigation: spec requires all type handling to stop at normalization boundary
- risk: discovery semantics drift between single-folder and batch modes
  - mitigation: both modes must reuse one supported-source discovery helper
- risk: recursive discovery ingests generated duplicates or environment files
  - mitigation: define one explicit ignore list and make all discovery paths reuse it
- risk: notebook normalization differs across implementations
  - mitigation: lock supported output subtypes, newline joining, and code-fence escaping in spec

## Validation Plan

- proof target: supported-source discovery works for mixed inputs
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts single folder with `.md`, `.py`, and `.ipynb` files is treated as one lecture set and all files are loaded
- proof target: mixed root-source and child-folder batch ambiguity fails fast
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts clear error when supported source files exist at root and in child folders simultaneously
- proof target: batch discovery works for non-markdown lecture sources
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts child folders with `.py` or `.ipynb` sources are included in batch membership
- proof target: generated directories do not affect discovery
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts `.ipynb_checkpoints`, `__pycache__`, `.venv`, and `.git` contents are ignored during single-folder and batch discovery
- proof target: markdown passthrough remains unchanged
  - method: regression test
  - evidence: existing markdown pipeline tests continue to pass with no behavior drift
- proof target: python normalization is deterministic and preserves full source
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts normalized `.py` content includes heading context and full fenced `python` source block
- proof target: notebook normalization preserves lecture order
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts markdown cells, code cells, and `text/plain` outputs appear in original notebook order
- proof target: notebook normalization handles supported output subtypes deterministically
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts `stream.text`, `execute_result.data["text/plain"]`, `display_data.data["text/plain"]`, and `error.traceback` are normalized with newline-preserving joins and valid markdown fences
- proof target: notebook rich outputs are excluded in first pass
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts HTML and image-only notebook outputs are omitted from normalized text
- proof target: patched outputs stay markdown-only
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts `.py` and `.ipynb` inputs yield `patched_notes/*.md` outputs only
- proof target: downstream stages stay source-type agnostic
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts review, patch, verify, and synthesize stage builders consume only normalized `dict[str, str]` maps keyed by `logical_name`, with no source-kind argument crossing stage boundary
- proof target: output naming avoids same-stem collisions
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts `lesson.md`, `lesson.py`, and `lesson.ipynb` normalize to distinct `logical_name` values and distinct patched markdown output paths
- proof target: canonical extension set is single-sourced
  - method: unit test plus inspection
  - evidence: `tests/test_pipeline.py` plus `note_refinery_simple/pipeline.py` show discovery, batch detection, and readiness checks all route through one supported-source helper
- proof target: docs and CLI wording match expanded contract
  - method: inspection
  - evidence: `README.md` and CLI help text describe lecture-source inputs as `.md`, `.py`, and `.ipynb`

## Completion Criteria

Specification is complete when:

1. supported input extensions, normalization rules, and output naming rules are explicitly defined
2. `logical_name`, mixed-mode failure behavior, and ignore rules are explicitly defined
3. no downstream stage is allowed to branch on `.py` or `.ipynb`
4. first-pass notebook and python scope is bounded clearly enough to avoid source-rewrite creep
5. validation plan proves mixed-source discovery, deterministic normalization, and unchanged markdown outputs
6. implementation can proceed with one bounded plan without reopening product scope
