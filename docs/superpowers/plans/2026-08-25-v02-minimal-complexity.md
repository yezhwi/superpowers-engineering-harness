# Engineering Harness v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Harness-native Minimal Implementation Check and Complexity Reviewer capabilities, persisted as evidence/findings and enforced by workflow and gate.

**Architecture:** Skills perform contextual decisions. Small deterministic Python helpers validate and atomically persist Minimal Decision YAML and complexity findings/review evidence. Existing `.harness/evidence`, `.harness/findings`, CLI, state machine, and quality gate remain control plane.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema, pytest, git.

**Spec:** `docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md`

## Global Constraints

- Add no runtime dependency and no Ponytail integration.
- Do not add complexity budgets, scores, repo-wide audit, debt ledger, automatic refactoring, or automatic deletion.
- Preserve existing `FND-*` finding schema and reproduction lifecycle exactly.
- Complexity scope is only DELETE, REUSE, STDLIB, NATIVE, YAGNI, SHRINK.
- Complexity reviewer does not judge correctness, security, performance, coverage, requirements completeness, architecture, or style.
- All persistent writes are atomic.

---

## File Structure

| File | Responsibility |
|---|---|
| `schemas/minimal-implementation.schema.json` | Minimal Decision YAML contract and Decision Ladder constraints. |
| `schemas/finding.schema.json` | Add discriminated `CPLX-*` complexity finding branch while retaining existing `FND-*` branch. |
| `scripts/complexity.py` | Load schemas, validate Minimal Decision/review input, write records atomically, validate workflow prerequisites. |
| `src/harness/controlplane.py` | Thin wrappers for check/review commands and transition prerequisite checks. |
| `src/harness/cli.py` | Parse `check minimal` and `review complexity`. |
| `scripts/quality_gate.py` | Enforce required review evidence and block open HIGH complexity findings. |
| `templates/gate.yaml` | Default complexity gate policy. |
| `skills/minimal-implementation/SKILL.md` | Agent procedure for pre-implementation Decision Ladder. |
| `skills/complexity-reviewer/SKILL.md` | Agent procedure for post-verification diff review. |
| `tests/test_minimal_implementation.py` | Schema, short-circuit, persistence, and pre-implementation guard tests. |
| `tests/test_complexity_review.py` | Taxonomy, evidence, persistence, drift, and review guard tests. |
| `tests/test_quality_gate.py` | Complexity policy tests. |
| `tests/test_cli_init.py` or new `tests/test_cli_complexity.py` | CLI parsing/exit-code integration tests. |

## Task 1: Minimal Decision schema and persistence

**Files:**
- Create: `schemas/minimal-implementation.schema.json`
- Create: `scripts/complexity.py`
- Test: `tests/test_minimal_implementation.py`

**Interfaces:**
- Produces `validate_minimal_decision(document: dict) -> None`.
- Produces `write_minimal_decision(harness_dir: Path, document: dict) -> Path`.
- Decision artifact path is `.harness/evidence/minimal-implementation.yaml`.

- [ ] **Step 1: Write failing schema/short-circuit tests**

```python
def test_reuse_short_circuits_ladder(tmp_path):
    decision = valid_decision(reuse={"checked": True, "result": "found", "candidate": "src/date.py"})
    decision["checks"].update(skipped_tail())
    decision["decision"] = {"approach": "reuse", "rationale": "existing formatter"}
    validate_minimal_decision(decision)


def test_found_reuse_requires_skipped_tail():
    decision = valid_decision(reuse={"checked": True, "result": "found"})
    decision["checks"]["stdlib"] = {"checked": True, "result": "none"}
    with pytest.raises(ValidationError):
        validate_minimal_decision(decision)
```

- [ ] **Step 2: Run focused test RED**

Run: `python -m pytest tests/test_minimal_implementation.py -q`

Expected: FAIL because schema/helper does not exist.

- [ ] **Step 3: Define schema and minimal helper**

Implement exact check shape:

```yaml
version: 1
task: TASK-001
checks:
  existence: {checked: true, result: required}
  reuse: {checked: true, result: found, candidate: src/date.py}
  stdlib: {checked: false, result: skipped}
  native: {checked: false, result: skipped}
  existing_dependency: {checked: false, result: skipped}
  minimum_local_implementation: {checked: false, result: skipped}
decision:
  approach: reuse
  rationale: Existing formatter meets REQ-001.
```

Use `jsonschema.validate`. Add semantic validation in `validate_minimal_decision`: validate schema, reject checks after first `found` unless `checked: false, result: skipped`, and require approach matching first found check; `unnecessary` requires `existence.result: unnecessary`.

Use temp sibling file plus `Path.replace()` in `write_minimal_decision`.

- [ ] **Step 4: Add invalid decision and atomic persistence tests**

```python
def test_unnecessary_requires_unnecessary_existence():
    decision = valid_local_decision()
    decision["decision"]["approach"] = "unnecessary"
    with pytest.raises(ValidationError):
        validate_minimal_decision(decision)


def test_write_minimal_decision_uses_required_evidence_path(tmp_path):
    path = write_minimal_decision(tmp_path / ".harness", valid_local_decision())
    assert path == tmp_path / ".harness/evidence/minimal-implementation.yaml"
    assert yaml.safe_load(path.read_text())["version"] == 1
```

- [ ] **Step 5: Run focused test GREEN**

Run: `python -m pytest tests/test_minimal_implementation.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add schemas/minimal-implementation.schema.json scripts/complexity.py tests/test_minimal_implementation.py
git commit -m "feat: add minimal implementation decision validation"
```

## Task 2: CLI and pre-implementation workflow guard

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_minimal_implementation.py`
- Test: `tests/test_cli_complexity.py`

**Interfaces:**
- Produces `harness check minimal --file <yaml>`.
- Produces `cmd_check_minimal(source: Path) -> int`.
- `PLANNED -> IMPLEMENTING` returns exit 1 and `MINIMAL_IMPLEMENTATION_REQUIRED` when valid artifact absent.

- [ ] **Step 1: Write failing command and transition tests**

```python
def test_check_minimal_persists_valid_document(repo, decision_file):
    result = run_cli(repo, "check", "minimal", "--file", str(decision_file))
    assert result.returncode == 0
    assert (repo / ".harness/evidence/minimal-implementation.yaml").exists()


def test_planned_to_implementing_requires_minimal_evidence(repo):
    set_task_state(repo, "PLANNED")
    result = run_cli(repo, "transition", "IMPLEMENTING")
    assert result.returncode == 1
    assert "MINIMAL_IMPLEMENTATION_REQUIRED" in result.stderr
```

- [ ] **Step 2: Run focused test RED**

Run: `python -m pytest tests/test_minimal_implementation.py tests/test_cli_complexity.py -q`

Expected: FAIL because command and guard do not exist.

- [ ] **Step 3: Wire thin CLI/control-plane command**

Add nested parser `check minimal` with required `--file`. `cmd_check_minimal` loads YAML mapping, verifies task ID equals `current-task.yaml.task.id`, calls Task 1 helper, and maps validation/I/O errors to exit 2. In `cmd_transition`, before existing state-machine check, require valid artifact only for `current == "PLANNED" and target == "IMPLEMENTING"`.

- [ ] **Step 4: Add malformed file and wrong task tests**

```python
def test_check_minimal_rejects_task_mismatch(repo, decision_file):
    write_task(decision_file, "TASK-999")
    result = run_cli(repo, "check", "minimal", "--file", str(decision_file))
    assert result.returncode == 2
    assert "task mismatch" in result.stderr
```

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_minimal_implementation.py tests/test_cli_complexity.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/cli.py src/harness/controlplane.py tests/test_minimal_implementation.py tests/test_cli_complexity.py
git commit -m "feat: require minimal decision before implementation"
```

## Task 3: Complexity finding schema and review persistence

**Files:**
- Modify: `schemas/finding.schema.json`
- Modify: `scripts/complexity.py`
- Test: `tests/test_complexity_review.py`

**Interfaces:**
- Produces `validate_complexity_finding(document: dict) -> None`.
- Produces `write_complexity_review(harness_dir: Path, review: dict) -> list[Path]`.
- Review input has `task`, `base`, `head`, and `findings`; writes `.harness/evidence/complexity-review.json` with type `review` and one `CPLX-NNN.yaml` per finding.

- [ ] **Step 1: Write failing taxonomy and acceptance tests**

```python
@pytest.mark.parametrize("kind", ["delete", "reuse", "stdlib", "native", "yagni", "shrink"])
def test_complexity_taxonomy_is_valid(kind):
    validate_complexity_finding(valid_finding(type=kind))


def test_accepted_finding_requires_reason():
    with pytest.raises(ValidationError):
        validate_complexity_finding(valid_finding(status="accepted"))
```

- [ ] **Step 2: Run focused test RED**

Run: `python -m pytest tests/test_complexity_review.py -q`

Expected: FAIL because `CPLX-*` records are not schema-valid.

- [ ] **Step 3: Add discriminated finding branch and writer**

Keep existing FND requirements in one `oneOf` branch. Add CPLX branch requiring:

```yaml
id: CPLX-001
category: complexity
type: reuse
severity: high
status: open
location: {file: src/date_helper.py, line: 12}
summary: Duplicate date formatter.
reason: Existing src/date.py exports format_date.
evidence: {existing_candidate: src/date.py, changed_file: src/date_helper.py}
recommendation: Reuse format_date.
```

Require `acceptance_reason` for `accepted`. Writer rejects duplicate IDs, validates each finding, atomically writes YAML records, then writes JSON review evidence containing `type: review`, current git commit, workspace fingerprints, `base`, `head`, and `finding_ids`.

- [ ] **Step 4: Add decision-drift and necessary-complexity tests**

```python
def test_reuse_finding_captures_minimal_decision_drift(tmp_path):
    finding = valid_finding(type="reuse", evidence={
        "minimal_decision": "reuse", "selected_candidate": "src/date.py",
        "actual_implementation": "src/new_date_service.py",
    })
    validate_complexity_finding(finding)


def test_audit_requirement_support_means_no_finding():
    review = valid_review(findings=[])
    assert write_complexity_review(harness_dir, review) == []
```

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_complexity_review.py tests/test_finding_schema.py -q`

Expected: PASS; existing FND lifecycle suite remains green.

- [ ] **Step 6: Commit**

```bash
git add schemas/finding.schema.json scripts/complexity.py tests/test_complexity_review.py
git commit -m "feat: persist complexity review findings"
```

## Task 4: Complexity review CLI and post-verification guard

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_complexity_review.py`
- Test: `tests/test_cli_complexity.py`

**Interfaces:**
- Produces `harness review complexity --file <yaml>`.
- Produces `cmd_review_complexity(source: Path) -> int`.
- `VERIFYING -> REVIEWING` returns exit 1 and `COMPLEXITY_REVIEW_REQUIRED` when fresh review evidence absent.

- [ ] **Step 1: Write failing review command/guard tests**

```python
def test_review_complexity_writes_findings_and_review_evidence(repo, review_file):
    result = run_cli(repo, "review", "complexity", "--file", str(review_file))
    assert result.returncode == 0
    assert (repo / ".harness/findings/CPLX-001.yaml").exists()
    assert (repo / ".harness/evidence/complexity-review.json").exists()


def test_verifying_to_reviewing_requires_fresh_complexity_review(repo):
    set_task_state(repo, "VERIFYING")
    result = run_cli(repo, "transition", "REVIEWING")
    assert result.returncode == 1
    assert "COMPLEXITY_REVIEW_REQUIRED" in result.stderr
```

- [ ] **Step 2: Run focused test RED**

Run: `python -m pytest tests/test_complexity_review.py tests/test_cli_complexity.py -q`

Expected: FAIL because command and guard do not exist.

- [ ] **Step 3: Implement CLI/control-plane review wrapper**

Add nested parser `review complexity` with required `--file`. Validate YAML review task against current task, verify review `head` equals `git rev-parse HEAD`, call Task 3 writer, and emit IDs. In transition guard, load `complexity-review.json`, require matching HEAD and current workspace fingerprint for `VERIFYING -> REVIEWING`.

- [ ] **Step 4: Add stale-review and malformed-finding tests**

```python
def test_review_complexity_rejects_stale_head(repo, review_file):
    write_review_head(review_file, "0" * 40)
    assert run_cli(repo, "review", "complexity", "--file", str(review_file)).returncode == 2


def test_review_complexity_rejects_finding_without_evidence(repo, review_file):
    remove_finding_field(review_file, "evidence")
    assert run_cli(repo, "review", "complexity", "--file", str(review_file)).returncode == 2
```

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_complexity_review.py tests/test_cli_complexity.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/cli.py src/harness/controlplane.py tests/test_complexity_review.py tests/test_cli_complexity.py
git commit -m "feat: require complexity review before reviewing"
```

## Task 5: Gate policy and templates

**Files:**
- Modify: `scripts/quality_gate.py`
- Modify: `templates/gate.yaml`
- Test: `tests/test_quality_gate.py`

**Interfaces:**
- Consumes `.harness/evidence/complexity-review.json` and `CPLX-*` records.
- `run_gate()` adds `missing complexity-review evidence` and `High complexity finding CPLX-NNN is open` blockers.

- [ ] **Step 1: Write failing gate-policy tests**

```python
def test_required_complexity_review_missing_blocks(tmp_path):
    h = make_harness(tmp_path)
    enable_complexity_policy(h)
    result = _gate(h)
    assert result.returncode == 1
    assert "missing complexity-review evidence" in result.stdout


def test_open_high_complexity_finding_blocks(tmp_path):
    h = make_harness(tmp_path)
    enable_complexity_policy(h)
    write_fresh_complexity_review(h)
    write_complexity_finding(h, valid_finding(id="CPLX-001", severity="high", status="open"))
    assert "High complexity finding CPLX-001 is open" in _gate(h).stdout
```

- [ ] **Step 2: Run focused test RED**

Run: `python -m pytest tests/test_quality_gate.py -q`

Expected: FAIL because complexity policy is ignored.

- [ ] **Step 3: Add deterministic gate policy**

Add template policy:

```yaml
complexity:
  required: true
  blocking:
    - high
```

In gate, validate complexity review JSON through existing evidence schema plus required review metadata. When policy required, require fresh commit/workspace fingerprints. Load only `CPLX-*` findings; block `status: open` whose severity lower-case is in configured blocking list. Do not block open medium/low. Treat resolved/accepted as non-open; schema enforces acceptance reason.

- [ ] **Step 4: Add non-blocking and accepted tests**

```python
@pytest.mark.parametrize("severity", ["medium", "low"])
def test_open_nonblocking_complexity_findings_do_not_block(tmp_path, severity):
    h = complete_complexity_ready_harness(tmp_path)
    write_complexity_finding(h, valid_finding(severity=severity, status="open"))
    assert _gate(h).returncode == 0


def test_accepted_high_complexity_finding_does_not_block(tmp_path):
    h = complete_complexity_ready_harness(tmp_path)
    write_complexity_finding(h, valid_finding(severity="high", status="accepted", acceptance_reason="REQ-017 compatibility"))
    assert _gate(h).returncode == 0
```

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_quality_gate.py tests/test_complexity_review.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/quality_gate.py templates/gate.yaml tests/test_quality_gate.py
git commit -m "feat: gate high complexity findings"
```

## Task 6: Skills, documentation, full regression, and dogfood

**Files:**
- Create: `skills/minimal-implementation/SKILL.md`
- Create: `skills/complexity-reviewer/SKILL.md`
- Modify: `README.md`
- Test: `tests/test_cli_complexity.py`

**Interfaces:**
- Skill output files are Task 1 and Task 3 contracts.
- README documents commands, phase placement, and HIGH/MEDIUM/LOW policy.

- [ ] **Step 1: Write failing skill/documentation presence tests**

```python
def test_v02_skills_are_packaged_and_documented():
    assert (REPO / "skills/minimal-implementation/SKILL.md").is_file()
    assert (REPO / "skills/complexity-reviewer/SKILL.md").is_file()
    readme = (REPO / "README.md").read_text()
    assert "harness check minimal" in readme
    assert "harness review complexity" in readme
```

- [ ] **Step 2: Run focused test RED**

Run: `python -m pytest tests/test_cli_complexity.py::test_v02_skills_are_packaged_and_documented -q`

Expected: FAIL because files and command documentation do not exist.

- [ ] **Step 3: Write both Skills and README usage**

Minimal Skill requires search evidence for EXISTENCE, REUSE, STDLIB, NATIVE, existing dependency, local implementation; permits first-positive short-circuit; calls `harness check minimal --file`. Complexity Skill restricts findings to fixed taxonomy, requires concrete evidence and context, avoids prohibited review axes, writes no finding for requirement/invariant-supported complexity, and calls `harness review complexity --file`. README adds both commands and workflow order.

- [ ] **Step 4: Run focused test GREEN**

Run: `python -m pytest tests/test_cli_complexity.py::test_v02_skills_are_packaged_and_documented -q`

Expected: PASS.

- [ ] **Step 5: Run regression suite**

Run: `python -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 6: Dogfood current diff**

Create Minimal Decision for this task, run `harness check minimal`, create complexity review input for `git diff HEAD~1..HEAD`, then run `harness review complexity`. Record no finding unless concrete evidence supports one. Verify no new dependencies, factories, registries, budget/score/audit/debt features.

- [ ] **Step 7: Commit**

```bash
git add skills/minimal-implementation/SKILL.md skills/complexity-reviewer/SKILL.md README.md tests/test_cli_complexity.py
git commit -m "docs: add v0.2 workflow skills"
```

## Plan self-review

- Spec coverage: Tasks 1–2 implement PREVENT and short-circuit; Tasks 3–4 implement six-type DETECT plus drift; Task 5 enforces HIGH-only gate; Task 6 implements Skills, docs, full regression, and dogfood.
- Placeholder scan: no TBD/TODO or unspecified test steps.
- Type consistency: CLI wrappers use `Path`; decision/review writer contracts originate in `scripts/complexity.py`; all persisted paths match spec.
