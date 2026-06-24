---
layer: change
artifact_type: plan
status: proposed
template_id: implementation-plan
name: folder-review-concurrency-ssot-symmetry
parent_workstream: none
parent_spec: docs/superpowers/specs/2026-06-25-00-09-folder-review-concurrency-ssot-symmetry-spec.md
targets:
  - note_refinery_simple/cli.py
  - note_refinery_simple/config.py
  - note_refinery_simple/pipeline.py
  - note_refinery.yaml.example
  - tests/test_cli.py
  - tests/test_config.py
  - tests/test_pipeline.py
  - README.md
related_features: []
related_stages: []
---

# Implementation Plan For Folder-Level Review Concurrency With SSOT And Symmetry

## Goal

Implement folder-level review concurrency for batch note processing while keeping sequential image enrichment inside each folder, preserving one runtime source of truth for concurrency, one canonical artifact contract per folder, and reuse of the existing single-folder review path as the inner engine.

## Key Deliverables

### Central runtime config for folder review concurrency

`note_refinery.yaml`, config loading, and CLI overrides support one canonical `review_folder_concurrency` setting aligned with existing runtime settings and validation behavior.

### Folder-concurrent review dispatch using existing single-folder engine

Batch review can process independent folders concurrently, while each folder still uses current sequential image enrichment, incremental `reports/image_context.json` persistence, and folder-local `REVIEW.md` output behavior.

### Regression coverage for SSOT, symmetry, and artifact isolation

Tests prove config resolution, concurrent folder dispatch, sequential in-folder image order, and strict folder-local artifact writes.

### User-facing docs and live proof

README explains the new knob and behavior, and one live run demonstrates folder-level concurrency with folder-local canonical outputs.

## Task/Wave Breakdown

### Task 1: Extend runtime config with one SSOT folder-concurrency knob

**Purpose:**
- add one canonical runtime setting for folder review concurrency without creating a second config path

**Files:**
- Inspect: `note_refinery_simple/config.py`
- Inspect: `note_refinery_simple/cli.py`
- Modify: `note_refinery_simple/config.py`
- Modify: `note_refinery_simple/cli.py`
- Modify: `note_refinery.yaml.example`
- Verify: `tests/test_config.py`
- Verify: `tests/test_cli.py`

**Preconditions:**
- approved spec exists at `docs/superpowers/specs/2026-06-25-00-09-folder-review-concurrency-ssot-symmetry-spec.md`
- existing runtime settings already resolve `patch_concurrency` through config file plus CLI override

**Steps:**
- [ ] Step 1: inspect current runtime config shape and reuse the existing `patch_concurrency` pattern for one new `review_folder_concurrency` field
- [ ] Step 2: add config parsing, validation, defaults, and CLI override support for `review_folder_concurrency`
- [ ] Step 3: update example config and CLI parser help text so the new knob lives in the same SSOT surface as other runtime knobs

**Verification:**
- [ ] `py -3 -m unittest tests.test_config.RuntimeConfigTest tests.test_cli.CliParserTest -v`

**Exit Criteria:**
- one resolved `review_folder_concurrency` value exists after config load and no alternate config path is introduced

### Task 2: Add folder-level review dispatch while reusing single-folder review logic

**Purpose:**
- speed up batch review across folders without changing single-folder review semantics

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 1 complete
- current single-folder review path already handles sequential image enrichment and incremental `image_context.json` persistence correctly

**Steps:**
- [ ] Step 1: inspect current batch note discovery and identify smallest insertion point for outer folder concurrency
- [ ] Step 2: add folder-level dispatch with stdlib executor, keeping one worker scoped to one folder review subtree
- [ ] Step 3: route each folder job through the existing single-folder review path instead of duplicating review logic
- [ ] Step 4: keep in-folder image enrichment sequential and preserve current incremental cache writes

**Verification:**
- [ ] targeted unit test proves multiple folders can review concurrently while a single folder still uses sequential image order
- [ ] targeted unit test proves the same single-folder review helper/path is used when `review_folder_concurrency=1` and when greater than `1`

**Exit Criteria:**
- folder-level concurrency exists, single-folder review behavior is preserved, and no parallel-only review implementation is introduced

### Task 3: Harden progress and folder-local artifact isolation

**Purpose:**
- make concurrent review observable and keep every folder strictly inside its own canonical artifact boundary

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 2 complete
- folder workers already dispatch through independent review jobs

**Steps:**
- [ ] Step 1: update progress messages to show outer folder progress and preserve inner image progress attribution
- [ ] Step 2: ensure each folder writes only its own `reports/REVIEW.md` and `reports/image_context.json` under its own run-root subtree
- [ ] Step 3: keep cache reuse folder-local and forbid shared batch-level image cache writes

**Verification:**
- [ ] targeted unit test proves per-folder outputs remain isolated
- [ ] targeted unit test proves progress messages identify folder context during concurrent review

**Exit Criteria:**
- concurrent review logs are attributable and no folder can overwrite another folder's canonical artifacts

### Task 4: Update docs and prove with a live run

**Purpose:**
- document the new behavior and gather direct evidence that folder-concurrent review works end to end

**Files:**
- Modify: `README.md`
- Verify: `README.md`
- Verify: live-run output root under repo root

**Preconditions:**
- Tasks 1 through 3 complete
- tests for folder concurrency pass locally

**Steps:**
- [ ] Step 1: update README usage and config sections for `review_folder_concurrency` and folder-level review behavior
- [ ] Step 2: document that images stay sequential inside a folder and canonical review artifacts stay folder-local
- [ ] Step 3: run a live batch review over multiple note folders with folder concurrency above `1`
- [ ] Step 4: capture output-root evidence showing multiple folder review subtrees, each with canonical `reports/REVIEW.md` and `reports/image_context.json`

**Verification:**
- [ ] live run shows visible folder-level progress and folder-local review artifacts

**Exit Criteria:**
- docs match shipped behavior and live evidence proves the new concurrency boundary works

## Verification

- `py -3 -m unittest discover -s tests -t . -v`
- `python -m mypy note_refinery_simple tests`
- live run with `review_folder_concurrency > 1` proves folder-level concurrency, sequential in-folder image order, and folder-local canonical review artifacts

## Completion Criteria

A plan item is considered complete when:

1. all Key Deliverables are satisfied
2. all downstream/child items are terminal
3. every child item is `completed` or `dropped`