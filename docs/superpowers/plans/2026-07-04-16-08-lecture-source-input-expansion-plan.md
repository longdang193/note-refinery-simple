---
layer: change
artifact_type: plan
status: proposed
template_id: implementation-plan
name: lecture-source-input-expansion
parent_workstream: none
parent_spec: docs/superpowers/specs/2026-07-04-15-59-lecture-source-input-expansion-spec.md
targets:
  - note_refinery_simple/pipeline.py
  - note_refinery_simple/cli.py
  - note_refinery_simple/prompts.py
  - prompts/profiles/default/review.md
  - prompts/profiles/default/patch.md
  - prompts/profiles/default/verify.md
  - prompts/profiles/default/synthesize.md
  - prompts/profiles/strict/review.md
  - prompts/profiles/strict/patch.md
  - prompts/profiles/strict/verify.md
  - prompts/profiles/strict/synthesize.md
  - tests/test_pipeline.py
  - tests/test_cli.py
  - tests/test_prompts.py
  - README.md
related_features: []
related_stages: []
---

# Implementation Plan: Lecture Source Input Expansion For `.md`, `.py`, And `.ipynb`

## Goal

Implement bounded input expansion so pipeline accepts lecture-source files in `.md`, `.py`, and `.ipynb`, normalizes them once at source boundary into markdown text, and keeps downstream `review -> patch -> verify -> synthesize` behavior markdown-only.

## Key Deliverables

### One SSOT source discovery and identity layer

Add one canonical source-extension set, one canonical ignore set, one canonical discovery helper, and one canonical `logical_name` contract so single-folder mode, batch detection, and readiness checks stop duplicating file-type logic.

### One deterministic normalization boundary

Normalize supported source files into markdown text with exact rules for markdown passthrough, python wrapping, notebook flattening, newline joining, and fence safety.

### One unchanged downstream pipeline contract

Keep review, patch, verify, and synthesize stages keyed only by normalized `dict[str, str]` maps and markdown outputs, without source-type branches.

### One regression-proof validation and doc update set

Add targeted unit coverage for mixed discovery, ambiguity failure, ignore rules, notebook normalization, same-stem identity stability, cached rerun behavior, and user-facing CLI/prompt/README wording.

## Task/Wave Breakdown

### Task 1: Add SSOT source discovery, ignore rules, and canonical identity

**Purpose:**
- move all source-type awareness into one shared boundary and freeze stable downstream keys before normalization work starts

**Files:**
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- approved spec exists at `docs/superpowers/specs/2026-07-04-15-59-lecture-source-input-expansion-spec.md`
- current markdown discovery lives in `collect_review_note_dirs()`, `read_notes()`, and `has_markdown_files()`

**Steps:**
- [ ] Step 1: add one canonical extension set, one canonical ignore-dir set, and one recursive helper such as `iter_source_files()` in `note_refinery_simple/pipeline.py`
- [ ] Step 2: define `logical_name` once at source boundary so `.md` keeps relative path and non-markdown sources append `.md` to source-relative path
- [ ] Step 3: update scope detection helpers to reuse canonical discovery helper instead of direct `*.md` glob checks
- [ ] Step 4: make ambiguous input trees fail fast when root has supported source files and child folders with supported source files also exist
- [ ] Step 5: update readiness checks to use supported-source discovery rather than markdown-only checks

**Verification:**
- [ ] targeted unit test proves supported-source discovery works for `.md`, `.py`, and `.ipynb`
- [ ] targeted unit test proves `.ipynb_checkpoints`, `__pycache__`, `.venv`, and `.git` are ignored
- [ ] targeted unit test proves mixed root-source and child-folder batch ambiguity raises clear error
- [ ] targeted unit test proves same-stem inputs normalize to distinct `logical_name` values

**Exit Criteria:**
- one helper owns extensions, ignores, and recursion, and no remaining directory-discovery path hardcodes markdown-only logic

### Task 2: Add deterministic `.py` and `.ipynb` normalization

**Purpose:**
- flatten supported lecture-source files into one markdown-text map without teaching later stages about source formats

**Files:**
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 1 complete
- downstream stage builders still accept `dict[str, str]` maps only

**Steps:**
- [ ] Step 1: keep `.md` passthrough unchanged through normalization boundary
- [ ] Step 2: normalize `.py` into markdown with filename heading and full fenced `python` block only
- [ ] Step 3: normalize `.ipynb` by preserving cell order, rendering markdown cells verbatim, code cells as fenced `python`, and supported plain-text outputs as fenced `text`
- [ ] Step 4: define deterministic newline joining for notebook array-valued outputs and deterministic fence escalation when content already contains triple backticks
- [ ] Step 5: ignore unsupported notebook mime types in first pass and keep this logic local to notebook normalizer only

**Verification:**
- [ ] targeted unit test proves python normalization preserves full source and expected heading context
- [ ] targeted unit test proves notebook normalization preserves markdown/code/output order
- [ ] targeted unit test proves `stream.text`, `execute_result.data["text/plain"]`, `display_data.data["text/plain"]`, and `error.traceback` normalize deterministically
- [ ] targeted unit test proves unsupported rich notebook outputs are omitted
- [ ] targeted unit test proves fence escalation keeps rendered markdown valid when source content contains code fences

**Exit Criteria:**
- all supported inputs become deterministic markdown text before review and no normalization rule leaks into downstream stage code

### Task 3: Rewire pipeline entrypoints to use normalized source map only

**Purpose:**
- swap markdown-only readers for normalized source readers while preserving existing output surfaces and patch/verify/synthesize behavior

**Files:**
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Tasks 1 and 2 complete
- existing downstream prompts and patch payload contract remain markdown-text based

**Steps:**
- [ ] Step 1: replace markdown-only loading paths in review, patch, verify, synthesize, batch aggregation, and selective repair with normalized source-map helpers
- [ ] Step 2: keep `patched_notes/*.md`, `reports/*.md`, and `concept_map.json` output contracts unchanged
- [ ] Step 3: preserve single-folder repair loop behavior by matching verify regressions against canonical `logical_name` values
- [ ] Step 4: keep image-context logic scoped to original `.md` sources only; do not add notebook-image extraction or normalized-source image scanning in this task
- [ ] Step 5: confirm no review/patch/verify/synthesize stage adds `.py` or `.ipynb` conditionals outside source-boundary helpers
- [ ] Step 6: preserve cached rerun behavior for existing markdown-only flows, including `--reuse-image-context-from` loading and `markdown_file` key matching

**Verification:**
- [ ] targeted unit test proves patched outputs for `.py` and `.ipynb` inputs are markdown files only
- [ ] targeted unit test proves batch aggregation uses normalized `logical_name` keys consistently
- [ ] targeted unit test proves stage builders still consume only normalized `dict[str, str]` maps with no source-kind argument crossing stage boundary
- [ ] targeted unit test proves existing markdown-only cached image-context reuse still works after source-boundary refactor
- [ ] regression test proves markdown-only pipeline behavior still passes existing coverage unchanged

**Exit Criteria:**
- downstream pipeline stays markdown-only and all supported input kinds flow through same stage interfaces

### Task 4: Update CLI/README wording and close validation loop

**Purpose:**
- align user-facing contract with shipped behavior and leave one runnable verification path for completion

**Files:**
- Modify: `note_refinery_simple/cli.py`
- Modify: `note_refinery_simple/prompts.py`
- Modify: `prompts/profiles/default/review.md`
- Modify: `prompts/profiles/default/patch.md`
- Modify: `prompts/profiles/default/verify.md`
- Modify: `prompts/profiles/default/synthesize.md`
- Modify: `prompts/profiles/strict/review.md`
- Modify: `prompts/profiles/strict/patch.md`
- Modify: `prompts/profiles/strict/verify.md`
- Modify: `prompts/profiles/strict/synthesize.md`
- Modify: `README.md`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_prompts.py`
- Verify: `tests/test_pipeline.py`
- Verify: `tests/test_cli.py`

**Preconditions:**
- Tasks 1 through 3 complete
- target strings and shipped prompt files that still say “markdown class notes” are known

**Steps:**
- [ ] Step 1: update CLI description, pipeline fallback strings, and shipped prompt profile files so user-visible input scope consistently says lecture-source files or equivalent source-neutral wording
- [ ] Step 2: update README usage and output-contract text to describe supported source inputs, fail-fast ambiguity rule, ignore behavior, markdown-only outputs, and `.md`-only image-context scope for v1
- [ ] Step 3: add or update prompt-loading and CLI tests where wording or loaded runtime prompt content changes materially
- [ ] Step 4: run targeted then full test suite and fix only defects within this change scope

**Verification:**
- [ ] `tests/test_cli.py` covers updated parser description or visible CLI wording if asserted
- [ ] `tests/test_prompts.py` proves loaded default and strict prompt sets no longer describe input scope as markdown-only notes
- [ ] `tests/test_pipeline.py` covers discovery, normalization, ambiguity failure, identity stability, and downstream invariants
- [ ] `py -3 -m unittest discover -s tests -t . -v` passes

**Exit Criteria:**
- docs and CLI match shipped input contract and tests prove behavior end to end

## Verification

Run in this order:

1. targeted pipeline tests for discovery and normalization additions
   - `py -3 -m unittest tests.test_pipeline -v`
2. targeted CLI tests for wording-sensitive parser behavior
   - `py -3 -m unittest tests.test_cli -v`
3. targeted prompt-loading tests for shipped runtime prompt text
   - `py -3 -m unittest tests.test_prompts -v`
4. full regression suite
   - `py -3 -m unittest discover -s tests -t . -v`
5. optional type check if already part of local workflow
   - `python -m mypy note_refinery_simple tests`

Completion evidence should show:
- `.md`, `.py`, and `.ipynb` discovery from one canonical helper
- fail-fast error for mixed root-source and child-folder batch ambiguity
- deterministic notebook normalization for supported plain-text outputs
- distinct `logical_name` keys and distinct patched markdown outputs for same-stem inputs
- unchanged markdown-only image-context reuse behavior for reruns
- unchanged markdown-only output contract for all supported source kinds

## Completion Criteria

1. one canonical source discovery helper and one canonical `logical_name` contract are implemented and reused everywhere
2. `.md`, `.py`, and `.ipynb` inputs normalize deterministically to markdown text before review
3. downstream review, patch, verify, and synthesize code remains source-type agnostic
4. single-folder mode, batch detection, readiness checks, and selective repair all work from same source identity semantics
5. README, CLI, fallback strings, and shipped prompt profiles describe lecture-source inputs consistently
6. existing markdown-only image-context reruns keep working unchanged
7. targeted tests and full unit suite pass without adding new infrastructure or source-rewrite behavior
