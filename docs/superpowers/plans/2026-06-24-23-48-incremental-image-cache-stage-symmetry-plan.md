---
layer: change
artifact_type: plan
status: proposed
template_id: implementation-plan
name: incremental-image-cache-stage-symmetry
parent_spec: docs/superpowers/specs/2026-06-24-23-40-incremental-image-cache-stage-symmetry-spec.md
targets:
  - note_refinery_simple/pipeline.py
  - note_refinery_simple/cli.py
  - tests/test_pipeline.py
  - tests/test_cli.py
  - README.md
related_features: []
related_stages: []
---

# Implementation Plan For Incremental Image Cache And Stage Symmetry

## Goal

Implement incremental review image-cache persistence and align stage behavior around one simple contract: each stage writes canonical artifacts, retries only its smallest safe unit, and reuses only canonical upstream outputs.

## Key Deliverables

### Incremental review image cache

Review image enrichment persists `reports/image_context.json` incrementally and atomically so partial successful work survives later failure and can be reused by reruns.

### Stage symmetry hardening

Review, patch, verify, and synth follow explicit stage-local rules for canonical outputs, retry scope, and downstream reuse, without adding a new orchestration framework.

### Regression coverage and docs

Tests cover incremental image-cache survival and reuse semantics, while README documents the canonical rerun behavior and stage artifact contract.

## Task/Wave Breakdown

### Task 1: Harden review image-cache persistence

**Purpose:**
- preserve successful image enrichment work immediately instead of only at end of full review batch

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- current review writes `reports/image_context.json` only after batch enrichment completes
- canonical cache path remains `reports/image_context.json`

**Steps:**
- [ ] Step 1: inspect current `build_image_contexts()` and `write_review()` flow to identify minimal insertion point for incremental persistence
- [ ] Step 2: add tiny helper for atomic JSON artifact write so review can rewrite canonical cache file safely after each successful image context append
- [ ] Step 3: update review image-enrichment flow so `reports/image_context.json` is persisted incrementally without changing public artifact path or CLI contract
- [ ] Step 4: keep final review prompt build reading in-memory collected contexts so stage output remains unchanged except for crash tolerance

**Verification:**
- [ ] `py -3 -m unittest tests.test_pipeline.ReviewPipelineTest.test_review_keeps_running_when_one_image_enrichment_fails -v`
- [ ] new targeted unit test proves first successful image remains in `reports/image_context.json` after later image failure

**Exit Criteria:**
- partial image-enrichment progress survives stage interruption through canonical cache artifact

### Task 2: Make partial cache reuse explicit and symmetric

**Purpose:**
- ensure partial upstream artifacts can be reused cleanly through existing cache flags without split truth or hidden alternate paths

**Files:**
- Inspect: `note_refinery_simple/cli.py`
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`
- Verify: `tests/test_cli.py`

**Preconditions:**
- Task 1 complete
- cache reuse flags already exist and point at canonical `reports/` artifacts

**Steps:**
- [ ] Step 1: inspect current cached review and cached image-context load path to confirm no second authoritative cache location exists
- [ ] Step 2: define minimal stage-contract comments or helper naming that keep review, patch, verify, and synth aligned on canonical artifact reads
- [ ] Step 3: if needed, tighten partial-cache load behavior so rerun consumes canonical saved contexts exactly as persisted by Task 1
- [ ] Step 4: avoid new config keys, cache directories, or generic stage framework; keep symmetry in local helpers and stage-local contracts only

**Verification:**
- [ ] `py -3 -m unittest tests.test_cli.CliParserTest.test_parser_accepts_cached_rerun_flags tests.test_pipeline.ReviewPipelineTest.test_write_review_can_reuse_cached_image_context tests.test_pipeline.ReviewPipelineTest.test_run_can_reuse_cached_review_without_calling_reviewer -v`
- [ ] new targeted unit test proves partial `image_context.json` can be reused from canonical path

**Exit Criteria:**
- rerun logic reuses canonical cache artifacts only and stage symmetry is explicit enough to guide future changes

### Task 3: Review cross-stage retry and artifact symmetry

**Purpose:**
- identify smallest code changes needed so review, patch, verify, and synth follow same principles while preserving stage-specific safe retry unit

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 1 complete
- Task 2 complete
- current patch and synth repair paths already exist

**Steps:**
- [ ] Step 1: inspect current stage behavior and map each stage to canonical unit of work, primary artifact, machine artifact, retry unit, and downstream input
- [ ] Step 2: remove small asymmetries where code already has near-identical behavior but different ad hoc handling
- [ ] Step 3: preserve explicit stage-local retry units: per-image for review persistence, per-file for patch, batch-with-flag extraction for verify, whole-response repair for synth
- [ ] Step 4: defer optional `verify_flags.json` sidecar unless markdown parsing remains the main blocking asymmetry after review pass

**Verification:**
- [ ] `py -3 -m unittest tests.test_pipeline.ReviewPipelineTest.test_write_synthesis_recovers_from_malformed_json tests.test_pipeline.ReviewPipelineTest.test_run_repatches_only_flagged_files_after_verify -v`
- [ ] inspection confirms no second authoritative artifact path was introduced for any stage

**Exit Criteria:**
- stage contracts are simpler, more symmetric, and still bounded by smallest safe retry unit per stage

### Task 4: Update docs and prove with live rerun

**Purpose:**
- make user-facing behavior clear and prove incremental cache survives real rerun path

**Files:**
- Modify: `README.md`
- Verify: `README.md`
- Verify: `tests/test_pipeline.py`
- Verify: live-run output root under repo root

**Preconditions:**
- Tasks 1 through 3 complete
- test suite green locally

**Steps:**
- [ ] Step 1: update README stage overview so review cache artifact is described as canonical incremental output, not end-only batch output
- [ ] Step 2: document rerun behavior using existing `--reuse-image-context-from` and `--reuse-review-from` flags
- [ ] Step 3: run focused live scenario that interrupts or simulates partial review progress, then rerun from saved cache path
- [ ] Step 4: capture resulting artifact evidence paths for `REVIEW.md`, `image_context.json`, and downstream rerun outputs

**Verification:**
- [ ] `py -3 -m unittest discover -s tests -t . -v`
- [ ] `python -m mypy note_refinery_simple tests`
- [ ] live run shows canonical `reports/image_context.json` exists before full review stage would otherwise complete, and rerun succeeds from reused cache

**Exit Criteria:**
- docs match actual rerun behavior and live evidence proves crash-tolerant cache reuse

## Verification

- `py -3 -m unittest discover -s tests -t . -v`
- `python -m mypy note_refinery_simple tests`
- live rerun using canonical cached artifacts under one run root proves review cache reuse and full pipeline completion

## Completion Criteria

A plan item is considered complete when:

1. all Key Deliverables are satisfied
2. all downstream/child items are terminal
3. every child item is `completed` or `dropped`
