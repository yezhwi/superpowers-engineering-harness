# Production Diagnosability Standard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Q2/Q3 production-diagnosability Contract, semantic-review proof, compliance Finding lifecycle, and Gate enforcement without a logger SDK or universal source scanner.

**Architecture:** `harness.diagnosability` is single deep module for observability Contract, review input/evidence, DIAG Finding shape, review scope linkage, and Gate readiness. Agent skills decide business/logging semantics; deterministic Python validates artifacts, Git/workspace freshness, Finding linkage, lifecycle proof, and risk policy. Existing ordinary Finding RED/GREEN behavior remains unchanged.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema, pytest, existing `harness` CLI and workspace snapshot APIs.

**Spec:** `docs/superpowers/specs/2026-08-29-production-diagnosability-design.md`

## Global Constraints

- Q0 skips. Q1/FAST uses skill-only three-item prompt; no observability artifact or Gate requirement.
- Q2 requires review only when `observability.required: true`; Q3 always requires a valid applicability artifact and fresh review.
- Do not add OpenTelemetry, a logger SDK, logger replacement, whole-repository scan, universal source scanner, or automatic log insertion.
- Agents inspect only changed files, declared Contract paths, and direct dependencies required for changed behavior.
- Existing logger, trace, reason-code, exception-handler, and masking conventions take precedence over generated conventions.
- `critical` and `major` open DIAG Findings block Gate; `minor` remains advisory. `DIAG_SENSITIVE_DATA_LOGGED` is always critical.
- Ordinary `FND-*` records retain same-test RED/GREEN and closure evidence rules. Only `category: diagnosability` with `compliance.evidence_kind: static_compliance` uses fresh passing diagnosability-review proof.
- Use atomic writes for every new persisted YAML/JSON artifact. Invalid input must not create partial evidence or Findings.
- No full test suite without explicit user authorization during Harness execution. Run focused tests in each task.

---

## File structure

| File | Responsibility |
|---|---|
| `src/harness/diagnosability.py` | Single interface for Contract validation/loading, review-input validation, scope calculation, canonical review persistence, DIAG Finding validation, compliance-proof validation, and Gate readiness. |
| `src/harness/schemas/observability.schema.json` | Versioned persisted Observability Contract schema. |
| `src/harness/schemas/diagnosability-review.schema.json` | Agent review input schema: task identity, checks, declared direct dependencies, Finding IDs, and outcome. |
| `src/harness/templates/observability.yaml` | Default `required: false` Contract created by `harness init`. |
| `src/harness/schemas/evidence.schema.json` | Add canonical `diagnosability_review` evidence type and its required review fields. |
| `src/harness/schemas/finding.schema.json` | Conditional DIAG Finding fields and static-compliance terminal proof fields. |
| `src/harness/init.py` | Initialize observability artifact non-destructively. |
| `src/harness/cli.py` | Add `harness review diagnosability --file`. |
| `src/harness/controlplane.py` | Delegate review command and DIAG Finding transition proof to `diagnosability`. |
| `src/harness/quality_gate.py` | Invoke `diagnosability.gate_blockers`; preserve generic Finding blocking. |
| `src/harness/review_outcome.py` and `src/harness/schemas/task.schema.json` | Permit `DIAGNOSABILITY_VIOLATION` only for `DEFECT`. |
| `src/harness/templates/gate.yaml` | Default standard/strict policy. |
| `skills/diagnosability-review/SKILL.md` | Semantic-review worker instructions and structured artifact format. |
| `skills/task-contract/SKILL.md` | Q2/Q3 applicability, linked requirements, and bugfix gap instructions. |
| `skills/engineering-harness/SKILL.md` | Q0/Q1/Q2/Q3 diagnostability routing. |
| `tests/test_diagnosability.py` | Unit tests for Contract, input, scope, canonical evidence, and DIAG Finding validation. |
| `tests/test_cli_diagnosability.py` | Real CLI persistence/rejection tests in temporary Git repositories. |
| `tests/test_diagnosability_gate.py` | Q2/Q3 conditional Gate, stale proof, and severity behavior. |
| `tests/test_diagnosability_lifecycle.py` | Static-compliance lifecycle and ordinary-Finding regression protection. |
| `tests/fixtures/diagnosability/*.yaml` | Seven fixture review inputs used by parametrized policy tests. |

## Shared interfaces

Define these in `src/harness/diagnosability.py`; later tasks import them rather than duplicating schema or evidence checks.

```python
from dataclasses import dataclass
from pathlib import Path

CHECK_NAMES = (
    "business_keys",
    "external_failure_context",
    "state_transitions",
    "caller_rejections",
    "sensitive_data",
    "duplicate_exception_logging",
    "low_value_logging",
)
CHECK_RESULTS = {"pass", "fail", "not_applicable"}

@dataclass(frozen=True)
class DiagnosabilityReview:
    task: str
    contract_required: bool
    checks: dict[str, str]
    finding_ids: tuple[str, ...]
    direct_dependencies: tuple[str, ...]


def load_contract(harness_dir: Path) -> dict: ...
def validate_contract(document: dict, *, task_type: str | None) -> None: ...
def validate_review_input(document: dict, *, task_id: str) -> DiagnosabilityReview: ...
def load_review_input(path: Path, *, task_id: str) -> DiagnosabilityReview: ...
def write_review(harness_dir: Path, review: DiagnosabilityReview, *, base_ref: str) -> Path: ...
def validate_review_evidence(record: dict, *, contract: dict, current_head: str, current_workspace: str) -> None: ...
def validate_diagnosability_finding(finding: dict) -> None: ...
def validate_compliance_closure(finding: dict, record: dict, *, current_head: str, current_workspace: str) -> None: ...
def gate_blockers(harness_dir: Path, task: dict, *, head: str, workspace: str) -> list["GateBlocker"]: ...
```

`write_review` calculates effective scope as current `workspace.review_scope(base_ref).files` union Contract `applicability.inspected_paths` union declared `direct_dependencies`. It rejects a source artifact whose claimed `review_scope.files` differs from this sorted union. Canonical evidence records this calculated list and a `direct_dependencies` list.

### Task 1: Persist and validate Observability Contracts

**Files:**
- Create: `src/harness/diagnosability.py`
- Create: `src/harness/schemas/observability.schema.json`
- Create: `src/harness/templates/observability.yaml`
- Modify: `src/harness/init.py`
- Modify: `tests/test_init.py`
- Modify: `tests/test_package_resources.py`
- Test: `tests/test_diagnosability.py`

**Interfaces:**
- Produces: `load_contract()` and `validate_contract()` from shared interface.
- Produces: default `.harness/observability.yaml` via `harness init`.
- Consumes: `harness.quality_gate.validate_schema` pattern only; schema ownership remains in `diagnosability.py`.

- [ ] **Step 1: Write failing Contract tests**

```python
# tests/test_diagnosability.py
import pytest
from harness.diagnosability import validate_contract


def test_required_contract_needs_business_key_failure_boundary_and_dimension():
    with pytest.raises(ValueError, match="OBSERVABILITY_CONTRACT_INVALID"):
        validate_contract({
            "version": 1,
            "required": True,
            "applicability": {"reasons": ["external_dependency"], "inspected_paths": ["src/pay.py"]},
            "business_keys": ["order_id"],
            "failure_boundaries": [],
        }, task_type="feature")


def test_bugfix_gap_false_rejects_improvement_fields():
    with pytest.raises(ValueError, match="OBSERVABILITY_CONTRACT_INVALID"):
        validate_contract({
            "version": 1, "required": False,
            "applicability": {"reasons": ["pure_calculation"], "inspected_paths": ["src/math.py"]},
            "bug_fix": {"observability_gap": False, "basis": "existing trace has order id", "improvement": "add log"},
        }, task_type="bugfix")
```

Add init tests asserting `observability.yaml` is created from template and an existing customized artifact is skipped unchanged. Add package-resource test assertions for both new resources.

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_init.py tests/test_package_resources.py -q
```

Expected: FAIL because `harness.diagnosability` and observability template/schema do not exist.

- [ ] **Step 3: Add schema, template, and minimal Contract module**

Implement `observability.schema.json` with `additionalProperties: false` and these conditional requirements:

```json
{
  "required": ["version", "required", "applicability"],
  "properties": {
    "version": {"const": 1},
    "required": {"type": "boolean"},
    "applicability": {
      "type": "object",
      "required": ["reasons", "inspected_paths"],
      "properties": {
        "reasons": {"type": "array", "minItems": 1, "uniqueItems": true, "items": {"type": "string", "minLength": 1}},
        "inspected_paths": {"type": "array", "minItems": 1, "uniqueItems": true, "items": {"type": "string", "minLength": 1}}
      },
      "additionalProperties": false
    }
  }
}
```

Implement conditional checks in `validate_contract` for `required` and `task_type == "bugfix"`; `required: false` permits only Contract core fields, except a bugfix may add `bug_fix`; raise `ValueError("OBSERVABILITY_CONTRACT_INVALID: <precise reason>")`. `load_contract` loads `.harness/observability.yaml`, validates it, and fails closed if missing/malformed. Add `observability.yaml` to `REQUIRED_FILES`; template default is:

```yaml
version: 1
required: false
applicability:
  reasons: [pure_calculation]
  inspected_paths: []
```

Because empty `inspected_paths` conflicts with Contract rule, change default to a documented initialization sentinel and teach `validate_contract` to accept exactly `inspected_paths: ["."]` only while `required: false`:

```yaml
version: 1
required: false
applicability:
  reasons: [not_assessed]
  inspected_paths: ["."]
```

Q2/Q3 Task Contract replaces sentinel before entering `PLANNED`; Q3 Gate rejects sentinel. This preserves non-destructive initialization while keeping persisted schema valid.

- [ ] **Step 4: Run focused tests to verify pass**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_init.py tests/test_package_resources.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Contract unit**

```bash
git add src/harness/diagnosability.py src/harness/schemas/observability.schema.json src/harness/templates/observability.yaml src/harness/init.py tests/test_diagnosability.py tests/test_init.py tests/test_package_resources.py
git commit -m "feat: add observability contract"
```

### Task 2: Persist fresh Diagnosability Review evidence through CLI

**Files:**
- Create: `src/harness/schemas/diagnosability-review.schema.json`
- Modify: `src/harness/schemas/evidence.schema.json`
- Modify: `src/harness/diagnosability.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_diagnosability.py`
- Test: `tests/test_cli_diagnosability.py`

**Interfaces:**
- Consumes: Task 1 `load_contract`, `validate_contract`; `workspace.review_scope`.
- Produces: `load_review_input`, `write_review`, `validate_review_evidence`.
- Produces CLI: `harness review diagnosability --file <path> [--base <ref>]`.

- [ ] **Step 1: Write failing CLI and scope tests**

```python
# tests/test_cli_diagnosability.py

def test_review_diagnosability_writes_current_scope_evidence(repo, review_source):
    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(review_source))
    assert result.returncode == 0, result.stderr
    record = json.loads((repo / ".harness/evidence/diagnosability-review.json").read_text())
    assert record["type"] == "diagnosability_review"
    assert record["checks"]["business_keys"] == "pass"
    assert "src/orders/refund.py" in record["review_scope"]["files"]


def test_review_diagnosability_rejects_missing_finding_for_failed_check(repo, failing_review_source):
    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(failing_review_source))
    assert result.returncode == 2
    assert "DIAG_FINDING_REQUIRED" in result.stderr
    assert not (repo / ".harness/evidence/diagnosability-review.json").exists()
```

Use same temporary-Git-repo helpers as `tests/test_cli_complexity.py`. Source artifact contains task ID, `contract_required`, all seven checks, `finding_ids`, `direct_dependencies`, and claimed sorted `review_scope.files`.

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_cli_diagnosability.py -q
```

Expected: FAIL because CLI subcommand and review schema/persistence are absent.

- [ ] **Step 3: Implement review input, canonical evidence, and CLI delegation**

Add parser branch:

```python
p_diagnosability = review_sub.add_parser("diagnosability", help="persist diagnosability review")
p_diagnosability.add_argument("--file", required=True, dest="source_file")
p_diagnosability.add_argument("--base")
```

Add `controlplane.cmd_review_diagnosability(Path, str | None)`. It loads current task, requires `state == "REVIEWING"`, uses `task["git"]["base_commit"]` when `--base` omitted, and returns exit 2 for invalid review without mutating artifacts.

`diagnosability.write_review` must:

1. Load and validate Contract and review input task identity.
2. Calculate sorted effective paths exactly as shared-interface section defines.
3. Require every failed check name to appear in at least one supplied DIAG Finding `compliance.required_checks`. Validate supplied Finding files as DIAG Findings and require each Finding `location.file` in effective paths.
4. Require `not_applicable` only for dimensions absent from Contract.
5. Write canonical JSON atomically with existing `evidence.schema.json` fields, `type: "diagnosability_review"`, `command: "harness review diagnosability"`, exit zero, current `git_head`, before/after identical snapshot fingerprints, review scope, contract-required flag, checks, and Finding IDs.

Extend evidence schema enum and conditionally require canonical fields when `type` is `diagnosability_review`. Do not route task state from this command.

- [ ] **Step 4: Run focused tests to verify pass**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_cli_diagnosability.py tests/test_evidence_validator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit review evidence unit**

```bash
git add src/harness/diagnosability.py src/harness/schemas/diagnosability-review.schema.json src/harness/schemas/evidence.schema.json src/harness/cli.py src/harness/controlplane.py tests/test_diagnosability.py tests/test_cli_diagnosability.py
git commit -m "feat: persist diagnosability review evidence"
```

### Task 3: Add DIAG Finding schema and static-compliance lifecycle

**Files:**
- Modify: `src/harness/schemas/finding.schema.json`
- Modify: `src/harness/diagnosability.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_finding_schema.py`
- Create: `tests/test_diagnosability_lifecycle.py`

**Interfaces:**
- Consumes: Task 2 `validate_review_evidence`.
- Produces: `validate_diagnosability_finding` and `validate_compliance_closure`.
- Produces CLI behavior: DIAG transitions reject test RED/GREEN flags and require `diagnosability-review.json` at `VERIFIED`.

- [ ] **Step 1: Write failing DIAG schema and lifecycle tests**

```python
# tests/test_finding_schema.py

def test_diag_finding_requires_reason_location_and_compliance():
    with pytest.raises(ValidationError):
        validate({
            "id": "FND-004", "kind": "requirement_violation", "target": "REQ-003",
            "category": "diagnosability", "severity": "major", "status": "PROPOSED",
            "scenario": "timeout lacks order id",
        })


def test_sensitive_data_diag_finding_must_be_critical():
    with pytest.raises(ValidationError):
        validate({**DIAG_BASE, "reason_code": "DIAG_SENSITIVE_DATA_LOGGED", "severity": "major", "status": "PROPOSED"})
```

```python
# tests/test_diagnosability_lifecycle.py

def test_static_compliance_finding_verifies_only_with_current_passing_review(repo, diag_finding):
    transition(repo, "FND-004", "REPRODUCING", "--attempt", "reviewed payment timeout")
    transition(repo, "FND-004", "CONFIRMED")
    transition(repo, "FND-004", "FIXING")
    transition(repo, "FND-004", "FIXED")
    result = transition(repo, "FND-004", "VERIFIED", "--evidence", "diagnosability-review.json")
    assert result.returncode == 0, result.stderr


def test_ordinary_finding_still_rejects_verified_without_red_green(repo, ordinary_finding):
    result = transition(repo, "FND-001", "VERIFIED", "--evidence", "diagnosability-review.json")
    assert result.returncode == 2
    assert "INVALID FINDING PROOF" in result.stderr
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest tests/test_finding_schema.py tests/test_finding_transition.py tests/test_diagnosability_lifecycle.py -q
```

Expected: FAIL because conditional DIAG fields and compliance lifecycle do not exist.

- [ ] **Step 3: Implement conditional schema and narrow lifecycle branch**

Add `category`, `reason_code`, `location`, and `compliance` properties to FND schema. Conditional `allOf` requires them when category is `diagnosability`; restrict reason-code enum; require `compliance.evidence_kind == "static_compliance"` and unique nonempty `required_checks`; require critical severity for sensitive-data code.

Amend every existing status-dependent RED/GREEN requirement so it applies only when `category` is absent or not `diagnosability`. Add DIAG status requirements: `CONFIRMED` requires `confirmed_at`; `FIXING` and `FIXED` require no regression-test fields; `VERIFIED` and `CLOSED` require `evidence` and `verified_at`, but no regression-test fields. Existing non-DIAG schema examples must continue validating unchanged.

In `cmd_finding_transition`, branch only when `finding.get("category") == "diagnosability"`:

- `REPRODUCING` retains required attempt.
- `CONFIRMED` sets `confirmed_at` and requires no `--test` or RED evidence.
- `FIXING` and `FIXED` require no RED/GREEN evidence.
- `VERIFIED` requires `--evidence`; delegate exact freshness/type/check validation to `validate_compliance_closure`.
- `REJECTED` retains attempts and reason.

Do not alter `_FINDING_TRANSITIONS`. Do not alter ordinary proof branch or `validate_finding_closure_evidence`.

- [ ] **Step 4: Run focused tests to verify pass**

Run:

```bash
pytest tests/test_finding_schema.py tests/test_finding_transition.py tests/test_diagnosability_lifecycle.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Finding lifecycle unit**

```bash
git add src/harness/schemas/finding.schema.json src/harness/diagnosability.py src/harness/controlplane.py tests/test_finding_schema.py tests/test_diagnosability_lifecycle.py
git commit -m "feat: add diagnosability finding lifecycle"
```

### Task 4: Enforce diagnostic readiness in Gate and review routing

**Files:**
- Modify: `src/harness/templates/gate.yaml`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/review_outcome.py`
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/harness_status.py`
- Create: `tests/test_diagnosability_gate.py`
- Modify: `tests/test_review_outcome.py`
- Modify: `tests/test_status_projection.py`

**Interfaces:**
- Consumes: Tasks 1–3 `gate_blockers`, canonical review evidence, and static-compliance Findings.
- Produces: typed Gate blockers `DIAGNOSABILITY_REVIEW_MISSING`, `DIAGNOSABILITY_REVIEW_STALE`, `OBSERVABILITY_CONTRACT_INVALID`, and `DIAGNOSABILITY_SCOPE_MISMATCH`.
- Produces: `review outcome DEFECT --reason-code DIAGNOSABILITY_VIOLATION --finding FND-nnn`.

- [ ] **Step 1: Write failing Gate/routing tests**

```python
# tests/test_diagnosability_gate.py

def test_q2_required_contract_blocks_without_review(harness):
    set_risk(harness, level="Q2", profile="STANDARD")
    write_contract(harness, required=True)
    status, blockers = run_gate(harness)
    assert status == "BLOCKED"
    assert any(item.code == "DIAGNOSABILITY_REVIEW_MISSING" for item in blockers)


def test_q2_not_required_contract_does_not_require_review(harness):
    set_risk(harness, level="Q2", profile="STANDARD")
    write_contract(harness, required=False)
    status, blockers = run_gate(harness)
    assert "DIAGNOSABILITY_REVIEW_MISSING" not in {item.code for item in blockers}


def test_q3_rejects_default_not_assessed_contract(harness):
    set_risk(harness, level="Q3", profile="STRICT")
    status, blockers = run_gate(harness)
    assert any(item.code == "OBSERVABILITY_CONTRACT_INVALID" for item in blockers)
```

```python
# tests/test_review_outcome.py

def test_diag_violation_routes_reviewing_to_reproducing(repo):
    result = cli(repo, "review", "outcome", "DEFECT", "--reason-code", "DIAGNOSABILITY_VIOLATION", "--finding", "FND-004")
    assert result.returncode == 0
    assert task_state(repo) == "REPRODUCING"
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest tests/test_diagnosability_gate.py tests/test_review_outcome.py tests/test_status_projection.py -q
```

Expected: FAIL because no diagnostability Gate policy or controlled reason code exists.

- [ ] **Step 3: Implement Gate policy and status projection**

Add default policy:

```yaml
diagnosability:
  standard: required_when_contract_required
  strict: required
  blocking: [critical, major]
```

Before generic Finding proof checks, branch on `finding.category == "diagnosability"`: do not call generic RED/GREEN `finding_proof`; for `VERIFIED`/`CLOSED`, call `validate_compliance_closure` against its canonical diagnosability review. Keep generic proof checks byte-for-byte behavior for all other Findings.

Call `diagnosability.gate_blockers(...)` after normal evidence loading and before generic Finding checks. It must not scan source. It reads only task risk, Contract, canonical review evidence, Findings, and current snapshot. It emits typed blockers with existing blocker categories/recovery targets:

- missing/stale review: `verification` → `VERIFYING`
- invalid Contract/scope/linkage: `implementation` → `IMPLEMENTING`

Extend `RECOVERY_POLICY` in `blockers.py` for every new code. Extend review reason code sets and task schema only for `DIAGNOSABILITY_VIOLATION` under `DEFECT`. Update status renderer to print Contract required state and diagnosability review projection when artifact exists; status remains read-only.

- [ ] **Step 4: Run focused tests to verify pass**

Run:

```bash
pytest tests/test_diagnosability_gate.py tests/test_review_outcome.py tests/test_status_projection.py tests/test_quality_gate.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Gate unit**

```bash
git add src/harness/templates/gate.yaml src/harness/quality_gate.py src/harness/review_outcome.py src/harness/schemas/task.schema.json src/harness/harness_status.py src/harness/blockers.py tests/test_diagnosability_gate.py tests/test_review_outcome.py tests/test_status_projection.py
git commit -m "feat: gate production diagnosability review"
```

### Task 5: Add worker skills and acceptance fixture corpus

**Files:**
- Create: `skills/diagnosability-review/SKILL.md`
- Modify: `skills/task-contract/SKILL.md`
- Modify: `skills/engineering-harness/SKILL.md`
- Create: `tests/fixtures/diagnosability/pure-calculation.yaml`
- Create: `tests/fixtures/diagnosability/payment-timeout.yaml`
- Create: `tests/fixtures/diagnosability/state-transition.yaml`
- Create: `tests/fixtures/diagnosability/duplicate-refund.yaml`
- Create: `tests/fixtures/diagnosability/sensitive-request-log.yaml`
- Create: `tests/fixtures/diagnosability/low-value-logging.yaml`
- Create: `tests/fixtures/diagnosability/diagnosable-bugfix.yaml`
- Modify: `tests/test_diagnosability.py`
- Modify: `tests/test_readme_docs.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Consumes: Contract and review schemas from Tasks 1–2.
- Produces: agent-readable artifact formats and risk routing; fixtures become stable policy examples.

- [ ] **Step 1: Write failing fixture and documentation tests**

```python
# tests/test_diagnosability.py
@pytest.mark.parametrize("fixture", Path("tests/fixtures/diagnosability").glob("*.yaml"))
def test_diagnosability_fixture_contracts_validate(fixture):
    case = yaml.safe_load(fixture.read_text())
    validate_contract(case["contract"], task_type=case["task_type"])
    validate_review_input(case["review"], task_id="TASK-001")


def test_sensitive_fixture_requires_critical_finding():
    case = load_fixture("sensitive-request-log.yaml")
    assert case["finding"]["reason_code"] == "DIAG_SENSITIVE_DATA_LOGGED"
    assert case["finding"]["severity"] == "critical"
```

Add README/skill tests requiring text for `observability.yaml`, `harness review diagnosability`, Q1 light check, Q2 conditional review, Q3 mandatory review, and `DIAGNOSABILITY_VIOLATION`.

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_readme_docs.py -q
```

Expected: FAIL because fixtures and skill/documentation contracts do not exist.

- [ ] **Step 3: Write skills, fixtures, and docs**

`skills/diagnosability-review/SKILL.md` must require Agent to:

1. Read `observability.yaml`, changed files, direct dependencies, existing logging/correlation/masking/exception conventions.
2. Review only Contract scope.
3. Produce checks for seven canonical names.
4. Create only concrete `FND-*` DIAG attempts with location, business scenario, linked REQ target, and severity.
5. Never add generic logger advice, full object logging, automatic code changes, or claims beyond reviewed scope.

Update task-contract skill to fill Contract only for Q2/Q3, create linked `must` REQ only when required, and record bugfix gap true/false. Update engineering-harness skill with exact Q0/Q1/Q2/Q3 route from Global Constraints.

Write fixtures with these exact semantic outcomes:

| Fixture | Required behavior |
|---|---|
| `pure-calculation.yaml` | `required: false`; all review checks `not_applicable`; no Finding. |
| `payment-timeout.yaml` | `required: true`; external-failure check fails; major `DIAG_MISSING_EXTERNAL_FAILURE_CONTEXT`. |
| `state-transition.yaml` | `required: true`; transition check fails; major `DIAG_MISSING_STATE_TRANSITION`. |
| `duplicate-refund.yaml` | caller rejection has stable reason code and INFO/WARN; no ERROR Finding. |
| `sensitive-request-log.yaml` | sensitive-data check fails; critical `DIAG_SENSITIVE_DATA_LOGGED`. |
| `low-value-logging.yaml` | low-value check fails; minor `DIAG_LOW_VALUE_LOGGING`. |
| `diagnosable-bugfix.yaml` | bugfix `observability_gap: false`; no logging improvement requirement. |

Add README concise routing and non-goals section. Do not claim universal source scanning or guaranteed production diagnosis.

- [ ] **Step 4: Run focused tests to verify pass**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_readme_docs.py tests/test_package_resources.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit skills and fixture unit**

```bash
git add skills/diagnosability-review/SKILL.md skills/task-contract/SKILL.md skills/engineering-harness/SKILL.md tests/fixtures/diagnosability tests/test_diagnosability.py tests/test_readme_docs.py README.md README.zh-CN.md
git commit -m "docs: add diagnosability review workflow"
```

### Task 6: Run release-focused regression and inspect package contents

**Files:**
- Modify only if tests expose a defect in Tasks 1–5.
- Test: all newly added tests plus resource/package tests.

**Interfaces:**
- Consumes: all completed feature interfaces.
- Produces: fresh release evidence only; no new behavior.

- [ ] **Step 1: Run focused feature suite**

Run:

```bash
pytest tests/test_diagnosability.py tests/test_cli_diagnosability.py tests/test_diagnosability_lifecycle.py tests/test_diagnosability_gate.py tests/test_finding_schema.py tests/test_finding_transition.py tests/test_quality_gate.py tests/test_review_outcome.py tests/test_status_projection.py -q
```

Expected: PASS.

- [ ] **Step 2: Run packaging/resource regression**

Run:

```bash
pytest tests/test_init.py tests/test_package_resources.py tests/test_wheel_isolation.py tests/test_npm_package.py -q
```

Expected: PASS. New schemas/templates must be present in Python wheel; new skills must be included by existing npm `skills/**` allowance.

- [ ] **Step 3: Inspect changed scope and artifacts**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only planned files plus user pre-existing workspace files are changed.

- [ ] **Step 4: Commit release regression fixes only when needed**

If Steps 1–3 require source/test fixes:

```bash
git add <only-files-fixed-by-regression>
git commit -m "fix: complete diagnosability regression coverage"
```

If all pass without changes, do not create an empty commit.

## Plan self-review

### Spec coverage

| Spec requirement | Plan task |
|---|---|
| Q0/Q1/Q2/Q3 routing | Task 4 policy; Task 5 skills/docs |
| Observability Contract and bugfix gap | Task 1 |
| Semantic review artifact and calculated scope | Task 2 |
| DIAG reason codes, critical sensitive data, compliance proof | Task 3 |
| Gate policy, stale review, severity blocking, review outcome | Task 4 |
| Existing-project conventions and non-goals | Task 5 |
| Fixture corpus and unit/CLI/lifecycle/Gate verification | Tasks 1–6 |
| Package resource preservation | Tasks 1, 5, 6 |

### Consistency checks

- `diagnosability_review` is exact evidence type in Tasks 2–4.
- `DIAGNOSABILITY_VIOLATION` is exact controlled DEFECT reason in Tasks 4–5.
- `static_compliance` is only DIAG alternative lifecycle in Tasks 3–4.
- Every source artifact write occurs after validation and uses existing atomic-write patterns.
- No task introduces logging-platform behavior or generic source scanning.
