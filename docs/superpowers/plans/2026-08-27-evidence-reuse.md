# Evidence Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit, fail-closed same-task evidence reuse without weakening Gate evidence validity.

**Architecture:** Collector creates `ReuseRequest` from CLI inputs and asks a pure validator predicate whether existing generic evidence proves exact same successful work at current HEAD, workspace, and runtime. A hit returns without shell execution or file mutation; every miss uses existing collection/write path. Gate and status retain existing freshness behavior.

**Tech Stack:** Python 3.11, argparse, JSON Schema 2020-12, pytest, jsonschema.

**Spec:** `docs/superpowers/specs/2026-08-27-evidence-reuse-design.md`

## Global Constraints

- Only current task `.harness/evidence/`; no cross-task cache.
- Reuse only generic successful evidence with absent phase/Finding identity.
- Exact match: type, command, unit-test scope/covered-test set, HEAD, workspace before/after, and all runtime fields.
- Runtime fields: `implementation`, `version`, `executable`, `platform`.
- Cache miss is normal collection, never an error or silent proof promotion.
- Old/invalid evidence remains Gate-compatible but never reusable.
- Do not add state shortcuts, budgets, telemetry, benchmarks, or release work.

---

## File Structure

- `src/harness/collect_evidence.py`: runtime capture; request construction; no-execution reuse branch; runtime persistence.
- `src/harness/evidence_validator.py`: pure `ReuseRequest` and reuse predicate, separate from Gate validity projection.
- `src/harness/cli.py`: `--reuse-if-valid` parser/pass-through.
- `src/harness/controlplane.py`: passes reuse flag to packaged collector.
- `src/harness/schemas/evidence.schema.json`: optional runtime object schema.
- `tests/test_evidence.py`: collector behavior, actual no-shell-hit proof, metadata persistence.
- `tests/test_evidence_validator.py`: pure exact-match and fail-closed predicate tests.
- `tests/test_cli_evidence_reuse.py`: CLI flag wiring and normal-miss behavior.
- `README.md`, `README.zh-CN.md`: concise explicit reuse examples and constraints.

## Task 1: Runtime metadata and pure reuse policy

**Files:**
- Modify: `src/harness/schemas/evidence.schema.json`
- Modify: `src/harness/evidence_validator.py`
- Modify: `src/harness/collect_evidence.py`
- Modify: `tests/test_evidence_validator.py`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- Produces `runtime_metadata() -> dict[str, str]` with `implementation`, `version`, `executable`, `platform`.
- Produces `@dataclass(frozen=True) ReuseRequest(evidence_type: str, command: str, scope: str, covered_tests: tuple[str, ...], phase: str | None, finding_id: str | None, test_id: str | None)`.
- Produces `can_reuse_evidence(record: object, request: ReuseRequest, *, current_head: str, current_workspace: str, current_runtime: dict[str, str]) -> bool`.

- [ ] **Step 1: Write pure reuse policy failing tests**

```python
from harness.evidence_validator import ReuseRequest, can_reuse_evidence


def test_reuse_requires_exact_generic_successful_evidence(evidence_record):
    request = ReuseRequest("unit_test", "pytest tests/test_x.py", "related", ("tests/test_x.py",), None, None, None)
    record = evidence_record(
        type="unit_test", command="pytest tests/test_x.py", exit_code=0,
        scope="related", covered_tests=["tests/test_x.py"],
        runtime={"implementation": "CPython", "version": "3.11.10", "executable": "/python", "platform": "Linux-x86_64"},
    )
    assert can_reuse_evidence(record, request, current_head=record["commit"], current_workspace=record["workspace_fingerprint"], current_runtime=record["runtime"])


@pytest.mark.parametrize("mutate", [
    lambda record: record.__setitem__("command", "pytest other"),
    lambda record: record.__setitem__("exit_code", 1),
    lambda record: record.__setitem__("workspace_fingerprint_after", "sha256:" + "0" * 64),
    lambda record: record.__setitem__("runtime", {}),
    lambda record: record.__setitem__("subject", {"kind": "finding", "id": "FND-001"}),
])
def test_reuse_rejects_nonidentical_or_non_generic_proof(evidence_record, mutate):
    request = ReuseRequest("build", "python -m build", "related", (), None, None, None)
    record = evidence_record(type="build", command="python -m build", exit_code=0)
    mutate(record)
    assert not can_reuse_evidence(record, request, current_head=record["commit"], current_workspace=record["workspace_fingerprint"], current_runtime=record.get("runtime", {}))
```

- [ ] **Step 2: Run policy tests RED**

Run: `python -m pytest tests/test_evidence_validator.py -q`

Expected: FAIL because `ReuseRequest` and `can_reuse_evidence` do not exist.

- [ ] **Step 3: Add optional runtime schema and minimal policy implementation**

Add optional `runtime` object to evidence schema. Require its four string fields and reject extra fields when present; do not add it to top-level `required`.

```python
@dataclass(frozen=True)
class ReuseRequest:
    evidence_type: str
    command: str
    scope: str
    covered_tests: tuple[str, ...]
    phase: str | None
    finding_id: str | None
    test_id: str | None


def can_reuse_evidence(record, request, *, current_head, current_workspace, current_runtime):
    if not isinstance(record, dict) or request.phase or request.finding_id or request.test_id:
        return False
    if record.get("exit_code") != 0 or record.get("subject") is not None or record.get("test") is not None:
        return False
    if record.get("type") != request.evidence_type or record.get("command") != request.command:
        return False
    if request.evidence_type == "unit_test" and (
        record.get("scope") != request.scope
        or set(record.get("covered_tests", [])) != set(request.covered_tests)
    ):
        return False
    if record.get("commit") != current_head or record.get("workspace_fingerprint") != current_workspace:
        return False
    if record.get("workspace_fingerprint_after") != current_workspace:
        return False
    return record.get("runtime") == current_runtime and _schema_valid(record)
```

Implement `_schema_valid` using existing evidence schema loading/validation and return `False` for invalid content; never raise for a candidate cache record.

- [ ] **Step 4: Add runtime collection failing test**

```python
def test_collect_success_evidence_records_exact_runtime(tmp_path):
    result = _collect(tmp_path, "build", "true")
    assert result.returncode == 0
    runtime = json.loads((tmp_path / "evidence/build.json").read_text())["runtime"]
    assert set(runtime) == {"implementation", "version", "executable", "platform"}
    assert all(isinstance(value, str) and value for value in runtime.values())
```

- [ ] **Step 5: Run runtime test RED**

Run: `python -m pytest tests/test_evidence.py::test_collect_success_evidence_records_exact_runtime -q`

Expected: FAIL with missing `runtime`.

- [ ] **Step 6: Persist runtime metadata**

In `collect_evidence.py`, import `platform` and `sys` and implement:

```python
def runtime_metadata() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "executable": sys.executable,
        "platform": f"{platform.system()}-{platform.machine()}",
    }
```

Add `"runtime": runtime_metadata()` to all newly collected evidence records.

- [ ] **Step 7: Run Task 1 tests GREEN**

Run: `python -m pytest tests/test_evidence_validator.py tests/test_evidence.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/harness/schemas/evidence.schema.json src/harness/evidence_validator.py src/harness/collect_evidence.py tests/test_evidence_validator.py tests/test_evidence.py
git diff --cached --check
git commit -m "feat: define fail-closed evidence reuse policy"
```

## Task 2: Explicit collector and CLI reuse path

**Files:**
- Modify: `src/harness/collect_evidence.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_evidence.py`
- Create: `tests/test_cli_evidence_reuse.py`

**Interfaces:**
- Consumes `ReuseRequest`, `can_reuse_evidence`, `runtime_metadata`, and `evidence_filename` from Task 1.
- Extends `collect(..., reuse_if_valid: bool = False) -> dict` behavior through collector `main`.
- Extends `cmd_evidence(..., phase=None, reuse_if_valid: bool = False) -> int`.
- Produces `EVIDENCE_REUSED: <filename>` on reuse hit.

- [ ] **Step 1: Write collector no-execution failing test**

```python
def test_reuse_hit_does_not_execute_or_rewrite_evidence(tmp_path):
    marker = tmp_path / "ran"
    command = f"sh -c 'echo ran > {marker}'"
    assert _collect(tmp_path, "build", command).returncode == 0
    marker.unlink()
    path = tmp_path / "evidence/build.json"
    before = path.read_bytes()

    result = _collect(tmp_path, "build", command, reuse_if_valid=True)

    assert result.returncode == 0
    assert "EVIDENCE_REUSED: build.json" in result.stdout
    assert not marker.exists()
    assert path.read_bytes() == before
```

Extend `_collect` to append `--reuse-if-valid` only when requested.

- [ ] **Step 2: Run no-execution test RED**

Run: `python -m pytest tests/test_evidence.py::test_reuse_hit_does_not_execute_or_rewrite_evidence -q`

Expected: FAIL because parser does not accept flag and collector executes shell.

- [ ] **Step 3: Implement collector reuse branch**

Add `parser.add_argument("--reuse-if-valid", action="store_true")`. Before `collect()` invokes `subprocess.run`, create request and read only its deterministic generic candidate filename. If `can_reuse_evidence(...)` returns true, print exact reuse line and return `0`. Catch `OSError`, `json.JSONDecodeError`, and schema validation failure as cache miss. Do not read candidate for phase/Finding request; collect it normally.

- [ ] **Step 4: Write mismatch fallback failing tests**

```python
@pytest.mark.parametrize("second_command", ["false", "printf changed"])
def test_reuse_command_miss_executes_and_replaces_record(tmp_path, second_command):
    assert _collect(tmp_path, "build", "true").returncode == 0
    result = _collect(tmp_path, "build", second_command, reuse_if_valid=True)
    evidence = json.loads((tmp_path / "evidence/build.json").read_text())
    assert "EVIDENCE_REUSED" not in result.stdout
    assert evidence["command"] == second_command
```

Add these explicit tests; each asserts `returncode == 0`, no `EVIDENCE_REUSED` in stdout, and stored record has the second command:

```python
def test_reuse_covered_tests_miss_executes(tmp_path):
    assert _collect(tmp_path, "unit_test", "true", scope="related", covered_tests=["tests/a.py::test_a"]).returncode == 0
    result = _collect(tmp_path, "unit_test", "printf second", scope="related", covered_tests=["tests/b.py::test_b"], reuse_if_valid=True)
    assert "EVIDENCE_REUSED" not in result.stdout


def test_reuse_runtime_miss_executes(tmp_path):
    assert _collect(tmp_path, "build", "true").returncode == 0
    path = tmp_path / "evidence/build.json"
    record = json.loads(path.read_text()); record["runtime"]["version"] = "0.0.0"; path.write_text(json.dumps(record))
    result = _collect(tmp_path, "build", "printf second", reuse_if_valid=True)
    assert "EVIDENCE_REUSED" not in result.stdout


def test_reuse_malformed_record_executes(tmp_path):
    path = tmp_path / "evidence/build.json"; path.parent.mkdir(parents=True); path.write_text("{")
    result = _collect(tmp_path, "build", "printf second", reuse_if_valid=True)
    assert "EVIDENCE_REUSED" not in result.stdout


def test_reuse_phase_request_executes(tmp_path):
    result = _collect(tmp_path, "unit_test", "false", scope="related", covered_tests=["tests/a.py::test_a"], phase="red", reuse_if_valid=True)
    assert "EVIDENCE_REUSED" not in result.stdout
```

Extend `_collect` with optional `scope`, `covered_tests`, `phase`, and `reuse_if_valid` arguments that append their exact collector flags.

- [ ] **Step 5: Run fallback tests RED, then GREEN**

Run: `python -m pytest tests/test_evidence.py -q`

Expected before implementation: reuse parser rejection. After implementation: PASS.

- [ ] **Step 6: Write CLI wiring failing test**

```python
def test_cli_passes_reuse_flag_to_collector(tmp_path):
    setup(tmp_path)
    first = cli(tmp_path, "evidence", "--type", "build", "--command", "true")
    second = cli(tmp_path, "evidence", "--type", "build", "--command", "true", "--reuse-if-valid")
    assert first.returncode == second.returncode == 0
    assert "EVIDENCE_REUSED: build.json" in second.stdout
```

- [ ] **Step 7: Run CLI test RED**

Run: `python -m pytest tests/test_cli_evidence_reuse.py::test_cli_passes_reuse_flag_to_collector -q`

Expected: FAIL because harness CLI rejects `--reuse-if-valid`.

- [ ] **Step 8: Wire CLI and control plane**

Add `--reuse-if-valid` to `harness evidence` parser. Pass boolean into `cmd_evidence`; append `--reuse-if-valid` to collector args only when true. Preserve full-suite authorization check before reuse decision: ungranted full-suite request exits `2` even if a reusable record exists.

- [ ] **Step 9: Run Task 2 tests GREEN**

Run: `python -m pytest tests/test_evidence.py tests/test_cli_evidence_reuse.py tests/test_test_authorization.py -q`

Expected: PASS.

- [ ] **Step 10: Commit Task 2**

```bash
git add src/harness/collect_evidence.py src/harness/cli.py src/harness/controlplane.py tests/test_evidence.py tests/test_cli_evidence_reuse.py
git diff --cached --check
git commit -m "feat: reuse valid same-task evidence explicitly"
```

## Task 3: Documentation and regression verification

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_readme_docs.py`
- Modify: `tests/test_evidence_validator.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Documents explicit `--reuse-if-valid`; no new runtime output contract beyond `EVIDENCE_REUSED`.
- Consumes existing Gate tests to prove runtime remains optional for old records.

- [ ] **Step 1: Write documentation failing test**

```python
def test_readmes_document_explicit_fail_closed_evidence_reuse():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "--reuse-if-valid" in text
        assert "EVIDENCE_REUSED" in text
```

- [ ] **Step 2: Run documentation test RED**

Run: `python -m pytest tests/test_readme_docs.py::test_readmes_document_explicit_fail_closed_evidence_reuse -q`

Expected: FAIL because reuse is undocumented.

- [ ] **Step 3: Document behavior in both READMEs**

Add concise adjacent sections with this command pattern:

```bash
harness evidence --type build --command "python -m pip wheel . --no-deps" --reuse-if-valid
```

State that reuse is same-task only; needs exact command/proof identity, unchanged HEAD/workspace, exact runtime, and prior success; any mismatch runs command. State `EVIDENCE_REUSED` means no command ran.

- [ ] **Step 4: Add old-record compatibility test**

```python
def test_gate_accepts_pre_runtime_evidence_records(tmp_path):
    h = make_harness(tmp_path)
    for path in (h / "evidence").glob("*.json"):
        data = json.loads(path.read_text())
        data.pop("runtime", None)
        path.write_text(json.dumps(data))
    assert _gate(h).returncode == 0
```

- [ ] **Step 5: Run final focused regression suite**

Run: `python -m pytest tests/test_evidence.py tests/test_evidence_validator.py tests/test_cli_evidence_reuse.py tests/test_quality_gate.py tests/test_readme_docs.py tests/test_test_authorization.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add README.md README.zh-CN.md tests/test_readme_docs.py tests/test_evidence_validator.py tests/test_quality_gate.py
git diff --cached --check
git commit -m "docs: document explicit evidence reuse"
```

## Final verification

- [ ] Create a new Harness task; do not reuse completed `TASK-018`.
- [ ] Record requirements/invariants and Minimal Implementation evidence through Harness CLI.
- [ ] Request explicit current-task full-suite authorization before full suite.
- [ ] Run `harness evidence --type unit_test --scope full_suite --command "python -m pytest tests/ -q"`.
- [ ] Run `harness evidence --type build --command "python -m pip wheel . --no-deps --wheel-dir /tmp/harness-evidence-reuse-wheels"`.
- [ ] Record impact, run complexity review, verify requirements/invariants, route clean review through `harness review outcome PASS --reason-code REVIEW_CLEAN`, then `harness gate`.
- [ ] After Gate PASS, transition `CONVERGED → DONE`; run `git diff --check`.
