# v0.2.10 Plan Reconciliation P1B — Status CLI Design

**Status:** External review incorporated; pending owner approval

**Authority:** Extends `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md` section 7 for P1B only.

## 1. Goal

Add a read-only `harness plan status` command that reports canonical Plan Reconciliation state without requiring users or Agents to inspect YAML artifacts manually.

The command answers four questions:

1. Is Plan Reconciliation effectively enabled for this task?
2. Are the canonical plan and execution artifacts present and fingerprint-compatible?
3. How much trustworthy execution progress is reconciled, and which canonical item is next?
4. Does the P0 final Plan Reconciliation check currently pass or block?

Canonical `.harness/plan.yaml`, `.harness/plan-execution.yaml`, task configuration, referenced contracts, evidence, and workspace facts remain authoritative. CLI output is derived and is never persisted as a new source of truth.

## 2. Scope

P1B includes:

- `harness plan status` human-readable output;
- `harness plan status --json` machine-readable output;
- effective-enable isolation for disabled and FAST/Q1 tasks;
- artifact presence and semantic-fingerprint reporting;
- trustworthy terminal-status counts and reconciled progress;
- first trustworthy nonterminal item;
- plan-only final blockers using existing P0 reconciliation rules;
- deterministic malformed, missing, and stale behavior;
- proof that the command is read-only.

P1B excludes:

- plan initialization, mutation, reconciliation, or repair commands;
- Q3 task-level enforcement (P1C);
- Context schema or projection changes;
- Markdown parsing or checkbox synchronization;
- automatic semantic decisions for `SKIPPED` or `SUPERSEDED` items;
- Gate Preview or non-plan Gate blockers;
- new blocker, evidence, or task-state types.

## 3. Command Interface

```bash
harness plan status
harness plan status --json
```

`plan` is a top-level command group. P1B adds only the required `status` subcommand.

The command normalizes execution to repository root in the same way as existing Harness commands. It reads `.harness/` from that repository root and does not add a `--harness-dir` override in P1B.

Exit behavior:

| Condition | Exit | Output |
|---|---:|---|
| Disabled, including FAST/Q1 with ad hoc `enabled: true` | 0 | Disabled report |
| Enabled and artifacts valid, whether reconciled or blocked | 0 | Status report |
| Enabled and one or both artifacts missing | 0 | Blocked report with `PLAN_REQUIRED` |
| Enabled and semantic fingerprint stale | 0 | Blocked report with `PLAN_STALE` |
| Enabled and another semantic P0 issue exists | 0 | Blocked report with typed `PLAN_*` blockers |
| Present artifact is malformed or schema-invalid | 2 | `INVALID_HARNESS_STATE:` on stderr; no stdout |
| Task or another required canonical input is malformed | 2 | `INVALID_HARNESS_STATE:` on stderr; no stdout |
| Repository root cannot be found | 1 | Existing `ERROR:` prefix on stderr; no stdout |

A blocked plan is reportable state, not command failure. Exit 2 is reserved for states that cannot be parsed or validated into a trustworthy report. Repository discovery remains the existing CLI-level exit-1 error and is not remapped to invalid Harness state.

## 4. Effective Enablement and Isolation

P1B reuses `effective_plan_reconciliation(task)`.

Effective enablement is true only when:

- persisted `plan_reconciliation.enabled` is exactly `true`; and
- task profile is `STANDARD` or `STRICT`.

For missing configuration, persisted `enabled: false`, or any FAST/Q1 task:

- return JSON exactly as `{ "enabled": false }`;
- human output reports Plan Reconciliation as disabled;
- do not open, parse, validate, hash, stat, or enumerate `.harness/plan.yaml` or `.harness/plan-execution.yaml`;
- do not inspect plan-owned Requirement, Invariant, Decision, Evidence, or workspace proof sources;
- adjacent missing, stale, or malformed plan artifacts have no effect.

This preserves the P0/P1A FAST source boundary. An ad hoc `enabled: true` on a FAST task is not an opt-in.

## 5. JSON Report Contract

Enabled reports use this closed conceptual shape:

```json
{
  "enabled": true,
  "mode": "final",
  "plan": {
    "present": true,
    "execution_present": true,
    "fingerprint": "sha256:...",
    "execution_fingerprint": "sha256:...",
    "fingerprint_fresh": true
  },
  "progress": {
    "total": 9,
    "reconciled": 7,
    "statuses": {
      "PENDING": 1,
      "IN_PROGRESS": 0,
      "COMPLETE": 6,
      "SKIPPED": 1,
      "SUPERSEDED": 0,
      "BLOCKED": 1
    }
  },
  "next_plan_item": "P-008",
  "final_status": "blocked",
  "blockers": [
    {
      "code": "PLAN_ITEM_UNRECONCILED",
      "source": "P-008",
      "message": "plan item lacks terminal reconciliation"
    }
  ]
}
```

Rules:

- `mode` is the effective persisted mode: `final` or `task_and_final`.
- `plan.present` and `plan.execution_present` report each canonical artifact independently.
- `plan.fingerprint` is the semantic fingerprint computed from a present valid plan, otherwise `null`.
- `plan.execution_fingerprint` is the execution document's recorded fingerprint when present, otherwise `null`.
- `plan.fingerprint_fresh` is `true` or `false` only when both fingerprints exist; otherwise `null`.
- `progress` is non-null only when both artifacts exist and fingerprints match. Missing or stale execution is not trustworthy, so `progress` is `null` rather than a misleading partial count.
- `total` is canonical `plan.items` length.
- `reconciled` counts `COMPLETE`, `SKIPPED`, and `SUPERSEDED` records.
- `statuses` contains every schema-defined status in the fixed order shown above, including zero counts.
- An absent execution record counts as unresolved for `next_plan_item`, but is not invented as a persisted `PENDING` record in `statuses`.
- `next_plan_item` and `final_status` are taken directly from `plan_context_summary(task, plan, execution, blockers)`. The status-report builder must not reimplement either algorithm.
- Consequently, `next_plan_item` is the first absent or nonterminal execution item in canonical plan order, or `null` when execution is missing/stale or all records are terminal.
- Consequently, `final_status` is `blocked` when plan-only assessment returns any `PLAN_*` blocker, otherwise `pass`.
- `blockers` is the compact projection of exactly the blocker list returned by the existing P0 reconciliation validation, including its early-return behavior. It contains only `code`, nullable `source`, and `message`, preserving assessment order. No unrelated Gate blocker appears.
- No plan intent, Requirement/Invariant references, test-case references, surfaces, reason, evidence reference, Decision ID, or supersession body is projected.
- No timestamp, current task state, global Gate status, or generated hash is included.

Disabled output remains the smaller exact shape and does not populate null enabled-only fields.

## 6. Human-Readable Report

Human output projects the same facts as JSON, without additional assessment:

```text
Plan Execution

Mode: final
Artifacts: plan present, execution present, fingerprint fresh
Progress: 7 / 9 reconciled

COMPLETE       6
SKIPPED        1
SUPERSEDED     0
PENDING        1
IN_PROGRESS    0
BLOCKED        1

Next: P-008
Final: BLOCKED

Blockers:
  PLAN_ITEM_UNRECONCILED [P-008] plan item lacks terminal reconciliation
```

Artifact lines use these exact terms:

- both present and matching: `Artifacts: plan present, execution present, fingerprint fresh`;
- both present and mismatching: `Artifacts: plan present, execution present, fingerprint stale`;
- either missing: `Artifacts: plan <present|missing>, execution <present|missing>, fingerprint unavailable`.

Missing/stale output prints `Progress: unavailable` and `Next: -`. A blocker with a source prints `  CODE [SOURCE] message`; a blocker without a source, including `PLAN_REQUIRED` and `PLAN_STALE`, prints `  CODE message`. When `final_status` is `pass`, the `Blockers:` section is omitted rather than printed empty. Disabled output is:

```text
Plan Execution

Status: disabled
```

Text rendering consumes the JSON-equivalent report object. It never loads sources or recomputes status independently. Tests compare key text values against the report used for JSON output.

## 7. Plan-Only Assessment

P1B must report the same final Plan Reconciliation result as P0 without running or projecting the complete Gate.

The status path therefore reuses existing P0 validation rules for:

- required artifact presence;
- semantic fingerprint freshness;
- execution key membership and terminal disposition validity;
- accepted Decision and supersession validity;
- item-owned evidence coverage;
- changed-surface proof and protected-path checks.

It does not call `quality_gate.assess_gate`, because that would mix unrelated blockers and require unrelated Gate policy for a plan-only report.

The blocker list MUST equal the list produced by today's `validate_plan_reconciliation()` semantics, not merely contain the same kinds of blockers. Existing early returns remain contractual:

- either artifact missing returns only `PLAN_REQUIRED`;
- fingerprint mismatch returns only `PLAN_STALE`;
- an execution key absent from the plan returns only its `PLAN_DISPOSITION_INVALID`;
- a supersession failure returns only its `PLAN_DISPOSITION_INVALID`;
- later item proof checks do not run after one of those early returns.

To avoid parsing canonical plan artifacts twice, extract a document-consuming P0 validation seam whose required `plan` and `execution` parameters accept `dict | None`. `None` means confirmed canonical absence, exactly as returned by `load_plan_artifacts(optional=True)`; it never means "load this document yourself".

Both callers use that seam:

1. the status command calls `load_plan_artifacts(optional=True)` once, passes the resulting pair to validation, then passes the same pair and returned blockers to `plan_context_summary()` and progress projection;
2. the existing Gate-facing wrapper retains its own canonical loading step and delegates the loaded pair to the same validation seam.

No internal missing/not-supplied sentinel is introduced. `PlanArtifactError` remains the only malformed-present path. No validation rule is copied into `controlplane.py` or CLI rendering.

## 8. Progress and Trust Rules

Terminal statuses are:

- `COMPLETE`;
- `SKIPPED`;
- `SUPERSEDED`.

Nonterminal statuses are:

- absent execution record;
- `PENDING`;
- `IN_PROGRESS`;
- `BLOCKED`.

Progress is trustworthy only when:

- both artifacts are present and schema-valid; and
- `execution.plan.fingerprint == plan_fingerprint(plan)`.

When trustworthy:

- count statuses only for execution records belonging to canonical plan item IDs;
- P0 validation still reports any unknown execution key as `PLAN_DISPOSITION_INVALID`;
- `total` comes from canonical plan order, not execution-map size;
- `reconciled` counts canonical items with terminal records, including a `COMPLETE` item whose proof later fails; proof validity affects `final_status` and `blockers`, not terminal disposition count;
- absent records reduce reconciled count but do not alter status counts.

When untrustworthy, `progress` and `next_plan_item` are null. Raw stale execution counts are not displayed as current progress.

## 9. Error Semantics

| Condition | Report behavior |
|---|---|
| Disabled plus malformed adjacent artifacts | Exit 0; disabled; artifacts unread |
| Enabled plus both artifacts absent | Exit 0; presence false; progress null; `PLAN_REQUIRED` |
| Enabled plus one artifact absent | Exit 0; independent presence; progress null; `PLAN_REQUIRED` |
| Enabled plus malformed present artifact | Exit 2; `INVALID_HARNESS_STATE:` stderr; no stdout |
| Enabled plus stale fingerprint | Exit 0; freshness false; progress/next null; `PLAN_STALE` |
| Enabled plus matching nonterminal records | Exit 0; trustworthy progress; first nonterminal item; blocked |
| Enabled plus terminal proof failure | Exit 0; trustworthy progress; next null; typed proof blocker |
| Enabled plus complete valid reconciliation | Exit 0; reconciled equals total; next null; pass |

Errors retain existing stable categories. P1B introduces no `PLAN_STATUS_*` code.

## 10. Read-Only and Determinism Guarantees

`harness plan status` must not:

- write or normalize YAML files;
- create missing directories or artifacts;
- update task Gate fields;
- initialize plan execution records;
- collect evidence;
- alter task state;
- publish Context;
- persist its report.

Given unchanged canonical inputs and workspace, repeated invocations produce semantically identical JSON and text. Mapping order is fixed by the report builder; item evaluation follows canonical plan order.

Tests snapshot relevant repository and `.harness/` bytes before and after success, blocked, malformed, and disabled invocations.

## 11. Component Boundaries

### `src/harness/plan_reconciliation.py`

Owns:

- normalized plan-only assessment from already-loaded documents;
- pure status report projection that directly consumes `plan_context_summary()` for next/final fields;
- progress trust and counting rules;
- compact blocker projection.

It does not print output or parse CLI arguments.

### `src/harness/controlplane.py`

Owns command orchestration:

- load and validate current task;
- stop immediately on disabled effective configuration;
- conditionally load canonical artifacts once;
- capture workspace facts needed by P0 assessment;
- map malformed source errors to stable CLI failure;
- select JSON or text renderer.

It does not duplicate reconciliation rules.

### `src/harness/cli.py`

Owns only parser shape and dispatch:

- `plan` command group;
- required `status` subcommand;
- `--json` flag.

### Tests

Focused tests own output contract, isolation, final-status parity, read-only behavior, and error exits.

No new package, schema resource, persistence file, or dependency is required.

## 12. Expected Implementation Surfaces

- `src/harness/cli.py`
- `src/harness/controlplane.py`
- `src/harness/plan_reconciliation.py`
- `tests/test_cli.py` or the repository's nearest parser/dispatch test file
- `tests/test_task_contract.py` for pure reconciliation/report behavior
- a focused plan-status CLI test file if existing CLI fixtures would become less clear

Context modules and `context.schema.json` remain unchanged. Quality Gate behavior remains unchanged except for internal reuse needed to prevent duplicated validation logic.

## 13. Verification

Focused deterministic tests must cover:

1. parser accepts `harness plan status` and `--json`, and rejects missing/unknown plan subcommands;
2. disabled output is exactly `{enabled: false}` in JSON;
3. disabled and FAST/ad-hoc-enabled commands do not inspect malformed adjacent artifacts;
4. enabled matching artifacts report independent presence, fresh fingerprint, fixed status counts, reconciled total, next item, and plan-only final status;
5. absent execution records affect next/reconciled values without being invented in status counts;
6. one or both missing artifacts exit 0 with null progress and only `PLAN_REQUIRED`;
7. stale fingerprint exits 0 with false freshness, null progress/next, and only `PLAN_STALE`;
8. unknown execution items and supersession failures preserve existing single-blocker early returns;
9. malformed present artifact exits 2 with `INVALID_HARNESS_STATE:` stderr and no stdout;
10. missing repository root retains existing exit 1 and `ERROR:` stderr;
11. proof, disposition, protected-path, and unresolved-item blockers match existing P0 rules, ordering, and early returns;
12. `next_plan_item` and `final_status` equal direct `plan_context_summary()` output for the same task, documents, and blockers;
13. non-plan Gate blockers never enter status output;
14. text covers sourced/unsourced blockers, exact artifact presence/freshness lines, unavailable progress, and omission of an empty passing `Blockers:` section;
15. a terminal `COMPLETE` record contributes to `reconciled` even when item proof fails;
16. text and JSON render the same report facts;
17. compact report contains no plan or execution bodies;
18. command leaves task, plan, execution, evidence, Gate, Context, and repository bytes unchanged;
19. existing P0 Gate, P1A Context, and FAST source-isolation focused regressions remain green.

Run focused related tests only. Full repository suite remains forbidden.

## 14. Delivery Boundary

P1B is complete when:

- both output modes expose the defined read-only report;
- disabled/FAST isolation remains intact;
- missing is reportable blocked state with exit 0;
- malformed present sources fail closed with exit 2;
- final status is derived from existing P0 rules without whole-Gate projection;
- no output body or command side effect becomes authoritative.

P1C remains a separate task for deterministic Q3 task-level guidance and enforcement. P1B output does not authorize work, transition task state, or replace `harness resume`.
