# v0.2.6 Control-Plane Integrity Design

**Status:** Approved design. No implementation before user reviews this document.

## Goal

Harden Harness control-plane artifact integrity after v0.2.5 review findings. Make Contract, review, Finding, scope, evidence, and Gate semantics single-owned, fail-closed, and transactionally persisted.

v0.2.6 adds no new production logging capability, logger integration, OpenTelemetry/APM integration, automatic log insertion, or universal source scanning.

## Scope

1. Artifact ownership.
2. Transactional diagnosability review persistence.
3. Separate review-input, review-readiness, and Finding-closure validation.
4. Shared complete Harness lifecycle fixture builder.
5. Cross-layer E2E fixture matrix.

## Architecture

```text
Agent skill output
        │
        ▼
review input artifact
        │
        ▼
validate_review_input
        │
        ▼
validate_review_readiness
Contract + Findings + Scope + HEAD + Workspace
        │
        ▼
.harness/.staging/<operation-id>/
  ├── FND-*.yaml
  └── diagnosability-review.json
        │
        ▼
atomic publish
        │
        ▼
Gate / Finding lifecycle
        │
        ▼
validate_compliance_closure
```

## Ownership

| Module | Owns |
|---|---|
| `task` data | persisted `task.type`; no caller infers task kind from Requirements. |
| `diagnosability.py` | Contract loading, review input, readiness, Finding linkage, and closure semantics. |
| `transaction.py` | staging, publish, cleanup; no semantic decision. |
| `evidence_validator.py` | evidence identity and freshness only. |
| `quality_gate.py` | calls readiness owner; does not reinterpret review checks. |
| `controlplane.py` | CLI adapter only. |

## Task type

Persist task kind as:

```yaml
task:
  id: TASK-001
  type: feature # feature | bugfix | refactor | nonfunctional
```

Contract loading receives this exact type. A bugfix Contract with `bug_fix.observability_gap` must validate through CLI and Gate paths. Old tasks without `task.type` default to `feature` only for backward compatibility.

## Validator interfaces

```python
def validate_review_input(document: dict, *, task_id: str) -> DiagnosabilityReview: ...

def validate_review_readiness(
    contract: dict,
    review: DiagnosabilityReview | dict,
    findings: list[dict],
    *,
    scope_files: tuple[str, ...],
    current_head: str,
    current_workspace: str,
) -> None: ...

def validate_compliance_closure(
    finding: dict,
    record: dict,
    *,
    current_head: str,
    current_workspace: str,
) -> None: ...
```

### Review input

Validates only schema, task identity, exact check names, valid check values, unique Finding IDs, and input shape.

### Review readiness

Fails closed unless all conditions hold:

- `review.contract_required == contract.required`.
- Review scope contains every Contract inspected path and declared direct dependency.
- `not_applicable` is permitted only when Contract does not declare that dimension.
- Every `fail` check maps to at least one proposed/open DIAG Finding.
- Linked Finding ID appears in review input.
- Linked Finding has `category: diagnosability`.
- Finding location is inside review scope.
- Finding `compliance.required_checks` covers mapped failed check.
- Review is bound to current HEAD/workspace when Gate reads canonical evidence.

A review containing `fail` checks is valid review evidence only for DEFECT routing. It is never Gate-ready while those checks remain failed or linked Findings are open.

### Finding closure

Validates terminal static-compliance proof only. It never decides whether an entire review is Gate-ready. Ordinary Findings retain same-test RED/GREEN closure requirements.

## Transaction

Add `src/harness/transaction.py`:

```python
@dataclass(frozen=True)
class StagedArtifact:
    relative_path: str
    content: bytes


def stage(harness_dir: Path, operation_id: str, artifacts: list[StagedArtifact]) -> Path: ...
def publish(harness_dir: Path, stage_dir: Path) -> None: ...
def cleanup_stale_staging(harness_dir: Path) -> None: ...
```

Rules:

1. Validate all source review, Contract, Finding, and scope relations before staging.
2. Stage only under `.harness/.staging/<operation-id>/`.
3. Stage every proposed Finding and canonical review evidence before publish.
4. Reject an existing canonical Finding target; never overwrite it.
5. Publish each canonical target with same-directory temporary file then atomic replace.
6. On validation or staging failure, publish zero canonical artifacts.
7. On publish failure, retain staging directory for diagnosis; report explicit failure and never claim success.
8. `.harness/.staging/**` is excluded from workspace fingerprint and review scope.
9. Status/startup may remove stale completed staging directories only after verifying no canonical publish is in progress.

## CLI behavior

`harness review diagnosability --file <artifact>`:

```text
load task + Contract
→ parse review input
→ derive actual scope
→ validate readiness and all proposed Findings
→ stage artifacts
→ publish artifacts
→ print canonical evidence path and Finding IDs
```

It does not transition task state. A review with failed checks persists proposed Findings plus review evidence, then caller must use:

```bash
harness review outcome DEFECT \
  --reason-code DIAGNOSABILITY_VIOLATION \
  --finding FND-001
```

## Shared fixture builder

Create test-only builder:

```python
make_harness(
    state="GATING",
    risk="Q2",
    task_type="feature",
    observability="required",
    test_plan="complete",
)
```

Builder creates schema-valid task, complete Requirements/Invariant test plans, fresh evidence, required canonical files, and empty findings. It replaces duplicated hand-written "passing harness" fixtures. It does not replace business-specific test setup.

## E2E matrix

1. Q2 required=false → no review → Gate PASS.
2. Q3 unassessed Contract → Gate BLOCK.
3. Bugfix `observability_gap=false` → Contract/review/Gate PASS.
4. Failed check without Finding → reject; zero canonical artifacts.
5. Failed check with linked DIAG Finding → persist Finding and evidence; DEFECT route required.
6. `contract_required` mismatch → reject.
7. `not_applicable` hides Contract-required dimension → reject.
8. Finding location outside scope → reject.
9. Workspace changes after review → stale Gate BLOCK.
10. DIAG Finding static-compliance closure → Gate PASS.
11. Ordinary Finding missing RED/GREEN → reject.
12. Injected publish failure → no incomplete canonical review/Finding set.

## Files

```text
src/harness/diagnosability.py
src/harness/transaction.py                 # new
src/harness/workspace.py
src/harness/quality_gate.py
src/harness/controlplane.py
src/harness/schemas/task.schema.json
src/harness/schemas/diagnosability-review.schema.json
src/harness/templates/current-task.yaml
tests/fixtures/harness.py                  # new builder
tests/test_diagnosability.py
tests/test_cli_diagnosability.py
tests/test_diagnosability_gate.py
tests/test_diagnosability_lifecycle.py
tests/test_harness_fixture.py              # new
```

## Non-goals

- Logger SDK, logging framework migration, OpenTelemetry, APM, ELK/Loki, trace backend.
- New business logging requirements.
- Automatic log insertion or full-repository source scanning.
- Rewriting every existing test fixture.
- Moving/replacing published `v0.2.5` tag.
