# Control-Plane Contract Repair Design

## Goal

Repair recovery ownership, evidence receipt persistence, evidence input validation, diagnosability state guidance, and missing automated-coverage diagnostics without weakening proof freshness or protected-path safety.

## Scope

- `harness impact adopt-path` must authorize an adopted recovered path for plan-surface proof while leaving every non-adopted user path protected.
- Each newly collected evidence result must have an immutable receipt. A later run with same command and covered tests must not replace bytes referenced by an existing plan proof.
- `harness evidence run --covered-test-case` must reject values outside `TC-<number>` before command execution or receipt persistence.
- Diagnosability skill and engineering-harness workflow must direct Q3, plus Q2 when `observability.required: true`, to run diagnosability review from `VERIFYING`; CLI continues accepting `VERIFYING` and `REVIEWING`.
- Plan-proof diagnostics for automated cases must name each missing contract case and pytest node ID.

## Non-goals

- Do not weaken fresh evidence checks, proof receipt digest checks, or protection for unadopted user paths.
- Do not change automated test coverage semantics.
- Do not add a complexity-review schema.

## Design

### Recovery ownership

Add versioned protection snapshots to `risk.user_changes`: v2 contains `paths`, `path_fingerprints`, and aggregate `fingerprint`; v1 remains existing `{paths, fingerprint}`. `protected_path_fingerprints(paths)` computes one deterministic v2 path contribution using Git-only queries: path name plus relative-HEAD binary diff, or `git hash-object -- <path>` content object ID when no diff. This approved v2 digest migration leaves legacy v1 raw-byte contributions unchanged. Context and normal callers both compute current contributions; neither substitutes persisted contributions for current content. `aggregate_protected_path_fingerprints(mapping)` deterministically combines those v2 contributions.

Add one task-aware `protected_user_changes_fingerprint(user_changes)` function. For v1 records it uses unchanged legacy `protected_paths_fingerprint(paths)` behavior. For v2 it computes current path contributions and aggregates them with `aggregate_protected_path_fingerprints`. Classification scans `protected_path_fingerprints` exactly once, persists that mapping, and aggregates that same mapping using `aggregate_protected_path_fingerprints`; it must not rescan between per-path and aggregate construction. FAST user-change checks and `mechanical_surface_facts` call this same function and compare its current aggregate with stored aggregate. Thus v1 records retain existing behavior, while unchanged unadopted v2 paths retain equal historical/current contributions after another path is adopted.

`harness impact adopt-path <path>` performs one atomic current-task update only when `<path>` is currently protected:

1. add `<path>` to `scope.owned_paths`;
2. remove `<path>` from `scope.protected_user_paths`;
3. remove `<path>` from proof-protection set `risk.user_changes.paths` and from `risk.user_changes.path_fingerprints`;
4. recompute `risk.user_changes.fingerprint` only from remaining historical per-path digests.

For a v1 record lacking `path_fingerprints`, adoption first computes its v1 current aggregate through `protected_user_changes_fingerprint` and compares it to stored fingerprint. Equal means current content still equals classification baseline: it derives current per-path contributions, marks record v2, computes v2 aggregate, applies steps 1–4, and persists all fields together. Unequal fails without writes as `USER_CHANGE_BASELINE_STALE`; it never replaces historical baseline with current bytes. If `<path>` is not protected, `adopt-path` retains existing no-baseline-mutation behavior.

Plan reconciliation and automatic plan proof continue to read `risk.user_changes` for their protected set. Thus an adopted recovered path is eligible as a surface; every unadopted path retains historical member and content protection. `quality_gate` FAST user-change checks, `plan_markdown` target rejection, and `architecture_store` exclusion behavior continue reading `risk.user_changes.paths`; they therefore observe adopted paths as task-owned and unadopted paths as user-owned.

### Immutable evidence receipts

Evidence identity remains `{type}-{identity12}`. First receipt keeps existing `{identity}.json` filename; later non-reuse collections allocate `{identity}-2.json`, `{identity}-3.json`, and so on, choosing lowest unused positive suffix. Existing receipt bytes are never overwritten.

`--reuse-if-valid` scans matching fresh generic or task GREEN receipts across evidence directory using `can_reuse_evidence` equality: type, command, scope, covered tests, covered test cases, phase, HEAD, workspace fingerprint, and runtime all match. Task phase records carry optional schema-validated `phase: red|green` metadata. Only successful generic or task GREEN records are reusable. RED and finding proofs always rerun. Legacy task GREEN records lacking phase metadata fail reuse closed and receive a new immutable receipt. Collector, FAST gate and automatic proof use shared `evidence_receipt_order`: highest numeric suffix, with unsuffixed filename ordered before suffix `2`, and lexical reference breaking equal-order ties. A 12-hex related identity is not a numeric receipt suffix, including when the digest contains only digits. Without this flag, collection always writes next immutable receipt.

Automatic proof first folds fresh candidates by coverage mask, retaining highest suffix receipt for each equal mask. It applies `_MAX_CANDIDATES` and minimum-cover selection only after this fold. Therefore repeated equivalent evidence neither triggers `PLAN_AUTO_LIMIT_EXCEEDED` nor `PLAN_AUTO_PROOF_AMBIGUOUS`; distinct non-equivalent minimum covers retain existing ambiguity refusal.

Plan proof continues binding exact receipt bytes. When receipt bytes no longer match, `PLAN_PROOF_MISSING` keeps existing code and `recover_to=VERIFYING`. Its message names stale evidence ref and prints one `harness plan refresh-proof <item> --evidence <ref>` command containing every evidence reference currently bound to that item, because refresh replaces rather than appends the item's evidence list.

### Input validation

Shared evidence input validation checks every `--covered-test-case` against `^TC-[0-9]+$`. Any invalid value returns exit code 2 with `COVERED_TEST_CASE_INVALID` before subprocess execution or evidence-file write; no supplied value runs partially. Both `harness evidence run` and `collect_evidence` use this same validation path.

### Review workflow

Root `SKILL.md` and `skills/engineering-harness/SKILL.md` remain byte-identical. Diagnosability skill says `VERIFYING` or `REVIEWING`. Engineering-harness dispatch runs required Q3 review before `VERIFYING -> REVIEWING`; Q2 runs it only when `observability.required: true`. This matches existing CLI state admission and Q3 preflight ordering.

### Proof diagnostics

Automated proof coverage keeps existing boolean coverage semantics and emits one `PLAN_PROOF_MISSING` blocker per plan item with `recover_to=VERIFYING`. Reconciliation and preflight error message lists every missing parent case reference (`REQ-*/TC-*` or `INV-*/TC-*`) with pytest node ID. `plan status --verbose` schema remains unchanged; it does not gain new JSON fields.

## Verification

Unit tests prove adopted versus protected surface behavior, immutable receipt allocation and reuse, invalid case rejection before subprocess execution, skill-state documentation contract, and node-specific missing-coverage diagnostics. Run only regression and impact-related tests for changed paths and their consumers. Full-suite execution is forbidden.

## Risks

- Receipt naming affects existing reuse and evidence lookup behavior.
- Ownership migration must preserve protection when paths are not explicitly adopted.
- Changed error text must retain stable blocker codes consumed by existing tools.
