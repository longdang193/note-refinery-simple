---
layer: change
artifact_type: plan
status: completed
template_id: implementation-plan
name: lazy-batch-map-reduce
parent_workstream: none
parent_spec: docs/superpowers/specs/2026-06-27-15-24-lazy-batch-map-reduce-spec.md
targets:
  - note_refinery_simple/cli.py
  - note_refinery_simple/pipeline.py
  - tests/test_cli.py
  - tests/test_pipeline.py
  - README.md
related_features: []
related_stages: []
---

# Implementation Plan: Lazy Batch Map/Reduce For Patch, Verify, And Synthesize

## Goal

Implement smallest useful batch contract after folder-concurrent review: one root `batch_manifest.json`, batch `patch` as folder fan-out, and batch `verify` plus `synthesize` as one global pass over complete patched batch, without adding extra orchestration machinery.

## Key Deliverables

### Canonical batch-root manifest and scope detection

Batch review writes one root `batch_manifest.json`, and later CLI/pipeline entrypoints can distinguish single-folder mode from batch-root mode without rediscovery drift.

### Batch patch wrapper over existing folder patch logic

`patch` accepts batch root, iterates manifest-listed folders, and produces folder-local patched outputs using existing single-folder patch behavior as inner engine.

### Batch verify and synthesize global outputs

`verify` and `synthesize` accept batch root, enforce complete patched-set barrier, and write exactly one root-level `reports/VERIFY.md` and `reports/SYNTHESIS.md`.

### Regression coverage and README alignment

Tests prove manifest reuse, barrier behavior, and local/global artifact split; README explains one-folder mode versus batch mode and stage topology.

## Task/Wave Breakdown

### Task 1: Add batch manifest contract and scope detection

**Purpose:**
- freeze batch membership once so later stages stop guessing from filesystem shape

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Inspect: `note_refinery_simple/cli.py`
- Modify: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/cli.py`
- Verify: `tests/test_pipeline.py`
- Verify: `tests/test_cli.py`

**Preconditions:**
- approved spec exists at `docs/superpowers/specs/2026-06-27-15-24-lazy-batch-map-reduce-spec.md`
- current batch review already creates one folder subtree per discovered source folder

**Steps:**
- [x] Step 1: inspect current folder-of-folders review output shape and choose smallest manifest fields needed for stable membership, such as folder id and relative output path
- [x] Step 2: write root `batch_manifest.json` during batch review creation and keep single-folder review behavior unchanged
- [x] Step 3: add lightweight scope detection helpers so CLI/pipeline can tell single-folder root from batch root and load manifest when present

**Verification:**
- [x] targeted unit test proves batch review writes one canonical `batch_manifest.json`
- [x] targeted CLI or pipeline test proves single-folder mode still bypasses batch-manifest path

**Exit Criteria:**
- one canonical manifest exists for batch runs and no per-folder manifest family is introduced

### Task 2: Add batch patch wrapper with manifest-driven folder fan-out

**Purpose:**
- let users patch full reviewed batch from batch root instead of manual per-folder commands

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 1 complete
- current single-folder patch path remains stable and callable per folder

**Steps:**
- [x] Step 1: extract or reuse smallest helper that patches one reviewed folder using current canonical local artifacts
- [x] Step 2: add batch-root `patch` path that iterates manifest-listed folders and calls same inner folder patch helper
- [x] Step 3: ensure batch patch reads membership from `batch_manifest.json`, not ad hoc rediscovery, and preserves folder-local `patched_notes/` outputs

**Verification:**
- [x] targeted unit test proves batch patch processes every manifest-listed folder
- [x] targeted unit test proves manifest order or filesystem order drift does not change batch membership

**Exit Criteria:**
- batch `patch` works from batch root and still reuses current single-folder patch behavior

### Task 3: Add batch verify and synthesize with hard barrier

**Purpose:**
- produce one batch-wide verification and one batch-wide synthesis only when full patched corpus is ready

**Files:**
- Inspect: `note_refinery_simple/pipeline.py`
- Modify: `note_refinery_simple/pipeline.py`
- Verify: `tests/test_pipeline.py`

**Preconditions:**
- Task 2 complete
- batch root already has stable manifest and folder-local patched outputs

**Steps:**
- [x] Step 1: add helper that validates every manifest-listed folder has canonical `patched_notes/` before batch reduce stages start
- [x] Step 2: add batch `verify` path that loads patched notes across manifest-listed folders and writes one root `reports/VERIFY.md`
- [x] Step 3: add batch `synthesize` path that loads same complete patched corpus and writes one root `reports/SYNTHESIS.md` plus existing machine-readable synthesis artifacts
- [x] Step 4: keep single-folder verify and synthesize behavior unchanged

**Verification:**
- [x] targeted unit test proves batch `verify` fails with explicit missing-folder list when patched outputs are incomplete
- [x] targeted unit test proves batch `verify` writes only one root-level `reports/VERIFY.md`
- [x] targeted unit test proves batch `synthesize` writes only root-level synthesis outputs in batch mode

**Exit Criteria:**
- batch reduce stages enforce complete-set barrier and keep local/global artifact scopes clean

### Task 4: Update README and prove end-to-end behavior

**Purpose:**
- make shipped batch behavior understandable and gather proof that stage flow works from batch root

**Files:**
- Modify: `README.md`
- Verify: `README.md`
- Verify: live-run output root under repo root

**Preconditions:**
- Tasks 1 through 3 complete
- targeted tests for batch behavior pass locally

**Steps:**
- [x] Step 1: update README stage overview so batch means full discovered folder set, not concurrency chunk
- [x] Step 2: document batch commands for `review`, `patch`, `verify`, and `synthesize`, plus note that local artifacts stay under folder subtree while global artifacts stay at batch root
- [x] Step 3: run one live batch scenario from batch root and inspect generated manifest, patched folders, root `reports/VERIFY.md`, and root `reports/SYNTHESIS.md`

**Verification:**
- [x] live run shows one `batch_manifest.json`, per-folder `patched_notes/`, one root `reports/VERIFY.md`, and one root `reports/SYNTHESIS.md`

**Exit Criteria:**
- docs match shipped behavior and one end-to-end batch run proves usability

## Verification

- `py -3 -m unittest discover -s tests -t . -v`
- `python -m mypy note_refinery_simple tests`
- live batch run from reviewed batch root proves:
  - one `batch_manifest.json`
  - batch `patch` updates every manifest-listed folder
  - batch `verify` writes one root `reports/VERIFY.md`
  - batch `synthesize` writes one root `reports/SYNTHESIS.md`

## Completion Criteria

1. batch manifest, batch patch, batch verify, and batch synthesize contracts all ship without extra framework surfaces
2. single-folder commands remain unchanged
3. tests, type check, and one live batch run prove stable membership, hard barrier behavior, and correct local/global artifact placement
