---
layer: change
artifact_type: spec
status: proposed
template_id: detailed-specification
name: batch-review-per-file-patch-topic-guard
parent_workstream: none
targets:
  - note_refinery_simple/pipeline.py
  - tests/test_pipeline.py
  - prompts/profiles/default/patch.md
  - prompts/profiles/default/verify.md
related_features: []
related_stages: []
---

# Batch Review With Per-File Patch, Topic Guard, And Concurrent Repair

## Goal

Define simple batch-processing architecture that keeps cross-file review context while preventing patched lecture content from landing in wrong file envelope. Design must preserve usable runtime for folder-scale runs by patching files concurrently, then verifying batch output before synthesis.

### Triage

```text
Layer: change
Feature type: MODIFY
Summary: Replace batch patch write path with per-file concurrent patch workers plus topic guard and selective repair.
Reasoning: Current batch review works, but batch patch payload can swap lecture content across file envelopes and is hard to recover safely.
Invariants:
  - one patched file maps to exactly one source markdown file
  - lecture identity must stay aligned with original file identity
  - verified files must not be repatched unless later validation flags them
Dependencies:
  - existing LLM client
  - existing prompt loading system under prompts/
  - existing verify and synthesis stages
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

### Per-file patch execution contract

Define patch stage so each source markdown file is patched in its own LLM session, using shared batch review as input but producing one output file only.

### Topic guard acceptance gate

Define lightweight acceptance gate that rejects obvious topic swaps or wrong-file payloads before patched content is written.

### Concurrent worker model

Define bounded concurrency for per-file patch and selective repair so folder-scale runs stay practical without returning to risky batch patch payloads.

### Selective repair and validation flow

Define batch verify plus targeted rework path for only flagged files, followed by synthesis over accepted patched notes.

## Task/Wave Breakdown

### Wave 1: Source-first analysis

**Purpose:**
- define current failure mode, current patch flow, and acceptance boundaries before changing orchestration

**Steps:**
- [ ] inspect current `write_patched_notes` and `_collect_patched_files` flow
- [ ] record live-run evidence showing wrong-file content placement
- [ ] identify current prompt, retry, and cleanup boundaries that remain reusable

**Verification:**
- [ ] failure mode is stated concretely enough to test against

**Exit Criteria:**
- no key design decision depends on unstated assumptions about why batch patch drift happened

### Wave 2: Decision closure

**Purpose:**
- define replacement patch orchestration, topic guard rules, and concurrency limits

**Steps:**
- [ ] define per-file patch prompt contract
- [ ] define topic guard inputs, checks, and failure behavior
- [ ] define worker pool behavior, retry scope, and artifact write timing
- [ ] define selective repair trigger points after verify

**Verification:**
- [ ] each design choice has explicit reason and observable impact

**Exit Criteria:**
- design removes cross-file payload ambiguity while keeping runtime bounded

### Wave 3: Validation and approval readiness

**Purpose:**
- make proof expectations explicit before implementation planning

**Steps:**
- [ ] define tests for wrong-file protection and concurrent worker safety
- [ ] define live-run evidence expected after rollout
- [ ] define documentation updates for batch-folder usage and progress reporting

**Verification:**
- [ ] validation plan proves both correctness and runtime behavior

**Exit Criteria:**
- spec is ready for implementation plan handoff

## Design Decisions

### Decision: Keep review as shared batch context

- context: review stage benefits from cross-file consistency checks and image-enrichment context across whole folder
- choice: keep one batch review over all selected markdown files
- alternatives considered:
  - per-file review only
  - fully independent file pipelines with no shared context
- impact:
  - retains cross-file inconsistency detection
  - avoids duplicating image-enrichment or review overhead per file

### Decision: Replace batch patch payload with per-file patch sessions

- context: single JSON payload across many files allowed content from one lecture to appear under another lecture filename
- choice: patch each markdown file in its own session using batch `REVIEW.md`, original file content, and file-local image context
- alternatives considered:
  - keep batch patch and harden parser only
  - keep batch patch and add post-hoc filename remapping
- impact:
  - removes multi-file output ambiguity from patch stage
  - makes retries local to one file
  - increases LLM call count, which must be offset with bounded concurrency

### Decision: Add topic guard before accepting patched file

- context: per-file patch lowers risk but does not eliminate lecture drift or model hallucinated topic replacement
- choice: run cheap topic guard on each patched candidate before write
- alternatives considered:
  - trust patch output without guard
  - rely only on later batch verify
  - use LLM verifier for every candidate as first-line guard
- impact:
  - catches obvious envelope swaps early
  - keeps expensive verification for batch-level pass rather than first-line filtering
  - topic guard should prefer deterministic checks first, with optional LLM fallback only when deterministic result is inconclusive

### Decision: Use bounded patch concurrency with low default

- context: per-file patching serially is safe but slow on folders with many lecture notes
- choice: run per-file patch workers concurrently with default `patch_concurrency: 3`
- alternatives considered:
  - serial execution only
  - high default concurrency `>5`
  - configurable unbounded concurrency
- impact:
  - shortens batch runtime materially
  - limits provider overload, rate-limit bursts, and noisy log interleaving
  - keeps progress readable with file-scoped messages

### Decision: Selective repair only for flagged files

- context: once one file passes topic guard and file write, whole-batch retry should not risk already-accepted files
- choice: after batch verify, only files named in guard failures or verify regressions enter repair queue
- alternatives considered:
  - repatch whole folder on any failure
  - stop entire run on first failed file
- impact:
  - preserves accepted outputs
  - reduces cost and runtime on partial failures
  - aligns with user goal of practical batch processing rather than fragile all-or-nothing runs

### Decision: Synthesis remains last stage over accepted patched set

- context: synthesis should operate on stable, verified notes rather than on speculative intermediate patches
- choice: run synthesis only after patch acceptance and batch verify complete
- alternatives considered:
  - synthesize immediately after patch stage
  - synthesize per file and merge later
- impact:
  - synthesis sees final cleaned notes only
  - reduces propagation of file-placement regressions into cross-source teaching note output

## Invariants

- each source markdown file has exactly one canonical patched output path relative to run root
- patch worker for file `X` may only emit content for file `X`
- accepted patched file content must pass topic guard before write
- topic guard rejection must not overwrite prior accepted content for that file
- retries remain file-local; no retry may force rewrite of unrelated accepted files
- batch verify operates on full accepted patched set and may flag files for selective repair only
- synthesis reads only accepted patched files plus batch review and batch verify outputs
- progress output must show file-level activity during long batch runs

## Acceptance Criteria

- folder run with multiple markdown files completes patch stage without requiring one multi-file patch payload
- if patcher returns content whose dominant topic conflicts with source lecture identity, topic guard rejects it and file is retried or marked failed
- concurrent patch run does not allow one worker to overwrite another worker's output path
- verify stage can name specific files for selective repair without discarding accepted outputs
- README documents batch-folder behavior, per-file patching, verification, and synthesis stages
- runtime config exposes bounded patch concurrency and related retry settings through existing SSOT config surface

## Non-Goals

- mathematically proving all formulas are correct
- building vector database, graph database, or long-term knowledge store for this change
- replacing batch review with per-file review
- introducing distributed job queue or external orchestration service
- guaranteeing zero hallucination; design only reduces drift and catches obvious failures earlier

## Risks and Mitigations

- risk: per-file patching increases token and request volume
  - mitigation: keep batch review shared, use low default concurrency, retry only flagged files
- risk: deterministic topic guard may reject valid heavily rewritten notes
  - mitigation: use layered guard with cheap lexical checks first and optional fallback review when score is inconclusive
- risk: concurrent logs become noisy or look stalled
  - mitigation: require file-scoped progress messages with worker stage markers and completion counts
- risk: verify output may describe regressions without machine-readable file extraction
  - mitigation: define stable verifier phrasing or structured section markers for selective repair parsing

## Validation Plan

- proof target: one-file fallback still accepts sole payload even when wrong filename key is returned
  - method: unit test
  - evidence: passing regression test in `tests/test_pipeline.py`
- proof target: empty single-file fallback can recover through bounded retries
  - method: unit test
  - evidence: passing regression test in `tests/test_pipeline.py`
- proof target: per-file patch worker cannot write content into unrelated file envelope
  - method: unit test plus inspection of worker contract
  - evidence: tests that only requested file path is accepted and written
- proof target: topic guard rejects obvious lecture swaps such as VNS/LNS content inside optimization-introduction file envelope
  - method: unit test with swapped lecture sample
  - evidence: test fixture showing guard rejection result
- proof target: concurrent workers do not collide on output paths and still emit complete patched set
  - method: unit test with multi-file concurrent mock run
  - evidence: passing test proving all expected files written once
- proof target: selective repair retries only files flagged by guard or verify
  - method: unit test with mixed pass/fail batch
  - evidence: call log showing retry prompts only for flagged files
- proof target: live batch run no longer produces known file-placement regression
  - method: live run comparison
  - evidence: `reports/VERIFY.md` in new run no longer reports wrong-file-envelope regression seen in `live-test-mineru-run-profile-default-full-2026-06-24/reports/VERIFY.md`
- proof target: user can see work progressing during batch run
  - method: live run inspection
  - evidence: console output showing per-file patch start, guard pass/fail, retry, verify, and synthesis progress

## Completion Criteria

Specification is complete when:

1. batch review, per-file patch, topic guard, concurrency, selective repair, batch verify, and final synthesis are all bounded in explicit contracts
2. invariants and acceptance criteria are testable without hidden assumptions
3. implementation can proceed via follow-up plan without reopening core architecture questions
