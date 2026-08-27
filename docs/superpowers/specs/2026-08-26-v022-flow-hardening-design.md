# v0.2.2 Flow Hardening Design

## Goal

Release `0.2.2` implements four guide P0 items without expanding Harness into a workflow engine:

1. Typed blocker recovery.
2. Deterministic review-outcome routing.
3. Evidence-backed status projection.
4. Deterministic complexity review scope.

Existing proof laws remain unchanged: only `CONVERGED -> DONE` completes; stale/failed evidence cannot pass Gate; defects retain Finding lifecycle; finding RED/GREEN identity remains enforced.

## Non-goals

No requirement-to-test traceability, extra review agents, UI, plugin system, database, CLI-framework rewrite, state-machine rewrite, or unrelated Evidence schema changes.

## Shared facts

### `workspace.py`

Add one repository-state API:

```python
@dataclass(frozen=True)
class WorkspaceSnapshot:
    head: str
    fingerprint: str
    changed_paths: tuple[str, ...]

@dataclass(frozen=True)
class ReviewScope:
    base_ref: str
    base_commit: str
    head_commit: str
    workspace: WorkspaceSnapshot
    files: tuple[str, ...]
```

`WorkspaceSnapshot` uses current `.harness/**` exclusion policy for both fingerprint and path discovery. It covers committed delta, staged delta, unstaged delta, plus relevant untracked files. `review_scope(base_ref)` obtains `merge-base(base_ref, HEAD)`, then computes effective files from all four sources. Therefore `--base HEAD` with a dirty worktree has nonempty scope.

`collect_evidence`, `quality_gate`, `harness_status`, and `complexity` use this API. No module keeps independent git/fingerprint rules.

### Evidence projection

Extend `evidence_validator.py` with a typed classification API returning exactly one of:

```text
FRESH | STALE | MISSING | INVALID | FAILED
```

Definitions:

- `FRESH`: schema-valid, current HEAD/workspace, successful when success is required.
- `STALE`: valid record whose HEAD or workspace differs.
- `MISSING`: required record absent.
- `INVALID`: malformed schema/provenance/identity.
- `FAILED`: current, schema-valid command exited nonzero.

Existing `validate_evidence` remains fail-closed and uses same internal facts. Projection exposes reason code and expected/current fingerprints; it does not weaken Gate validation.

## Typed blockers and recovery

Add `blockers.py`:

```python
@dataclass(frozen=True)
class GateBlocker:
    code: str
    category: Literal["verification", "implementation", "defect", "harness", "convergence"]
    message: str
    source: str | None = None
    finding_id: str | None = None
    recover_to: str | None = None
```

`GateResult(passed, blockers)` replaces string-only internal Gate output. Persist `task.gate.blocked_by` as objects. Stable codes include Evidence failures, required-verification gaps, Finding-open states, complexity-review failures, harness invalidity, and convergence limit. Renderer text remains human-readable, but routing uses codes/categories only.

Recovery priority is `defect > implementation > verification > convergence`. Harness-invalid blockers have no general recovery target and fail closed.

Add `harness resume`:

1. Require task state `BLOCKED` and schema-valid typed blockers.
2. Select highest-priority blocker and computed `recover_to`.
3. Validate corresponding state transition, persist it atomically, print code and route.
4. Reject user-selected targets and unrouteable harness blockers.

State graph adds `BLOCKED -> VERIFYING`. `resume`, not generic `transition`, is sole route for this recovery edge. `FINDING_OPEN` only routes to `REPRODUCING`; iteration-limit only routes to `ESCALATED`.

## Review outcome routing

Add structured review outcome artifact with fields:

```yaml
review:
  outcome: PASS | VERIFICATION_GAP | DEFECT
  reason_code: <stable code>
  message: <human explanation>
  finding_ids: []
```

Add commands:

```text
harness review outcome PASS
harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT
harness review outcome DEFECT --finding FND-003
```

Command requires `REVIEWING`, validates artifact, then performs atomic deterministic route:

```text
PASS             -> GATING
VERIFICATION_GAP -> VERIFYING
DEFECT           -> REPRODUCING
```

`DEFECT` requires every referenced Finding exist and be nonterminal. Generic `harness transition` rejects these `REVIEWING` exits so agents cannot label defects as verification gaps. State graph adds `REVIEWING -> VERIFYING`, but only review-outcome control plane may use it.

## Complexity review scope

Recommended invocation becomes:

```text
harness review complexity --base <ref> --file <review.yaml>
```

`--base` is required for new calls. `--file` remains required and backward-compatible as reviewer findings input; Harness computes `base`, `head`, fingerprint, and scope itself. A submitted artifact may include scope only as an assertion. It must exactly match calculated scope or command rejects it with `COMPLEXITY_REVIEW_SCOPE_MISMATCH`.

Persist canonical computed scope in `complexity-review.json`:

```yaml
review_scope:
  base_ref: origin/main
  base_commit: <merge-base>
  head_commit: <HEAD>
  workspace_fingerprint: sha256:...
  files: [src/foo.py, tests/test_foo.py]
```

Review metadata must validate as fresh through shared Evidence projection. Workspace changes after review make it `STALE` in status and block Gate.

## Status and Gate

`harness status` remains read-only. It dynamically loads task, requirements, invariants, gate config, Finding records, Evidence records, and `WorkspaceSnapshot`. It stops treating `current-task.verification` as verification truth.

Status shows per Evidence type: classification, command, timestamp, exit code, covered tests, stale reason, expected/current fingerprint, and changed paths where applicable. It also renders typed blockers and deterministic next command hint.

Gate consumes same projection/validator. `harness gate` may persist current Gate result, but `harness status` and `harness check` never mutate state. Identical current inputs must produce identical Evidence classifications in status and Gate.

## Compatibility and migration

- Existing `harness review complexity --file` input stays supported only with explicit `--base`; no caller may declare authoritative `head` or scope.
- Existing Evidence fields, including `covered_tests`, remain intact for v0.3 traceability.
- Existing generic transition behavior stays for unrelated legal edges; new recovery/review edges are command-guarded.
- Legacy string `gate.blocked_by` is rendered as legacy/invalid recovery data. `resume` refuses it rather than guessing a recovery state. Next valid Gate evaluation writes typed blockers.

## Tests

Add focused unit tests for workspace snapshots/review scope, Evidence classification, typed blocker recovery, review outcome validation/routing, status projection, and scope mismatch.

Add CLI integration tests for `harness status`, `harness gate`, `harness resume`, `harness review outcome`, and `harness review complexity --base ... --file ...`.

Add lifecycle E2E cases:

1. Fresh evidence, workspace mutation, Gate block, `resume -> VERIFYING`, refresh, re-enter review/Gate without `IMPLEMENTING`.
2. `VERIFICATION_GAP -> VERIFYING -> REVIEWING -> PASS`; no Finding created.
3. `DEFECT` with Finding routes to reproduction; `DEFECT` without Finding rejects.
4. `base == HEAD` with dirty and untracked business files produces nonempty complexity scope; post-review mutation makes scope stale.

Run focused tests after each phase. Run full suite only with explicit user authorization under Harness policy.

## Release

Set project version to `0.2.2`. Update `CHANGELOG.md`, `README.md`, and Chinese README with recovery, review-outcome, evidence projection, and complexity invocation behavior. Keep guide as source specification.
