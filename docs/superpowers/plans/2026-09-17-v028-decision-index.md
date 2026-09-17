# v0.2.8 Decision Index Implementation Plan

**Goal:** Use authoritative decision index for steady-state Context without historical body reads.

**Authority:** `decisions/index.yaml` is control metadata. Harness decision writes publish body/index atomically. Manual body edits require explicit `harness decision reindex`; Context does not hash historical body files on every run.

## Task 1 — Index lifecycle

- Test: first propose creates index; accept/reject/supersede update it atomically; missing index migration writes it; index/member ID mismatch fails closed.
- Implement in `decision.py`: index schema, build/rebuild helper, transactional record publication, `reindex()`.
- Add CLI `harness decision reindex` in `controlplane.py`/`cli.py`; it fully loads/validates bodies, rebuilds index atomically.
- Run `tests/test_decision.py` and decision CLI tests. Commit lifecycle.

## Task 2 — Indexed Context model

- Add `DecisionMetadata` collection to `AuthoritativeContext`.
- `FileContextSource` loads index metadata, registers index/member refs, then calls `load_decision()` only for current-task IDs and explicit IDs from current decision supersession, impact `DEC-*:` labels, interface `decision_refs`.
- Selector uses metadata for historical omitted entries; control core uses loaded current bodies only.
- Missing explicit ID, malformed index, or index/member mismatch raises Context stable fail-closed code.
- Regression fixture proves 100 historical bodies do not reach `load_decision` or serialized Context; current and explicit ref bodies do.
- Run all context suites. Commit selective source.

## Task 3 — Freshness/docs/verification

- Freshness hashes index and member names, not historical body bytes. Body mutation is not observed until reindex; document this authority boundary in contract/guide.
- Add test: reindex after direct body edit changes index freshness; direct edit alone leaves index Context unchanged by design.
- Run `pytest -q`, Ruff, diff review. Commit final changes.
