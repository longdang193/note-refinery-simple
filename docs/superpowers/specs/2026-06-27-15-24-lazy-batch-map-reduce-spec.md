---
layer: change
artifact_type: spec
status: proposed
template_id: detailed-specification
name: lazy-batch-map-reduce
parent_workstream: none
targets:
  - note_refinery_simple/cli.py
  - note_refinery_simple/pipeline.py
  - tests/test_cli.py
  - tests/test_pipeline.py
  - README.md
related_features: []
related_stages: []
---

# Lazy Batch Map/Reduce For Patch, Verify, And Synthesize

## Goal

Define smallest safe batch contract after folder-concurrent review: patch each discovered folder independently, then verify and synthesize once across complete patched batch. Design must stay simple, use one batch identity, and avoid new manifest forests or generic orchestration framework.

### Triage

```text
Layer: change
Feature type: MODIFY
Summary: Add lazy batch-root support for patch, verify, and synthesize by combining per-folder map stages with one batch barrier and one global reduce output.
Reasoning: Current product supports batch folder input for review only. Users can review many folders together, but later stages still require manual per-folder calls. Smallest useful fix is to keep review/patch local to each folder and make verify/synthesize consume full patched batch from one batch root.
Invariants:
  - batch membership is defined once and stays fixed for all later stages
  - one folder remains one canonical local processing unit
  - one batch produces one batch VERIFY.md and one batch SYNTHESIS.md
  - local artifacts stay inside folder subtree
  - global artifacts stay at batch root
Dependencies:
  - existing batch folder review layout
  - existing per-folder REVIEW.md, image_context.json, and patched_notes outputs
  - existing single-folder patch, verify, and synthesize prompts
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

### One canonical batch identity contract

Define one small `batch_manifest.json` at batch root as single source of truth for which folders belong to batch and where their canonical local artifacts live.

### Batch patch map contract

Define how `patch` accepts batch root, fans out folder patch runs, and writes only folder-local patched outputs.

### Batch verify reduce contract

Define how `verify` accepts batch root and emits one root-level `reports/VERIFY.md` across all patched folders in batch.

### Batch synthesize reduce contract

Define how `synthesize` accepts batch root and emits one root-level `reports/SYNTHESIS.md` plus machine-readable synthesis artifacts across all patched folders in batch.

## Task/Wave Breakdown

### Wave 1: Source-first analysis

**Purpose:**
- define shipped batch review shape and later-stage gaps before extending contracts

**Steps:**
- [ ] inspect current batch review folder layout and canonical outputs
- [ ] inspect current single-folder `patch`, `verify`, and `synthesize` entry rules
- [ ] confirm which local artifacts are already sufficient to drive later batch stages
- [ ] identify smallest new root artifact needed to freeze batch membership

**Verification:**
- [ ] current source shows one small batch manifest is enough and per-folder manifests are not required

**Exit Criteria:**
- no design step depends on speculative orchestration files or hidden state

### Wave 2: Decision closure

**Purpose:**
- resolve batch identity, stage topology, and barrier behavior

**Steps:**
- [ ] define `batch_manifest.json` fields and creation point
- [ ] define batch `patch` folder fan-out behavior
- [ ] define batch `verify` barrier and output contract
- [ ] define batch `synthesize` barrier and output contract

**Verification:**
- [ ] each stage has one explicit input contract and one explicit output contract

**Exit Criteria:**
- design is symmetric by scope, not overbuilt by framework

### Wave 3: Validation and approval readiness

**Purpose:**
- make proof expectations explicit before implementation planning

**Steps:**
- [ ] define tests for batch manifest creation and reuse
- [ ] define tests for batch patch dispatch and barrier enforcement
- [ ] define tests for one batch `VERIFY.md` and one batch `SYNTHESIS.md`
- [ ] define README proof for user-facing stage overview and commands

**Verification:**
- [ ] validation plan proves batch membership, local/global artifact split, and stage usability

**Exit Criteria:**
- spec is ready for implementation planning

## Design Decisions

### Decision: Batch means input set, not worker chunk

- context: user asked whether batch means all folders or only concurrency groups
- choice: one batch is all folders discovered from one run input set; concurrency only changes execution order
- alternatives considered:
  - define batch from worker chunking
  - redefine batch per stage
- impact:
  - batch identity stays stable across review, patch, verify, and synthesize
  - `review_folder_concurrency` changes speed only, not membership

### Decision: Add one root `batch_manifest.json`

- context: later stages need stable folder membership without rediscovery drift
- choice: write one small `batch_manifest.json` at batch root listing folder ids and relative output paths
- alternatives considered:
  - rediscover folders from filesystem on each stage
  - add per-stage manifests under every folder
  - add orchestration database or queue state
- impact:
  - one file becomes SSOT for batch membership
  - later stages can trust batch shape without extra sidecars
  - implementation stays small

### Decision: Keep folder-local truth local

- context: review and patch work independently per folder
- choice: each folder keeps canonical local artifacts under its own subtree, such as `reports/REVIEW.md`, `reports/image_context.json`, and `patched_notes/`
- alternatives considered:
  - move all artifacts to batch root
  - duplicate local artifacts into root summaries
- impact:
  - current folder contract stays mostly unchanged
  - patch can reuse current single-folder engine
  - no shared write collisions

### Decision: Patch is map, verify and synthesize are reduce

- context: review and patch can run folder-by-folder, but verify and synthesize need whole patched corpus for cross-folder checks and linking
- choice: batch `patch` fans out over folders; batch `verify` and `synthesize` run once over full patched batch
- alternatives considered:
  - keep every later stage per folder only
  - force every stage into identical per-folder topology
  - build generic DAG/orchestrator abstraction
- impact:
  - topology matches real data scope
  - user gets one batch `VERIFY.md` and one batch `SYNTHESIS.md`
  - code stays close to existing stage semantics

### Decision: Hard barrier before batch reduce stages

- context: global verify/synthesize become misleading if some folders are missing from patched corpus
- choice: batch `verify` and batch `synthesize` require every folder in `batch_manifest.json` to have canonical `patched_notes/` ready; otherwise fail with explicit missing-folder list
- alternatives considered:
  - silently skip missing folders
  - auto-verify partial batches
  - create partial/complete mode now
- impact:
  - simplest safe behavior
  - no silent cross-folder blind spots
  - partial-mode complexity is deferred until proven needed

### Decision: Reuse existing single-folder logic as inner engine

- context: current product already knows how to patch one folder and verify/synthesize one folder
- choice: batch stages wrap existing folder-stage helpers where possible instead of introducing separate batch-only engines
- alternatives considered:
  - duplicate logic into new batch classes
  - build generic worker framework first
- impact:
  - shortest diff
  - lower bug risk
  - single-folder behavior remains canonical

### Decision: Global outputs live at batch root only

- context: one folder should not accidentally become home for batch-wide conclusions
- choice: batch `verify` writes `reports/VERIFY.md` at batch root; batch `synthesize` writes `reports/SYNTHESIS.md` and machine-readable synthesis files at batch root
- alternatives considered:
  - store global outputs under arbitrary first folder
  - write duplicate global outputs under each folder
- impact:
  - local and global scopes remain clean
  - user can find batch-wide outputs in one place

## Invariants

- one batch is all folders discovered from one input set
- `batch_manifest.json` is canonical SSOT for batch membership
- folder identity remains stable from review through synthesize
- folder-local stages write only inside folder subtree
- batch-global stages write only at batch root
- batch `verify` and batch `synthesize` never infer membership from ad hoc folder rediscovery when manifest exists
- batch `verify` and batch `synthesize` require complete patched set by default
- `review_folder_concurrency` affects scheduling only, not batch identity

## Acceptance Criteria

- batch review writes one root `batch_manifest.json` when input path is folder-of-folders
- batch `patch` accepts that batch root and patches every manifest-listed folder without user needing per-folder commands
- batch `verify` accepts that batch root and writes exactly one `reports/VERIFY.md`
- batch `synthesize` accepts that batch root and writes exactly one `reports/SYNTHESIS.md`
- batch `verify` fails clearly when one or more manifest-listed folders do not yet have canonical patched outputs
- batch `synthesize` fails clearly when batch `verify` prerequisites are missing
- single-folder commands keep working unchanged
- README explains that batch means full discovered folder set, not concurrency chunk

## Non-Goals

- partial-batch verify or synthesize mode
- per-folder `VERIFY.md` or per-folder `SYNTHESIS.md` in batch mode
- per-folder stage manifests
- workflow engine, queue system, or generic DAG framework
- cross-batch deduplication or long-term knowledge graph
- changing prompt semantics beyond what batch reduce stages need for full patched corpus input

## Risks and Mitigations

- risk: folder rediscovery drifts from original batch after manual edits
  - mitigation: root `batch_manifest.json` becomes canonical membership source
- risk: users expect verify to run after patching only some folders
  - mitigation: fail fast with explicit missing-folder list and document hard barrier
- risk: batch root and folder root contracts get mixed
  - mitigation: keep local artifacts under folder subtree and global artifacts under root `reports/`
- risk: implementation duplicates existing single-folder stage logic
  - mitigation: spec requires batch wrappers over existing inner helpers where possible

## Validation Plan

- proof target: batch identity stays stable after review
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts batch review writes one `batch_manifest.json` with all discovered folder ids and relative paths
- proof target: batch `patch` reuses manifest membership rather than rediscovery
  - method: unit test
  - evidence: `tests/test_pipeline.py` shows patch processes manifest-listed folders even if filesystem order differs
- proof target: batch `verify` writes one root-level report across all patched folders
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts `reports/VERIFY.md` exists at batch root and no per-folder verify report is created in batch mode
- proof target: batch `verify` enforces hard barrier
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts clear failure when any manifest-listed folder lacks `patched_notes/`
- proof target: batch `synthesize` writes one root-level synthesis output across all patched folders
  - method: unit test
  - evidence: `tests/test_pipeline.py` asserts `reports/SYNTHESIS.md` and machine-readable synthesis artifacts exist at batch root
- proof target: single-folder behavior remains unchanged
  - method: regression test
  - evidence: existing single-folder CLI and pipeline tests still pass unchanged
- proof target: docs explain stage topology clearly
  - method: inspection
  - evidence: `README.md` includes stage overview and commands for one-folder mode and batch mode

## Completion Criteria

Specification is complete when:

1. one canonical batch identity, one batch patch map contract, one batch verify reduce contract, and one batch synthesize reduce contract are all explicitly defined
2. invariants and acceptance criteria are testable without adding framework-level machinery
3. implementation can proceed with one bounded plan without reopening batch scope semantics
