# v0.2.8 Important Review Fixes Design

## Scope

Resolve Important findings 3–7 from `docs/Superpowers-Engineering-Harness-v0.2.8-正式CodeReview报告.md` against current HEAD. Current HEAD already resolves both report Blocking findings.

## Invariants

1. Historical decision bodies are not deserialized or projected unless current task owns or explicitly references them.
2. Every canonical decision remains a byte-hashed freshness input; omitted body loading does not weaken stale detection.
3. FAST skips RED only with a valid persisted existing-implementation verification record.
4. Contract labels and repository file paths remain separate typed fields.
5. `requires_reproduction` does not mutate task state; task remains `CLASSIFIED` and user enters existing finding/reproduce workflow.

## Decision Source Loading

Split decision processing into two phases:

- Byte-read and hash every direct canonical `decisions/DEC-*.yaml` member for freshness.
- Scan YAML nodes/events for only top-level metadata required to identify ID, task ownership, status, and cross-task references; do not construct full Python records for historical decisions.
- Parse full YAML bodies only for current-task decisions and decisions explicitly referenced through supported dependency edges.

Unreferenced historical decisions remain omitted with a content-bound Layer 2 reference, but their body is not deserialized or projected. Duplicate IDs, malformed metadata, or missing explicit references fail closed. Collection membership and every canonical decision content hash remain in freshness versions. This does not claim zero file I/O: byte hashing remains required to detect arbitrary historical content edits.

This change is decision-only. Findings, interface contracts, and evidence retain current source loading because they carry separate control semantics.

## FAST Existing-Implementation Verification

Add one shared ordered resolver for accepted GREEN unit-test evidence paths:

1. `evidence/fast-green-unit-test.json`
2. `evidence/unit-test.json`

Both `verify-existing` and Light Gate use resolver. Light Gate skips RED only when both `verification_mode: existing_implementation` and a schema-valid `existing_verification` record with allowed conclusion exist. Otherwise it follows normal RED/GREEN checks.

`requires_reproduction` remains a command rejection with no state write. Documentation directs user to create or resume a finding and use normal reproduce workflow.

Implementation Contract documents this narrowly scoped FAST exception, including required persisted verification record.

## Typed Review Scope Schema

`diagnosability-review-evidence.schema.json` rejects `DEC-*` labels in `review_scope.files`. `contract_refs` accepts non-empty strings. Existing artifact read compatibility remains in `claimed_scope_sets()`, which migrates legacy labels into contract refs. New writes and schema validation cannot mix these types.

## Tests and Verification

Use test-first changes:

- alternate GREEN filename passes both verify-existing and Light Gate;
- bare or malformed existing-mode record does not skip RED;
- `DEC-*` in files is rejected and valid contract refs accepted;
- hundreds of historical decision fixture bodies are neither fully deserialized nor serialized;
- current and explicit reference decision bodies remain loaded; malformed/missing dependencies fail closed;
- historical body mutation still makes context stale.

Run affected context, gate, verify-existing, diagnosability, schema suites; then full `pytest`, Ruff, and diff review.
