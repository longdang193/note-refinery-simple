---
layer: change
artifact_type: spec
status: proposed
template_id: detailed-specification
name: incremental-image-cache-stage-symmetry
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

# Incremental Image Cache And Stage Symmetry

## Goal

Define one bounded change that makes long-running review/pipeline stages crash-tolerant and structurally symmetric. Primary focus is incremental persistence for image enrichment during review, then a source-of-truth pass over all stages so retry, cache reuse, artifact shape, and failure recovery follow one simple invariant model.

### Triage

```text
Layer: change
Feature type: MODIFY
Summary: Add incremental image-context persistence and normalize stage contracts around shared SSOT, symmetry, and invariance rules.
Reasoning: Current review stage loses all in-flight image enrichment if batch dies before final write, while later stages already have stronger retry/repair behavior. Stage contracts are similar but not fully symmetric, which increases bespoke failure handling.
Invariants:
  - partial successful work must survive later failure
  - each stage has one canonical output path per run root
  - retries must operate on smallest safe unit for that stage
  - cache reuse must read canonical stage artifacts, not alternate copies
Dependencies:
  - existing run root layout under reports/ and patched_notes/
  - existing OpenAI-compatible LLM client
  - existing prompt/profile system
  - existing patch and synth repair paths
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

### Incremental image-context persistence contract

Define review-stage write behavior so every successfully enriched image is persisted to canonical artifact storage before next image starts.

### Stage contract symmetry table

Define one canonical contract per stage: unit of work, primary human artifact, machine-readable artifact, retryable unit, and cache reuse input.

### SSOT artifact rules

Define which paths are canonical for reuse, repair, and downstream reads so no stage invents alternate copies or hidden state.

### Minimal optimization set

Define smallest code-shape changes needed to improve symmetry without adding a new orchestration framework or speculative abstraction layer.

## Task/Wave Breakdown

### Wave 1: Source-first analysis

**Purpose:**
- define current artifact flow, write timing, and retry boundaries before changing stage contracts

**Steps:**
- [ ] inspect review image-enrichment write timing and current `image_context.json` behavior
- [ ] inspect patch, verify, and synth retry/repair behavior already present
- [ ] identify stage outputs already acting as canonical cache inputs
- [ ] record where stage behavior is symmetric already and where it diverges

**Verification:**
- [ ] current-state artifact and retry map is explicit enough to support one concrete symmetry model

**Exit Criteria:**
- no proposed optimization depends on hidden assumptions about stage boundaries

### Wave 2: Decision closure

**Purpose:**
- resolve incremental cache shape, canonical artifact rules, and minimum shared behavior across stages

**Steps:**
- [ ] define incremental write contract for image enrichment
- [ ] define canonical stage contract table
- [ ] define where repair should stay stage-local versus where no retry should be added
- [ ] define smallest reusable helpers that preserve symmetry without over-engineering

**Verification:**
- [ ] each stage has explicit source, sink, retry unit, and downstream read contract

**Exit Criteria:**
- design is bounded, crash-tolerant, and avoids new framework-level abstraction

### Wave 3: Validation and approval readiness

**Purpose:**
- make proof expectations explicit before implementation planning

**Steps:**
- [ ] define unit tests for incremental image persistence and resume behavior
- [ ] define regression tests for stage repair symmetry
- [ ] define live-run proof required for cached rerun and partial-progress survival

**Verification:**
- [ ] validation plan proves both crash tolerance and SSOT reuse behavior

**Exit Criteria:**
- spec is ready for implementation planning

## Design Decisions

### Decision: Persist image enrichment incrementally to canonical artifact path

- context: review currently writes `reports/image_context.json` only after full image batch completes, so one late failure can discard many successful image enrichments
- choice: after each image task finishes, rewrite canonical `reports/image_context.json` atomically with all collected contexts so far
- alternatives considered:
  - keep end-of-batch write only
  - write one temporary file per image and merge later
  - add external database or queue-backed cache
- impact:
  - crash after image `N` preserves images `1..N`
  - rerun with `--reuse-image-context-from` can reuse partial successful work immediately
  - implementation stays simple because artifact path does not change

### Decision: Keep `reports/image_context.json` as SSOT for review image cache

- context: cache reuse already points at `reports/image_context.json`; adding alternate image-cache paths would create split truth
- choice: preserve existing artifact name and path as single source of truth for enriched image context
- alternatives considered:
  - add `image_context.partial.json`
  - add stage-specific cache directories
  - move image cache into config-managed state
- impact:
  - no CLI contract expansion beyond existing reuse flags
  - downstream review and patch logic continue reading one known path
  - partial-progress persistence becomes invisible to callers because canonical path stays stable

### Decision: Define one symmetric stage contract model

- context: stages already share shape informally, but retry/caching behavior is uneven and partly implicit
- choice: every stage must declare five canonical facts: unit of work, primary human artifact, machine artifact, retryable unit, and cache/reuse input
- alternatives considered:
  - keep stage-specific behavior undocumented and ad hoc
  - introduce large generic stage framework in code first
- impact:
  - implementation can add small helpers while preserving simple mental model
  - future retries or cache features can be judged against same invariants

### Decision: Smallest safe retryable unit differs by stage but must be explicit

- context: symmetry does not mean identical retry granularity; patch is naturally per-file, review-image is per-image, synth is whole-response repair
- choice: preserve stage-local smallest safe unit instead of forcing fake uniformity
- alternatives considered:
  - whole-run retry for every failure
  - per-file retry for every stage even where stage output is whole-batch
- impact:
  - review image enrichment retries/persistence operate per image
  - patch retries operate per file
  - verify remains batch-level with file extraction for selective repair
  - synth remains whole-response repair because output is one coupled JSON object

### Decision: Prefer tiny shared helpers over new orchestration layer

- context: user wants simplicity and current pipeline already works with bounded targeted fixes
- choice: introduce only low-level reusable helpers where symmetry is real, such as atomic JSON write and repair-wrapper patterns
- alternatives considered:
  - new stage base class
  - generalized state machine for all stages
  - config-heavy retry policy layer
- impact:
  - keeps code boring and local
  - enforces SSOT through helpers and contracts, not through framework ceremony

### Decision: Make verify machine-readable enough to remain canonical for selective repair

- context: patch selective repair already depends on parsing `VERIFY.md`; this works but is weaker than explicit sidecar data
- choice: keep `VERIFY.md` as human artifact, but allow optional canonical sidecar such as `reports/verify_flags.json` only if parser fragility becomes recurring cost
- alternatives considered:
  - require sidecar immediately
  - keep markdown-only forever regardless of drift
- impact:
  - short-term implementation can stay small
  - spec leaves one bounded extension point if verify parsing becomes main asymmetry hotspot

## Invariants

- each stage writes to one canonical artifact location under current run root
- downstream stages and reuse flags must read canonical stage artifacts only
- successful sub-unit work must be preserved before later sub-unit failure when stage granularity allows it
- retry scope must be smallest safe unit for that stage and must not invalidate unrelated accepted work
- human-readable artifacts and machine-readable artifacts for same stage must describe same underlying state
- no optimization may introduce second authoritative cache path for same stage output
- symmetry improvements must reduce bespoke behavior, not add new framework complexity

## Acceptance Criteria

- review image enrichment writes `reports/image_context.json` incrementally after each successful image, using atomic replacement so file never lands half-written
- if review crashes after some images complete, rerun can reuse saved partial `image_context.json` without re-enriching completed images
- stage contract table exists in code comments/docs/plan and clearly maps review, patch, verify, and synth to canonical unit/artifact/retry rules
- synth malformed JSON path uses same repair principle as patch malformed JSON path
- README explains canonical artifact reuse behavior for partial review cache and rerun commands
- no new alternate cache directory, queue, or database is introduced for this change

## Non-Goals

- building generic workflow engine for all stages
- adding persistent database for cache storage
- mathematically verifying formulas beyond current LLM-driven scope
- redesigning prompt system or model/provider configuration
- introducing distributed concurrency, resumable job scheduler, or external worker service

## Risks and Mitigations

- risk: incremental writes may increase disk churn during image-heavy runs
  - mitigation: write one canonical file atomically and only after each successful image; accept small extra I/O to avoid losing expensive API work
- risk: partial cache may contain mixed old/new image contexts if source folder changes between runs
  - mitigation: cache reuse remains explicit via CLI flag; implementation plan should define path/root consistency checks before trusting reused artifact
- risk: pushing symmetry too far may create over-abstracted stage framework
  - mitigation: spec explicitly limits implementation to tiny helpers and local refactors only
- risk: verify remains less machine-readable than other stages
  - mitigation: document optional sidecar as deferred extension, not immediate requirement

## Validation Plan

- proof target: image contexts survive mid-batch interruption
  - method: unit test with fake enricher that succeeds once then raises
  - evidence: `tests/test_pipeline.py` proves `reports/image_context.json` contains completed first image after failure
- proof target: rerun can load partial cached image context from canonical path
  - method: unit test
  - evidence: CLI/pipeline test showing cached image context skips already saved enrichment work
- proof target: canonical image cache file is always valid JSON after each incremental write
  - method: unit test
  - evidence: repeated load/parse checks during simulated multi-image review
- proof target: synth malformed JSON follows same repair principle as patch malformed JSON
  - method: unit test
  - evidence: passing regression test for synth repair path
- proof target: full cached rerun completes after prior mid-stage failure scenario
  - method: live run
  - evidence: run artifacts under new run root include `REVIEW.md`, `VERIFY.md`, `SYNTHESIS.md`, `concept_map.json`, and patched notes
- proof target: README documents canonical reuse behavior clearly enough for manual rerun use
  - method: inspection
  - evidence: usage section includes incremental cache/rerun commands and stage artifact overview

## Completion Criteria

Specification is complete when:

1. incremental image persistence contract is explicit and bounded
2. stage symmetry model defines canonical unit, artifact, and retry scope for review, patch, verify, and synth
3. SSOT rules forbid duplicate authoritative artifact paths for same stage state
4. validation plan proves crash tolerance, cache reuse, and repair symmetry without requiring broader architecture redesign
