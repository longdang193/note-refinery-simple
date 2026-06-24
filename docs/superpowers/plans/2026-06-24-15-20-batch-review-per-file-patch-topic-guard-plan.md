---
layer: change
artifact_type: plan
status: completed
template_id: implementation-plan
name: batch-review-per-file-patch-topic-guard
parent_workstream: none
parent_spec: docs/superpowers/specs/2026-06-24-15-05-batch-review-per-file-patch-topic-guard-spec.md
targets:
  - note_refinery_simple/pipeline.py
  - note_refinery_simple/config.py
  - note_refinery_simple/cli.py
  - tests/test_pipeline.py
  - tests/test_config.py
  - README.md
related_features: []
related_stages: []
---

# Implementation Plan: Batch Review With Per-File Patch, Topic Guard, And Concurrent Repair

## Goal

Implement per-file patch execution with topic guard and bounded concurrency so batch review keeps cross-file context, patched notes stay in correct file envelope, and selective repair replaces whole-batch patch retries.

## Key Deliverables

### Per-file patch orchestration in pipeline

Replace current multi-file patch payload path with per-file patch workers that reuse shared `REVIEW.md`, file-local source content, and file-local image context while preserving existing stage outputs.

### Topic guard and selective repair flow

Add a small acceptance gate for patched file identity, wire failed files into bounded local retries, and keep batch verify as final batch-level quality pass.

### Runtime config, tests, and docs alignment

Expose bounded concurrency through existing SSOT config surfaces, add focused regression coverage for swapped-topic and concurrent patch behavior, and update README batch-stage guidance.

## Task/Wave Breakdown

### Task 1: Reshape patch stage around per-file workers

**Purpose:**
- remove dependency on one multi-file patch payload and make each patch request own exactly one output file

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- approved spec at `docs/superpowers/specs/2026-06-24-15-05-batch-review-per-file-patch-topic-guard-spec.md`
- current fallback regression tests remain green before refactor

**Steps:**
- [x] Step 1: extract file-scoped patch request path that takes one note, shared review markdown, and file-local image context
- [x] Step 2: replace `_collect_patched_files()` batch payload flow with loop or worker executor that aggregates accepted per-file results
- [x] Step 3: keep output contract unchanged for `patched_notes/`, `reports/REVIEW.md`, `reports/VERIFY.md`, and `reports/SYNTHESIS.md`

**Verification:**
- [x] `py -3 -m unittest discover -s tests -t . -v`
- [x] inspect call flow in `pipeline.py` to confirm one patch request maps to one file only

**Exit Criteria:**
- patch stage no longer depends on one model response containing all files

### Task 2: Add topic guard and local retry rules

**Purpose:**
- reject obvious wrong-file patches before write and keep retries local to failed files only

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 1 complete
- source lecture identity signals chosen from existing inputs such as filename, headings, and review references

**Steps:**
- [x] Step 1: implement cheap topic guard for file identity using deterministic signals first
- [x] Step 2: route guard failures through bounded per-file retry path without rewriting accepted files
- [x] Step 3: keep clear progress messages for patch start, guard pass/fail, retry, and final write

**Verification:**
- [x] add regression test for obvious lecture swap rejection
- [x] add regression test proving failed file retry does not touch accepted sibling files

**Exit Criteria:**
- wrong-file payload is rejected before write and retries remain file-local

### Task 3: Add bounded concurrency through existing config surface

**Purpose:**
- speed up per-file patching without adding new orchestration layer or breaking SSOT config

**Files:**
- Inspect: `note_refinery_simple/config.py`
- Inspect: `note_refinery_simple/cli.py`
- Modify: `note_refinery_simple/config.py`
- Modify: `note_refinery_simple/cli.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_config.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 1 and Task 2 complete
- concurrency default stays low and bounded

**Steps:**
- [x] Step 1: add `patch_concurrency` to `note_refinery.yaml` loading path and CLI override path only if needed by current SSOT pattern
- [x] Step 2: use stdlib worker primitive in patch stage with default concurrency `3`
- [x] Step 3: make progress output file-scoped so concurrent runs still show visible forward movement

**Verification:**
- [x] add config test for `patch_concurrency` resolution
- [x] add pipeline test proving concurrent mock run emits complete patched set without output collisions

**Exit Criteria:**
- patch stage can run multiple per-file workers concurrently with bounded default and stable outputs

### Task 4: Finish selective verify loop and docs

**Purpose:**
- keep verify and synthesis stable after refactor and document new batch behavior

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Modify: `README.md`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Tasks 1 through 3 complete
- verify report structure remains readable enough to identify flagged files

**Steps:**
- [x] Step 1: keep batch verify over accepted patched set and wire selective repair queue for files flagged by guard or verify parsing
- [x] Step 2: ensure synthesis reads accepted final patched set only
- [x] Step 3: update README stage overview and batch-processing notes to explain per-file patching, topic guard, and progress output

**Verification:**
- [x] add pipeline test for selective repair on mixed pass/fail file batch
- [x] inspect README examples for full `run` flow and batch-folder behavior accuracy

**Exit Criteria:**
- verify and synthesis still run after patch refactor, and docs match actual stage behavior

## Verification

- `py -3 -m unittest discover -s tests -t . -v`
- `python -m mypy note_refinery_simple tests`
- live run on `C:\Users\HOANG PHI LONG DANG\MinerU` using existing config, then inspect new `reports/VERIFY.md` for absence of wrong-file-envelope regression

## Completion Criteria

1. per-file patch workers replace multi-file patch payload flow
2. topic guard rejects obvious lecture swaps before file write
3. bounded concurrency is configurable through existing SSOT runtime config surface
4. selective repair touches only flagged files
5. tests, type check, and one live batch run confirm no recurrence of known file-placement regression

