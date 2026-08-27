# Evidence Reuse Design

**Status:** Proposed Phase 4
**Scope:** Same-task, same-state evidence reuse only. No implementation until user approves this document.

## Goal

Avoid duplicate successful test/build execution without weakening Evidence proof. Reuse is an explicit collector optimization, never a Gate shortcut.

## Non-goals

- Cross-task or cross-workspace evidence cache.
- Reuse for failed proof, including FAST RED/GREEN and Finding lifecycle RED/GREEN evidence.
- State-machine shortcut transitions.
- Evidence reuse, execution budget, telemetry, benchmark, or release work outside this Phase 4 scope.

## CLI

Add optional `--reuse-if-valid` to `harness evidence`.

```bash
harness evidence --type unit_test --scope related \
  --covered-test tests/x.py::test_x \
  --command "pytest tests/x.py::test_x" \
  --reuse-if-valid
```

Without flag, collector always executes command. With flag:

- valid matching record: print `EVIDENCE_REUSED: <filename>`, return `0`, do not execute shell command, do not rewrite evidence;
- missing, stale, invalid, failed, or mismatching record: run command and write fresh evidence through existing collection path.

No output contains `runtime.executable`; only filename is printed.

## Reuse eligibility

Reuse only an existing successful generic record in current task `.harness/evidence/`. Reuse requires exact equality of:

1. evidence type;
2. command string;
3. unit-test scope and covered-test set;
4. phase (must be absent);
5. Finding subject/test identity (must be absent);
6. current Git HEAD;
7. current workspace fingerprint, including record before/after equality;
8. exact runtime metadata.

Only generic build/lint/typecheck/unit/integration/contract/security/custom records qualify. Any request or candidate carrying `--finding` or `--phase` is collected normally. Candidate `exit_code` must be zero.

## Runtime metadata

Every newly collected Evidence record adds:

```json
"runtime": {
  "implementation": "CPython",
  "version": "3.11.10",
  "executable": "/absolute/path/to/python",
  "platform": "Darwin-arm64"
}
```

Compatibility requires exact equality for all four fields. Existing evidence with no `runtime`, malformed JSON, or schema-invalid content is never reusable and is replaced by a newly executed record.

`runtime` becomes optional in evidence schema for backward compatibility: old records remain valid for Gate and status, but never qualify for reuse.

## Components

- `collect_evidence.py`: gathers runtime metadata, computes candidate filename, calls pure reuse predicate before shell execution.
- `evidence_validator.py`: exposes pure projection/predicate for successful same-task reuse; collector consumes it. Existing Gate freshness validator behavior stays unchanged.
- `cli.py`: parses/passes `--reuse-if-valid`.
- tests: prove execution/no-execution behavior and every fail-closed mismatch.

## Failure behavior

Reuse mismatch is normal cache miss, not CLI error. Collector runs supplied command. Git/workspace inspection failure keeps current invalid-harness behavior. Collector never trusts an invalid record and never changes a reused record.

## Verification

TDD coverage proves:

- matching evidence returns `EVIDENCE_REUSED` without executing command;
- command, scope, covered-tests, HEAD, workspace, runtime, phase, Finding identity, failed result, old record, malformed record, and schema-invalid record all execute command;
- normal collection writes runtime metadata;
- existing Gate/status/finding evidence regressions remain unchanged.

## Acceptance criteria

1. Reuse only occurs under same task, exact proof identity, unchanged HEAD/workspace, and exact runtime.
2. Reuse cannot turn failed, RED/GREEN, Finding, stale, old, malformed, or mismatching evidence into success.
3. Cache miss runs normal collection with no user intervention.
4. Existing evidence consumers stay backward compatible.
