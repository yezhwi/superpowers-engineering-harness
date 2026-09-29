# v0.2.10 Plan Reconciliation P2 Design

> Status: proposed
> Task: TASK-063
> Extends: `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md`
> Predecessor: `docs/superpowers/specs/2026-09-28-v0210-plan-task-reconciliation-p1c-design.md`

## 1. Intent

P2 completes the remaining v0.2.10 Plan Reconciliation product surface without weakening canonical YAML authority. It adds four operator-facing capabilities:

1. explicit one-way projection from trusted Plan execution state to Markdown checkboxes;
2. deterministic automatic `COMPLETE` reconciliation from mechanical proof;
3. opt-in verbose Plan status reporting;
4. Plan status in existing Gate preflight output.

P2 also bounds per-request Plan indexing and evidence selection so richer output and automation do not require persistent caches or repeated canonical reads.

Requirements, frozen Alignment, `plan.yaml`, and `plan-execution.yaml` retain their existing authority. Markdown remains a projection. Automatic reconciliation proves mechanical facts only; it never makes semantic dispositions.

## 2. Scope

### 2.1 Included

- `harness plan sync-markdown <repo-relative-path>`
- `harness plan reconcile P-001 --auto`
- `harness plan status --verbose`
- `harness plan status --json --verbose`
- Plan summary in existing `harness gate preflight`
- request-local `P-*` and evidence coverage indexes
- omission/stale/fake-completion/recovery benchmark fixtures needed for v0.2.10 completion

### 2.2 Excluded

P2 does not add:

- Markdown-to-YAML import;
- automatic Markdown discovery;
- automatic Plan generation;
- automatic `SKIPPED` or `SUPERSEDED` dispositions;
- generated reasons or accepted Decisions;
- a persistent cache, index, registry, or canonical artifact;
- a separate `harness gate preview` command;
- a new evidence type, top-level Harness state, or lock;
- arbitrary Markdown parsing;
- semantic validation of whether a Plan is optimal or complete.

## 3. Architecture

P2 uses three focused modules while retaining existing Plan policy and mutation truth.

### 3.1 `plan_markdown.py`

Owns the restricted checkbox grammar, exact mapping validation, byte-preserving checkbox patching, and atomic publication of an explicitly named Markdown target.

It consumes an already trusted Plan projection. It does not load Gate truth independently and never writes Plan YAML.

### 3.2 `plan_automation.py`

Owns request-local evidence indexing, coverage atoms, unique-minimum evidence cover selection, and mechanical surface selection.

It returns a normalized ordinary `PlanMutationRequest` for `COMPLETE`. Existing `mutate_plan_execution(...)` remains the only canonical Plan execution writer and revalidates every inferred proof.

### 3.3 `plan_reporting.py`

Owns body-free verbose item projection and compact Gate preflight Plan projection from one already computed `PlanAssessment`.

Default status and Context output remain unchanged. Reporting never loads journal or proof bodies for rendering.

### 3.4 Existing seams

- `plan_reconciliation.py` remains canonical policy, assessment, and mutation orchestration.
- CLI parses arguments and maps stable errors only.
- Control plane loads task state, delegates once, and renders.
- `quality_gate` computes one `PlanAssessment`; Gate blockers and preflight rendering consume that same object.
- `telemetry_lock` and `transaction.atomic_write` remain the only lock and publication mechanisms.

## 4. Markdown checkbox projection

### 4.1 Command

```bash
harness plan sync-markdown docs/superpowers/plans/example.md
```

The path is required, repository-relative, and explicit. Harness does not search `docs/` or derive a target from `plan.yaml`.

### 4.2 Restricted grammar

A Plan checkbox mapping line is recognized only when, after optional leading spaces or tabs, it contains exactly:

```text
- [<state>] <plan-id><optional whitespace and suffix>
```

where `<state>` is one of space, lowercase `x`, or uppercase `X`, and `<plan-id>` matches `P-[0-9]+`. Examples:

```markdown
- [ ] P-001 text...
- [x] P-002 text...
- [X] P-003 text...
```

In regex terms, excluding the preserved line ending, the accepted mapping shape is:

```regex
^[ \t]*- \[( |x|X)\] (P-[0-9]+)(?:[ \t]+.*)?$
```

A malformed reserved candidate is a line that starts with optional indentation plus `- [`, contains a `P-[0-9]+` token before end-of-line, but does not match the accepted mapping regex. It rejects the operation. This definition is lexical and does not depend on whether prose “looks like” a Plan mapping. Ordinary headings, paragraphs, list text, and other lines containing `P-001` do not participate in mapping.

Leading indentation, marker spacing, Plan ID, suffix, and LF or CRLF line ending are preserved. Only the single checkbox-state character may change. Terminal state always writes lowercase `x`; when the existing character already equals the required character, no byte changes.

Every canonical Plan ID must occur exactly once as an accepted mapping line. A second accepted line for the same ID, an accepted line with an ID absent from canonical Plan, a malformed reserved candidate, or a missing canonical ID rejects the whole operation.

### 4.3 State mapping

- `COMPLETE`, `SKIPPED`, `SUPERSEDED` project to `[x]`.
- `PENDING`, `IN_PROGRESS`, `BLOCKED` project to `[ ]`.

The projection requires a trusted assessment projection:

- Q2 uses a legal, fresh v1 projection.
- Q3 uses replay-derived v2 projection.
- missing artifacts, stale fingerprint, required upgrade, or replay failure rejects synchronization.

### 4.4 Safety

Before Plan or Markdown reads, effective enablement rejects FAST/Q1 and disabled tasks. The target must be a regular UTF-8 file inside the repository, not a symlink, absolute path, or path containing `..`. A target listed in `risk.user_changes.paths` is protected and rejected.

The command acquires the existing `telemetry_lock`, reloads Plan artifacts and target bytes inside the lock, computes the complete patch, and publishes with `transaction.atomic_write`. Any error leaves target bytes unchanged. An already synchronized target returns success without writing and remains byte-identical.

Markdown content, hashes, and checkboxes never enter Gate truth, Context manifests, Plan fingerprints, or execution receipts.

## 5. Automatic mechanical COMPLETE

### 5.1 Command shape

```bash
harness plan reconcile P-001 --auto
```

`--auto` is mutually exclusive with `--complete`, `--skipped`, `--superseded`, `--reason`, `--decision`, `--replacement`, explicit `--evidence`, and explicit `--surface`.

Automatic reconciliation is available only for STRICT/Q3 `task_and_final`. Q2 remains v1 final-only and does not acquire journal mutation semantics.

### 5.2 Authorization and sequencing

The existing mutation pre-authorization runs before Plan or evidence reads. The item must be the active `IN_PROGRESS` item in canonical sequence. Exact retries use existing mutation semantics.

Automation can produce only:

```python
PlanMutationRequest(
    action="RECONCILE",
    item_id=item_id,
    disposition="COMPLETE",
    evidence_refs=derived_evidence_refs,
    surface_refs=derived_surface_refs,
)
```

It cannot construct a semantic disposition, reason, replacement, or Decision reference.

### 5.3 Candidate evidence

Candidate discovery is limited to canonical `.harness/evidence/*.json` members. A candidate is eligible only when existing evidence projection reports a fresh, successful record for current HEAD and product workspace. Stale or failed schema-valid records are ineligible. Any malformed present evidence record fails closed as `INVALID_HARNESS_STATE`; automation never silently skips malformed canonical evidence.

Evidence bodies are used only for existing coverage predicates and receipt creation. They are never rendered by automatic reconciliation or reports.

Limits are fail-closed:

- at most 16 eligible evidence candidates;
- at most 16 required coverage atoms.

Exceeding either limit returns `PLAN_AUTO_LIMIT_EXCEEDED` without mutation. These bounds cap worst-case exact search at `2^16 = 65,536` candidate subsets.

### 5.4 Coverage atoms and unique minimum cover

Required atoms come from the item’s qualified `test_case_refs`:

- each manual case contributes its bare `TC-*` coverage claim;
- each automated case contributes every declared test node required by existing `record_covers_test` and `command_covers_test` semantics.

A non-empty `test_case_refs` branch that resolves to zero coverage atoms returns `PLAN_PROOF_MISSING`; automation never treats the empty set as evidence. Otherwise, a request-local bitset index maps each eligible evidence ref to covered atoms. Candidate refs are sorted canonically. The exact selector enumerates combinations by increasing candidate count. At the first cardinality containing a complete cover, it checks the remainder of that same cardinality only: exactly one complete combination is accepted, while a second distinct complete combination immediately returns `PLAN_AUTO_PROOF_AMBIGUOUS`. If no cardinality covers every atom, it returns `PLAN_PROOF_MISSING`.

At the accepted limits, enumeration inspects at most 65,536 subsets. Evidence outside the unique minimum set is not attached. Manual atoms use bare `TC-*` membership in `covered_test_cases`; automated atoms use the existing `record_covers_test` and `command_covers_test` predicates.

### 5.5 Surface derivation

P2 extracts and reuses one mechanical surface helper from existing P0 validation rather than computing a raw intersection independently. The helper starts from `changed_paths_since(task.git.base_commit)` and applies section 2.2 of the Implementation Contract exactly:

- while the aggregate protected-path fingerprint equals the stored fingerprint, every `risk.user_changes.paths` entry is removed from the usable mechanical path set;
- when the aggregate fingerprint differs, protected paths remain observable so an intersecting COMPLETE item reaches existing `PLAN_PROTECTED_PATHS_MODIFIED` validation.

Automation selects the sorted intersection of item-declared surfaces and that filtered mechanical path set. No usable path returns `PLAN_PROOF_MISSING`. A protected-path conflict is delegated to the existing mutation validator and returns existing `PLAN_PROTECTED_PATHS_MODIFIED`; automation does not replace it with a new code.

An item with both test cases and surfaces requires both derived proof branches. An item with neither remains `PLAN_DISPOSITION_INVALID` through the existing mutation validator.

### 5.6 Final publication

Automation snapshots current workspace while deriving proof, then delegates to the existing locked mutation engine. The mutation engine reloads canonical artifacts, validates stale writers, validates all inferred evidence and surfaces, performs its existing second workspace snapshot, validates candidate schema, and atomically writes execution v2.

There is no alternate writer or weaker auto-only validator.

## 6. Verbose status

### 6.1 Compatibility

Existing commands retain byte-for-byte output:

```bash
harness plan status
harness plan status --json
```

Verbose output is opt-in:

```bash
harness plan status --verbose
harness plan status --json --verbose
```

### 6.2 Item projection

Verbose JSON adds an `items` array while preserving existing top-level key order and meanings. Each item may contain only:

```yaml
id: P-001
status: COMPLETE
proof_branch: tests | surfaces | tests_and_surfaces | none
proof_health: valid | missing | invalid | not_applicable | untrusted
blockers:
  - code: PLAN_PROOF_MISSING
    recovery: VERIFYING
```

Verbose text renders the same facts in canonical Plan order.

It never includes:

- journal transitions, actions, or sequence;
- evidence command output or payload bodies;
- proof or Decision receipt data;
- Decision IDs or bodies;
- skip/supersede reasons;
- Requirement, Invariant, or test-case statement bodies.

`proof_health` follows this closed precedence table:

1. untrusted execution projection → `untrusted`, with item `status: null`;
2. trusted nonterminal item, `SKIPPED`, `SUPERSEDED`, or any item whose `proof_branch` is `none` → `not_applicable`;
3. proof-bearing `COMPLETE` item with `PLAN_PROOF_MISSING` → `missing`;
4. proof-bearing `COMPLETE` item with `PLAN_DISPOSITION_INVALID` or `PLAN_PROTECTED_PATHS_MODIFIED` → `invalid`;
5. trusted proof-bearing `COMPLETE` item without those blockers → `valid`.

Only `COMPLETE` enters mechanical proof-health levels 3 through 5. `SKIPPED` and `SUPERSEDED` remain `not_applicable` even when their Plan definitions declare tests or surfaces, because P0 does not require mechanical COMPLETE proof for those dispositions. Blocker rows remain present for every disposition even when proof health is not applicable; for example, a COMPLETE item without a proof branch still exposes its `PLAN_DISPOSITION_INVALID` blocker.

For missing/stale/task-level-required/replay-invalid execution, item status or progress is not inferred from persisted untrusted `items`. Rows report `untrusted` with null status.

`final_status` continues to use only `assessment.final_blockers`. Public task-level blockers remain independent.

## 7. Gate preflight Plan preview

P2 extends existing:

```bash
harness gate preflight
```

No new command is introduced.

Internal `GateAssessment` carries a nullable `plan_assessment`. `quality_gate` loads Plan artifacts and computes Plan assessment once per Gate evaluation. It appends `assessment.blockers` to Gate blockers and attaches the same assessment for rendering.

For an enabled task, preflight adds a compact body-free Plan section containing:

- mode;
- trustworthy progress or unavailable;
- next Plan item or `-`;
- independent final status;
- Plan blocker codes and item sources.

Existing `READY:` output and existing blocker lines retain their exact content and order. The Plan section is appended after those existing lines. Plan-derived blockers are not rendered a second time inside the original blocker list.

Disabled tasks do not add the section. FAST returns before Plan evaluation and never inspects adjacent Plan, Markdown, or evidence automation sources.

Gate evaluation replaces the current `validate_plan_reconciliation(...)` result with the blockers from this one `PlanAssessment`; it does not call both paths or append duplicate `PLAN_*` blockers. Preflight remains read-only and does not offer reconciliation commands as authority.

## 8. Request-local indexing and read discipline

Each P2 command loads each canonical Plan document at most once per locked attempt and builds an in-memory map keyed by `P-*`. Automatic reconciliation scans canonical evidence members once and builds coverage bitsets once.

No persistent index is created. No report or Context path stores evidence coverage, journal bodies, or Markdown state. Retry after a concurrent writer re-enters the normal locked load path rather than reusing stale indexes.

## 9. Errors and exit contracts

New stable domain refusal codes:

| Code | Meaning |
|---|---|
| `PLAN_MARKDOWN_TARGET_INVALID` | unsafe path, protected target, non-regular/symlink target, non-UTF-8 content, or malformed checkbox syntax |
| `PLAN_MARKDOWN_MAPPING_INVALID` | missing, duplicate, or unknown Plan ID mapping |
| `PLAN_AUTO_PROOF_AMBIGUOUS` | multiple distinct minimum evidence covers |
| `PLAN_AUTO_LIMIT_EXCEEDED` | candidate or coverage-atom bound exceeded |

These are command refusal codes, not Gate blockers, and are not added to `RECOVERY_POLICY`.

Existing codes remain authoritative:

- missing proof or no cover: `PLAN_PROOF_MISSING`;
- missing/stale artifacts: `PLAN_REQUIRED` / `PLAN_STALE`;
- untrusted task-level execution: `PLAN_TASK_LEVEL_REQUIRED` / `PLAN_SEQUENCE_INVALID`;
- illegal lifecycle/order: `PLAN_SEQUENCE_INVALID`;
- item with no proof branch or invalid disposition: `PLAN_DISPOSITION_INVALID`.

Domain refusals exit 1 with empty stdout and stable code on stderr. Malformed canonical Harness sources exit 2 with `INVALID_HARNESS_STATE:` and empty stdout. Success and exact no-op retry exit 0 with minimal output.

## 10. Concurrency and atomicity

P2 adds no lock. Canonical execution mutation continues under existing `telemetry_lock`. Markdown synchronization uses that same lock and reloads source bytes while held.

All complete-file publication uses `transaction.atomic_write`. Failure injection must prove no temporary or partial canonical bytes remain. Concurrent Markdown writers must yield one complete legal projection. Concurrent auto reconciliation remains governed by the P1C one-active-item and stale-writer rules.

## 11. Acceptance tests

### 11.1 Markdown

Tests pin:

- LF and CRLF preservation;
- indentation, suffix text, and all non-checkbox bytes unchanged;
- `[ ]`, `[x]`, and `[X]` normalization by state;
- missing, duplicate, unknown, and malformed `P-*` lines reject with zero writes;
- non-UTF-8, symlink, absolute, `..`, repository-external, and protected targets reject;
- stale Plan, missing Plan, Q3 invalid replay, and FAST adjacent malformed artifacts fail or isolate as specified;
- exact no-op is byte-identical and does not call `atomic_write`;
- injected write failure and concurrent writers cannot produce partial content.

### 11.2 Automatic COMPLETE

Tests pin:

- unique one-file and multi-file minimum covers;
- ambiguous equal minimum covers;
- omission of non-minimum evidence;
- stale, failed, wrong-HEAD, and wrong-workspace evidence exclusion; malformed present evidence fails closed;
- manual case claims and automated test-node coverage;
- zero coverage atoms return `PLAN_PROOF_MISSING`; 16 atoms are accepted and 17 return the limit code;
- 16 and 17 eligible candidates;
- tests-only, surfaces-only, and dual proof branches;
- unchanged and protected surfaces;
- active-item/order refusal, exact retry, workspace race, atomic failure, and concurrent calls;
- derived request and explicit `--complete` request produce the same canonical transition payload;
- no automatic path exists for `SKIPPED` or `SUPERSEDED`.

### 11.3 Reporting and preflight

Tests pin:

- default text and JSON status bytes remain unchanged;
- trusted Q2/v1 and Q3/v2 verbose projections;
- missing, stale, Q3/v1, and replay-invalid execution never project untrusted progress;
- task-level blocker and independent final status remain separate;
- proof health follows the closed mapping table in section 6.2, including `SKIPPED` and `SUPERSEDED` items whose Plan definitions still declare proof branches;
- no journal, receipt, reason, Decision, Requirement, Invariant, or evidence body leaks;
- Gate preflight preserves existing `READY:` and blocker-line ordering, appends Plan output afterward, performs one Plan load/assessment, and does not duplicate `PLAN_*` blockers;
- FAST/Q1 does not read malformed adjacent Plan, Markdown, or evidence sources.

### 11.4 Packaging and benchmarks

- Wheel contains all three new modules.
- Installed CLI smoke covers `sync-markdown`, `reconcile --auto`, `status --verbose`, and `gate preflight`.
- Benchmark fixtures cover Plan omission, stale fingerprint, fake completion, replay recovery, automatic-proof ambiguity, and Context/status recovery without claiming unseen Agent behavior.

## 12. Delivery and release boundary

P2 is implemented as independently reviewable slices: pure Markdown projection, pure auto-proof selection, mutation/CLI integration, verbose reporting, Gate preflight integration, benchmarks, then focused acceptance and package verification.

Only after P2 Gate convergence may release work begin. Version, CHANGELOG, README, tags, push, and publishing remain separate user-authorized actions.

## 13. Core invariants

1. Requirement and canonical Plan YAML remain authoritative over Markdown.
2. Checkbox state is never proof and never Gate input.
3. Automatic reconciliation can only establish mechanical `COMPLETE` proof.
4. Semantic dispositions always require explicit operator input and existing Decision rules.
5. Auto output passes the same mutation validator, lock, race check, schema check, and atomic writer as explicit output.
6. Untrusted execution never determines progress, next item, Markdown state, or verbose item status.
7. Default status, Context, FAST/Q1, and Q2 semantics remain backward compatible.
8. Reports never expose journal, receipt, reason, Decision, or evidence bodies.
9. No persistent cache, new canonical artifact, top-level state, evidence type, or lock is introduced.
