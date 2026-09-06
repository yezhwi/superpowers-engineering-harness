# Evidence Timeout Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure timeout output is always textual and timeout records carry compatible structured error detail.

**Architecture:** Add one private output normalizer in `collect_evidence`; use it on subprocess results before tailing. Extend evidence schema with optional `error_detail` while preserving existing `error` string.

**Tech Stack:** Python stdlib, JSON Schema, pytest.

**Spec:** `DEC-005 evidence-timeout-error-shape`

## Global Constraints

- Preserve `error: EVIDENCE_COMMAND_TIMEOUT`.
- Decode bytes with replacement, never raise on malformed output.
- No public execution-policy changes.

---

### Task 1: Normalized timeout record

**Files:**
- Modify: `src/harness/collect_evidence.py`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- Produces: private `_text_output(value: str | bytes | None) -> str`.
- Produces: timeout `error_detail` mapping with `code`, `kind`, `timeout_seconds`.

- [ ] Write failing byte-output timeout test.
- [ ] Run exact test; expect missing detail or bytes tail failure.
- [ ] Add minimal normalizer and timeout detail.
- [ ] Run exact test; expect pass.

### Task 2: Schema compatibility

**Files:**
- Modify: `src/harness/schemas/evidence.schema.json`
- Modify: `tests/test_evidence.py`

- [ ] Write failing schema validation test for timeout detail.
- [ ] Run exact test; expect schema rejection.
- [ ] Add optional closed `error_detail` schema.
- [ ] Run focused evidence tests and wheel build.
