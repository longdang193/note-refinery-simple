---
layer: change
artifact_type: spec
status: proposed
template_id: detailed-specification
name: folder-review-concurrency-ssot-symmetry
parent_workstream: none
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

# Folder-Level Review Concurrency With SSOT And Symmetry

## Goal

Define one bounded change that speeds up image enrichment by processing note folders concurrently while preserving sequential image handling inside each folder. The design must preserve single-source-of-truth configuration, canonical per-folder artifacts, and symmetric stage contracts across review, patch, verify, and synth.

### Triage

```text
Layer: change
Feature type: MODIFY
Summary: Add folder-level review concurrency for batch note processing while keeping sequential per-folder image enrichment and canonical per-folder cache artifacts.
Reasoning: Current review image enrichment is fully sequential across all folders, which underuses independent folder boundaries. Folder-level concurrency is the smallest safe acceleration because each folder already has its own review/cache contract, while per-image concurrency inside a folder would complicate ordering, progress, and incremental persistence.
Invariants:
  - one runtime SSOT knob controls folder review concurrency
  - one folder remains one canonical review/cache unit
  - images inside a folder remain sequential
  - each folder writes only its own canonical artifacts
  - downstream stages keep same canonical input/output contract
Dependencies:
  - existing folder-oriented note layout under input notes dir
  - existing per-folder review prompt and image-context artifact logic
  - existing patch concurrency contract
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

### Folder-level review concurrency contract

Define how batch runs dispatch independent folder review jobs concurrently while keeping the single-folder review flow unchanged.

### Central runtime configuration contract

Define one canonical runtime setting for folder review concurrency and its load/override behavior alongside existing runtime settings.

### Per-folder artifact SSOT rules

Define canonical output ownership so each folder review job writes only its own `REVIEW.md` and `image_context.json` under its own run-root subtree.

### Symmetric stage model for split execution

Define how outer folder concurrency and inner folder sequential processing fit the same stage contract model already used by review, patch, verify, and synth.

## Task/Wave Breakdown

### Wave 1: Source-first analysis

**Purpose:**
- define current review unit boundaries and identify smallest safe concurrency boundary

**Steps:**
- [ ] inspect current batch note discovery and single-folder review flow
- [ ] inspect current image enrichment ordering and incremental `image_context.json` persistence
- [ ] inspect runtime config loading for existing concurrency knobs
- [ ] identify where folder boundaries already act as natural isolated review/cache units

**Verification:**
- [ ] current source shows folder is safe concurrency boundary and image is current sequential sub-unit

**Exit Criteria:**
- no concurrency decision depends on unstated artifact-sharing assumptions

### Wave 2: Decision closure

**Purpose:**
- resolve folder concurrency shape, SSOT config placement, and stage-symmetry rules

**Steps:**
- [ ] define one canonical `review_folder_concurrency` runtime knob
- [ ] define batch dispatch behavior for folder review jobs
- [ ] define per-folder output-root/artifact isolation rules
- [ ] define progress contract for outer folder progress and inner image progress

**Verification:**
- [ ] every design question has one explicit decision and no second authoritative config or cache path

**Exit Criteria:**
- design is bounded, symmetric, and avoids per-image parallel complexity

### Wave 3: Validation and approval readiness

**Purpose:**
- make proof expectations explicit before implementation planning

**Steps:**
- [ ] define unit tests for config loading, folder dispatch, and per-folder artifact isolation
- [ ] define regression tests proving per-folder sequential image behavior is preserved
- [ ] define live-run proof for multiple folders with visible concurrent folder progress

**Verification:**
- [ ] validation plan proves both speedup boundary and SSOT/symmetry preservation

**Exit Criteria:**
- spec is ready for implementation planning

## Design Decisions

### Decision: Concurrency boundary is folder, not image

- context: image enrichment is currently sequential, and each note folder already behaves like an isolated review/cache unit
- choice: run folder review jobs concurrently, but keep `build_image_contexts()` sequential inside each folder
- alternatives considered:
  - keep whole batch sequential
  - run images concurrently across all folders
  - run images concurrently within each folder
- impact:
  - speedup comes from independent folder parallelism
  - per-folder progress, heading order, and incremental cache writes stay simple
  - no new locking or merge logic is needed inside one folder review

### Decision: Add one runtime knob `review_folder_concurrency`

- context: concurrency should be centrally configured, not hidden in ad hoc code paths or hard-coded thread counts
- choice: add `review_folder_concurrency` beside `patch_concurrency` in `note_refinery.yaml` and runtime config loader, with CLI override support matching existing config rules
- alternatives considered:
  - hard-code folder concurrency
  - reuse `patch_concurrency` for review too
  - add a separate environment-only setting
- impact:
  - runtime behavior stays SSOT-driven
  - review and patch concurrency remain symmetric but independently tunable
  - docs and tests can point to one canonical config path

### Decision: Reuse single-folder review implementation as inner engine

- context: current single-folder review path already handles sequential image enrichment, incremental `image_context.json` writes, cache reuse, and progress output
- choice: outer batch dispatcher calls the same single-folder review codepath for each folder instead of introducing a second review implementation
- alternatives considered:
  - split out a new parallel-specific review engine
  - duplicate review logic inside batch runner
- impact:
  - SSOT for review behavior remains in one implementation path
  - bug fixes to single-folder review automatically apply to folder-concurrent runs
  - code stays shorter and easier to reason about

### Decision: Canonical artifact ownership stays per folder

- context: concurrency is only safe if each worker owns its own artifact surface
- choice: each folder review worker writes only to its own run-root subtree, with one canonical `reports/REVIEW.md` and one canonical `reports/image_context.json` for that folder
- alternatives considered:
  - shared batch-level image cache
  - shared batch-level review artifact
  - alternate cache path for parallel mode
- impact:
  - no cross-worker cache collisions
  - partial cache reuse remains explicit and folder-local
  - downstream patch/verify/synth logic can keep current assumptions

### Decision: Progress must be symmetric at outer and inner levels

- context: once folders run concurrently, current image-only progress lines become harder to read and attribute
- choice: progress output must show both outer folder unit and inner image unit when batch folder concurrency is active
- alternatives considered:
  - keep current image-only logs
  - add separate verbose/debug-only mode
- impact:
  - user can see both folder scheduling and in-folder image movement
  - concurrent output remains attributable to one folder
  - no hidden work perception during long runs

### Decision: Stage symmetry means same contract shape, not identical retry granularity

- context: folder-level concurrency changes dispatch shape but should not change what each stage canonically owns
- choice: preserve current stage-local smallest safe unit while making folder the explicit outer review batch unit
- alternatives considered:
  - force all stages to become folder-concurrent
  - add generic cross-stage worker framework
- impact:
  - review: folder-concurrent outer loop, image-sequential inner loop, per-image persistence
  - patch: file-concurrent within current folder/batch contract
  - verify: existing batch verification contract unchanged
  - synth: existing single coupled output contract unchanged

## Invariants

- `review_folder_concurrency` has exactly one runtime source of truth after config resolution
- one folder remains one canonical review/cache unit
- images inside one folder are processed sequentially in source order
- each folder review worker writes only to its own canonical artifact paths
- no shared batch-level image cache is introduced
- folder-concurrent review must reuse existing single-folder review logic, not a duplicated variant
- cache reuse remains folder-local and explicit through canonical artifacts only
- outer concurrency must not change downstream patch, verify, or synth artifact contracts

## Acceptance Criteria

- runtime config supports `review_folder_concurrency` in same SSOT layer as `patch_concurrency`
- CLI override behavior for `review_folder_concurrency` matches existing runtime override rules
- batch review can process multiple folders concurrently while one folder still logs image progress sequentially
- a folder run never writes into another folder's `reports/` or `patched_notes/` subtree
- partial `reports/image_context.json` persistence still works during folder-concurrent review
- existing single-folder review behavior remains unchanged when `review_folder_concurrency` resolves to `1`
- no alternate cache path, batch-level image cache, or parallel-only review implementation is introduced

## Non-Goals

- per-image concurrency inside one folder
- distributed workers, queues, or external job orchestration
- redesigning patch/verify/synth around folder concurrency
- cross-folder synthesized cache sharing
- changing prompt semantics or provider/model configuration beyond one new runtime knob

## Risks and Mitigations

- risk: provider rate limits or cost spikes if too many folders run at once
  - mitigation: keep one explicit `review_folder_concurrency` knob with conservative default
- risk: concurrent logs become hard to read
  - mitigation: require folder-qualified progress lines when folder concurrency is active
- risk: accidental shared artifact writes across workers
  - mitigation: spec keeps folder-local canonical run roots and forbids shared batch cache files
- risk: duplicate review logic appears during implementation
  - mitigation: spec requires reuse of current single-folder review path as inner engine
- risk: user expects inner-folder image parallelism too
  - mitigation: spec makes sequential inner-folder behavior explicit and intentional

## Validation Plan

- proof target: runtime config has one canonical resolved value for folder review concurrency
  - method: unit test
  - evidence: `tests/test_config.py` covers file config default plus CLI override behavior
- proof target: batch review dispatches independent folders concurrently
  - method: unit test with fake client/enricher and timing-safe progress/order assertions
  - evidence: `tests/test_pipeline.py` shows two folder jobs start independently under configured worker count
- proof target: images inside one folder remain sequential
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts in-folder image call order stays source-ordered
- proof target: per-folder artifacts stay isolated
  - method: unit test
  - evidence: `tests/test_pipeline.py` proves each folder writes only its own `reports/image_context.json` and `REVIEW.md`
- proof target: single-folder review path remains canonical inner engine
  - method: inspection plus regression test
  - evidence: implementation reuses same review helper/path for `review_folder_concurrency=1` and `>1`
- proof target: live batch run shows visible folder-level concurrency and correct folder-local outputs
  - method: live run
  - evidence: one run root with multiple folder subtrees, each containing canonical `reports/REVIEW.md` and `reports/image_context.json`

## Completion Criteria

A specification item is considered complete when:

1. all Key Deliverables are satisfied
2. all downstream/child items are terminal
3. every child item is `completed` or `dropped`