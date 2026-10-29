"""Counterexamples for Guard/Gate separation and convergence write safety."""

import ast
import inspect
from functools import partial
from pathlib import Path

import pytest
import yaml
from test_autonomous_convergence import _seal_alignment, run_cli
from test_autonomous_convergence import make_repo as _make_repo

from harness import alignment, controlplane
from harness.blockers import GateBlocker, select_recovery

make_repo = partial(_make_repo, trusted_scope=True)
ROOT = Path(__file__).resolve().parents[1]


def _guidance_section(path, heading):
    text = (ROOT / path).read_text()
    assert heading in text, f"missing guidance section: {heading} in {path}"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md"])
def test_evidence_scheduling_preplans_complete_bounded_batches(path):
    section = _guidance_section(path, "## Efficient Evidence Scheduling")
    # Machine-check public references, not synonyms or explanatory sentences.
    # Semantic constraints are reviewed by a human, not inferred from phrases.
    for identifier in ("harness evidence plan --json", "harness impact reconcile",
                       "--covered-test", "harness context --compact", "harness context validate"):
        assert identifier in section


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md"])
def test_registry_publication_stays_with_the_user(path):
    section = _guidance_section(path, "## Hard Boundaries")
    for identifier in ("npm publish", "twine upload", "uv publish", "transaction.publish"):
        assert identifier in section


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md"])
def test_execution_guidance_has_inline_route_and_no_orchestrator_only_rule(path):
    """Static routing regression, not an Agent compliance experiment."""
    text = (ROOT / path).read_text()
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert "MUST NOT implement business code itself" not in metadata["description"]
    assert "You do NOT do the development work" not in text
    assert "Never write business code" not in text
    assert "Writing business code because" not in text
    section = _guidance_section(path, "## Executor Continuity")
    assert "executing-plans" in section
    assert "subagent-driven-development" in section
    assert "Do not start Codex" in section
    assert "pi --provider openai-codex" in section
    assert "fresh-context review" not in section
    assert "## Verification Failure Triage" in text
    reviewing = [line for line in text.splitlines() if line.startswith("| `REVIEWING` |")]
    assert reviewing and "Do not call Codex" in reviewing[0]


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md"])
def test_failure_triage_covers_setup_product_and_authority_without_new_states(path):
    """Check documented decision-table shape; prose needs human semantic review."""
    section = _guidance_section(path, "## Verification Failure Triage")
    rows = [line.strip().strip("|").split("|")
            for line in section.splitlines() if line.strip().startswith("|")]
    entries = {cells[0].strip(): [cell.strip() for cell in cells[1:]]
               for cells in rows[2:]}
    assert len(entries) == 3
    assert all(label and len(cells) == 2 and all(cells) for label, cells in entries.items())
    # These are actual Core protocol identifiers, not prescribed prose labels.
    assert "BUDGET_OVERRIDE_REQUIRED" in section
    assert "HALT_AND_WAIT" in section


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md", "skills/task-contract/SKILL.md"])
def test_missing_task_guidance_uses_public_init_not_template_copy(path):
    text = (ROOT / path).read_text()
    section = _guidance_section(path, "## Inputs")
    assert "harness init" in section
    assert "templates/current-task.yaml" not in text


def test_contract_exit_has_no_unused_task_counter_writes():
    text = (ROOT / "skills/task-contract/SKILL.md").read_text()
    for field in ("requirements.total", "invariants.total", "timestamps.updated_at"):
        assert field not in text
    assert "counters + state updated" not in text
    assert "harness transition PLANNED" in text


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md"])
def test_loop_skips_measurement_and_deprecated_commands(path):
    startup = _guidance_section(path, "## Session Startup")
    assert "scans the product tree" in startup
    commands = _guidance_section(path, "## Deterministic Commands")
    for identifier in (
        "harness converge",
        "harness benchmark",
        "harness review session",
        "harness review batches",
        "harness plan sync-markdown",
        "harness evidence plan --probe-launcher",
        "harness telemetry report",
        "token_estimate",
    ):
        assert identifier in commands
    routing = _guidance_section(path, "## Request Routing")
    assert "CLASSIFIED → IMPLEMENTING" in routing
    assert "Do not invoke task contract, minimal implementation, impact, or complexity ceremony." in routing


@pytest.mark.parametrize("path", ["SKILL.md", "skills/engineering-harness/SKILL.md"])
def test_deprecated_gate_wrapper_guidance_describes_refusal(path):
    text = (ROOT / path).read_text()
    section = text.split("`python scripts/quality_gate.py`", 1)[1].split("\n\n", 1)[0]
    assert "exit" in section and "2" in section
    assert "harness gate" in section
    assert "evaluates Gate without" not in section


def test_doc_verification_reference_resolves_and_mirrors_stay_identical():
    root = (ROOT / "SKILL.md").read_bytes()
    assert root == (ROOT / "skills/engineering-harness/SKILL.md").read_bytes()
    marker = "## Documentation Verification"
    assert marker in root.decode()
    assert "engineering-harness" in _guidance_section(
        "skills/collect-evidence/SKILL.md", marker
    )


def test_collection_batch_proof_is_genuine_qualified_and_fail_stop():
    section = _guidance_section(
        "skills/collect-evidence/SKILL.md", "## Plan and Reuse Before Execution"
    )
    for identifier in ("harness evidence plan --json", "harness evidence run",
                       "--covered-test", "--scope related", "--reuse-if-valid", "can_reuse_evidence"):
        assert identifier in section


@pytest.mark.parametrize('filename,code', [('impact.yaml', 'IMPACT_CONTRACT_INVALID'),
                                          ('alignment-freeze.yaml', 'ALIGNMENT_FREEZE_INVALID')])
def test_secondary_live_yaml_error_is_bounded_at_source(tmp_path, monkeypatch, filename, code):
    from pathlib import Path

    from harness import quality_gate
    from harness.telemetry_lock import telemetry_lock

    root = make_repo(tmp_path, state='GATING')
    _seal_alignment(root)
    monkeypatch.chdir(tmp_path)
    task_path = root / 'current-task.yaml'
    before = task_path.read_bytes()
    task = yaml.safe_load(before)
    real = controlplane.source_access.read_text
    injected = False

    def malformed(path):
        nonlocal injected
        if Path(path).name == filename:
            injected = True
            return 'secret_payload_not_for_stderr: [invalid'
        return real(path)

    monkeypatch.setattr(controlplane.source_access, 'read_text', malformed)
    with telemetry_lock(root), pytest.raises(quality_gate.InvalidHarnessState, match=code) as error:
        quality_gate._append_live_alignment_drift(root, task, [], lambda *args, **kwargs: None)
    assert injected, 'counterexample must reach actual malformed secondary read'
    assert 'secret_payload_not_for_stderr' not in str(error.value)
    assert task_path.read_bytes() == before


def test_only_gate_emits_convergence_decision():
    """Catch future non-Gate CLI shortcuts, including state-machine bypasses."""
    tree = ast.parse(inspect.getsource(controlplane))
    decision_emitters = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in {"print", "_committed_print"}:
                continue
            if any(
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.startswith("DECISION:")
                for arg in call.args
                for value in ast.walk(arg)
            ):
                decision_emitters.add(node.name)
    assert decision_emitters == {"_cmd_gate_convergence"}


@pytest.mark.parametrize("emitter", ["print", "_committed_print"])
def test_convergence_emitter_check_detects_unauthorized_wrapper(monkeypatch, emitter):
    source = (
        'def _cmd_gate_convergence():\n    _committed_print("DECISION: CONVERGED")\n'
        f'def unauthorized():\n    {emitter}("DECISION: CONVERGED")\n'
    )
    monkeypatch.setattr(inspect, "getsource", lambda _module: source)
    with pytest.raises(AssertionError):
        test_only_gate_emits_convergence_decision()


def test_stale_guard_blocker_cannot_override_current_passing_gate(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["gate"]["blocked_by"] = [
        {
            "code": "CONTRACT_CHANGED",
            "category": "implementation",
            "message": "previously changed",
            "finding_id": "FND-999",
            "recover_to": "ESCALATED",
        }
    ]
    task_path.write_text(yaml.safe_dump(task))

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 0, result.stderr
    assert "DECISION: CONVERGED" in result.stdout
    assert yaml.safe_load(task_path.read_text())["gate"]["blocked_by"] == []


def test_gate_rejects_non_gating_state_without_writes(tmp_path):
    harness_dir = make_repo(tmp_path, state="IMPLEMENTING")
    task_path = harness_dir / "current-task.yaml"
    before = task_path.read_bytes()

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 1
    assert task_path.read_bytes() == before
    assert "DECISION:" not in result.stdout


def test_resume_cannot_turn_user_authority_marker_into_escalation(tmp_path):
    harness_dir = make_repo(tmp_path, state="BLOCKED")
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["gate"]["blocked_by"] = [
        {
            "code": "CONTRACT_CHANGED",
            "category": "implementation",
            "message": "user decision required",
            "recover_to": "ESCALATED",
        }
    ]
    task_path.write_text(yaml.safe_dump(task))
    before = task_path.read_bytes()

    result = run_cli(tmp_path, "resume")

    assert result.returncode != 0
    assert task_path.read_bytes() == before
    assert select_recovery([GateBlocker("CONTRACT_CHANGED", "implementation", "drift")]) is None


def test_gate_assessment_error_after_validation_does_not_write_task(tmp_path, monkeypatch, capsys):
    harness_dir = make_repo(tmp_path, state="GATING")
    (harness_dir / "evidence" / "unit-test.json").unlink()
    task_path = harness_dir / "current-task.yaml"
    before = task_path.read_bytes()
    monkeypatch.chdir(tmp_path)

    def fail_findings(_harness_dir):
        raise controlplane.HarnessStateError("FINDING_STATE_INVALID")

    monkeypatch.setattr(controlplane, "_findings", fail_findings)
    assert controlplane.cmd_gate() == 2
    assert "INVALID_HARNESS_STATE" in capsys.readouterr().err
    assert task_path.read_bytes() == before


def test_invalid_convergence_metadata_rejects_gate_without_writes(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["convergence"] = {"fingerprint": "sha256:old", "count": 0}
    task_path.write_text(yaml.safe_dump(task))
    before = task_path.read_bytes()

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 2
    assert task_path.read_bytes() == before
    assert "DECISION:" not in result.stdout


def test_non_gate_task_save_propagates_telemetry_failure(tmp_path, monkeypatch):
    harness_dir = make_repo(tmp_path, state="IMPLEMENTING")
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())

    def fail_telemetry(*_args):
        raise OSError("telemetry disk full")

    monkeypatch.setattr(controlplane.telemetry, "update_telemetry", fail_telemetry)
    with pytest.raises(OSError, match="telemetry disk full"):
        controlplane.save_task(harness_dir, task)


def test_gate_telemetry_failure_after_commit_reports_decision(tmp_path, monkeypatch, capsys):
    harness_dir = make_repo(tmp_path, state="GATING")
    monkeypatch.chdir(tmp_path)

    def fail_telemetry(*_args):
        raise OSError("telemetry disk full")

    monkeypatch.setattr(controlplane.telemetry, "update_telemetry", fail_telemetry)
    result = controlplane.cmd_gate()
    captured = capsys.readouterr()

    assert result == 0
    assert "DECISION: CONVERGED" in captured.out
    assert "TELEMETRY_UPDATE_FAILED" in captured.err
    assert yaml.safe_load((harness_dir / "current-task.yaml").read_text())["state"] == "CONVERGED"


def test_lock_release_failure_after_commit_keeps_gate_decision(tmp_path, monkeypatch, capsys):
    harness_dir = make_repo(tmp_path, state="GATING")
    monkeypatch.chdir(tmp_path)

    import fcntl

    real = fcntl.flock
    releases = []

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            releases.append(fd)
            raise OSError("unlock failed")
        return real(fd, operation)

    monkeypatch.setattr(fcntl, "flock", failed_release)
    assert controlplane.cmd_gate() == 0
    assert len(releases) == 1
    captured = capsys.readouterr()
    assert "DECISION: CONVERGED" in captured.out
    assert "TELEMETRY_UPDATE_FAILED" in captured.err
    assert yaml.safe_load((harness_dir / "current-task.yaml").read_text())["state"] == "CONVERGED"


def test_task_rename_failure_does_not_emit_gate_decision(tmp_path, monkeypatch, capsys):
    harness_dir = make_repo(tmp_path, state="GATING")
    task_path = harness_dir / "current-task.yaml"
    before = task_path.read_bytes()
    monkeypatch.chdir(tmp_path)
    original_replace = controlplane.Path.replace

    def fail_task_replace(path, target):
        if path.name == "current-task.yaml.tmp":
            raise OSError("task disk full")
        return original_replace(path, target)

    monkeypatch.setattr(controlplane.Path, "replace", fail_task_replace)
    assert controlplane.cmd_gate() == 2
    captured = capsys.readouterr()
    assert "GATE_IO_FAILED" in captured.err
    assert "DECISION:" not in captured.out
    assert task_path.read_bytes() == before


def test_continue_directive_only_on_continue(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    (harness_dir / "evidence" / "unit-test.json").unlink()

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 0
    assert "DECISION: CONTINUE" in result.stdout
    assert result.stdout.count("DIRECTIVE:") == 1
    assert "DIRECTIVE: RESUME_TYPED_RECOVERY" in result.stdout


def test_converged_directive_is_none(tmp_path):
    make_repo(tmp_path, state="GATING")
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "DECISION: CONVERGED" in result.stdout
    assert result.stdout.count("DIRECTIVE:") == 1
    assert "DIRECTIVE: NONE" in result.stdout


def test_escalated_directive_is_none(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["iteration"] = task["max_iterations"]
    task_path.write_text(yaml.safe_dump(task))
    (harness_dir / "evidence" / "unit-test.json").unlink()
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "DECISION: ESCALATED" in result.stdout
    assert result.stdout.count("DIRECTIVE:") == 1
    assert "DIRECTIVE: NONE" in result.stdout


def _standard_task(harness_dir):
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q2", "profile": "STANDARD",
        "dimensions": {
            "scope": "high", "contract": "high", "data": "none",
            "authorization": "none", "security": "none", "concurrency": "none",
            "deployment": "none",
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:test"},
    }
    task_path.write_text(yaml.safe_dump(task))
    return task_path


@pytest.mark.parametrize("case", ["missing", "unfrozen", "corrupt_seal"])
def test_standard_gate_invalid_alignment_fails_closed_without_writing(tmp_path, case):
    harness_dir = make_repo(tmp_path, state="GATING")
    task_path = _standard_task(harness_dir)
    if case != "missing":
        document = _seal_alignment(harness_dir)
        if case == "unfrozen":
            document["freeze"] = {"frozen": False, "frozen_at": None, "contract_hash": None}
            (harness_dir / "alignment.yaml").write_text(yaml.safe_dump(document))
        else:
            (harness_dir / "alignment-freeze.yaml").write_text("broken: yes\n")
    before = task_path.read_bytes()

    result = run_cli(tmp_path, "gate")

    assert "DECISION:" not in result.stdout
    assert task_path.read_bytes() == before
    if case == "unfrozen":
        assert result.returncode == 1
        assert "ALIGNMENT_FREEZE_INVALID" in result.stderr
        assert "POLICY: USER_AUTHORITY_REQUIRED" not in result.stderr
        preflight = run_cli(tmp_path, "gate", "preflight")
        assert preflight.returncode == 1
        assert "ALIGNMENT_FREEZE_INVALID" in preflight.stderr
        assert "GATE_PREFLIGHT_INVALID" not in preflight.stderr
        assert "POLICY: USER_AUTHORITY_REQUIRED" not in preflight.stderr
        assert task_path.read_bytes() == before
    else:
        assert result.returncode == 2
        assert "INVALID_HARNESS_STATE" in result.stderr


def test_invalid_seal_rejects_verify_without_authority_or_audit_finding(tmp_path):
    harness_dir = make_repo(tmp_path, state="IMPLEMENTING")
    task_path = _standard_task(harness_dir)
    _seal_alignment(harness_dir)
    declared_path = tmp_path / 'tests/test_agent_guidance_contract.py'
    declared_path.parent.mkdir(exist_ok=True)
    declared_path.write_text('def test_fixture_declaration():\n    pass\n')
    declared = run_cli(tmp_path, 'impact', 'add-test', 'tests/test_agent_guidance_contract.py')
    assert declared.returncode == 0, declared.stdout + declared.stderr
    (harness_dir / "alignment-freeze.yaml").write_text("broken: yes\n")
    before = task_path.read_bytes()

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 1
    assert "ALIGNMENT_FREEZE_INVALID" in result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" not in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" not in result.stderr
    assert task_path.read_bytes() == before
    assert not list((harness_dir / "findings").glob("FND-*.yaml"))


def test_live_drift_attaches_matching_current_task_audit_finding(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    document["goal"]["summary"] = "changed"
    (harness_dir / "alignment.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "findings" / "FND-009.yaml").write_text(
        yaml.safe_dump({
            "id": "FND-009", "category": "alignment", "task_id": "TASK-001",
            "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
            "detected_during": "IMPLEMENTING", "reason_code": "CONTRACT_CHANGED",
            "boundary_ref": "alignment.yaml", "expected_hash": document["freeze"]["contract_hash"],
            "actual_hash": alignment.contract_hash(document),
        })
    )

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 0, result.stderr
    assert "DECISION: ESCALATED" in result.stdout
    blockers = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["gate"]["blocked_by"]
    assert next(b for b in blockers if b["code"] == "CONTRACT_CHANGED")["finding_id"] == "FND-009"


def test_new_hash_drift_creates_new_audit_record_without_overwriting_old(tmp_path):
    harness_dir = make_repo(tmp_path, state="IMPLEMENTING")
    document = _seal_alignment(harness_dir)
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    document["goal"]["summary"] = "first change"
    controlplane._record_contract_change(
        harness_dir, task, document, reason_code="CONTRACT_CHANGED", boundary_ref="alignment.yaml"
    )
    first = yaml.safe_load((harness_dir / "findings" / "FND-001.yaml").read_text())
    document["goal"]["summary"] = "second change"
    controlplane._record_contract_change(
        harness_dir, task, document, reason_code="CONTRACT_CHANGED", boundary_ref="alignment.yaml"
    )
    second = yaml.safe_load((harness_dir / "findings" / "FND-002.yaml").read_text())
    assert first["actual_hash"] != second["actual_hash"]
    assert yaml.safe_load((harness_dir / "findings" / "FND-001.yaml").read_text()) == first


def test_missing_seal_does_not_link_unprovable_same_hash_finding(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    (harness_dir / "alignment-freeze.yaml").unlink()
    (harness_dir / "findings" / "FND-009.yaml").write_text(yaml.safe_dump({
        "id": "FND-009", "category": "alignment", "task_id": "TASK-001",
        "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
        "detected_during": "IMPLEMENTING", "reason_code": "CONTRACT_CHANGED",
        "boundary_ref": "alignment.yaml", "expected_hash": document["freeze"]["contract_hash"],
        "actual_hash": document["freeze"]["contract_hash"],
    }))
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0, result.stderr
    blockers = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["gate"]["blocked_by"]
    assert next(b for b in blockers if b["code"] == "CONTRACT_CHANGED")["finding_id"] is None


def test_live_drift_does_not_attach_stale_hash_audit_finding(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    document["goal"]["summary"] = "different change"
    (harness_dir / "alignment.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "findings" / "FND-009.yaml").write_text(
        yaml.safe_dump({
            "id": "FND-009", "category": "alignment", "task_id": "TASK-001",
            "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
            "detected_during": "IMPLEMENTING", "reason_code": "CONTRACT_CHANGED",
            "boundary_ref": "alignment.yaml", "expected_hash": document["freeze"]["contract_hash"],
            "actual_hash": "sha256:" + "1" * 64,
        })
    )
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0, result.stderr
    blockers = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["gate"]["blocked_by"]
    assert next(b for b in blockers if b["code"] == "CONTRACT_CHANGED")["finding_id"] is None


@pytest.mark.parametrize("record_direction, expected_id", [(False, "FND-009"), (True, None)])
def test_scope_drift_finding_requires_matching_boundary_direction(tmp_path, record_direction, expected_id):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    impact_path = harness_dir / "impact.yaml"
    impact = yaml.safe_load(impact_path.read_text())
    impact["impact"]["contracts"] = [{"kind": "permission", "ref": "DEC-001"}]
    impact_path.write_text(yaml.safe_dump(impact))
    (harness_dir / "findings" / "FND-009.yaml").write_text(yaml.safe_dump({
        "id": "FND-009", "category": "alignment", "task_id": "TASK-001",
        "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
        "detected_during": "IMPLEMENTING", "reason_code": "SCOPE_DRIFT_PERMISSION",
        "boundary_ref": "DEC-001", "expected_hash": document["freeze"]["contract_hash"],
        "actual_hash": alignment.contract_hash(document),
        "expected_boundary_present": record_direction,
        "actual_boundary_present": not record_direction,
    }))

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0, result.stderr
    blockers = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["gate"]["blocked_by"]
    assert next(b for b in blockers if b["code"] == "SCOPE_DRIFT_PERMISSION")["finding_id"] == expected_id


def test_scope_drift_secondary_freeze_read_is_typed_invalid_state(tmp_path, monkeypatch, capsys):
    harness_dir = make_repo(tmp_path, state="GATING")
    _seal_alignment(harness_dir)
    impact = yaml.safe_load((harness_dir / "impact.yaml").read_text())
    impact["impact"]["contracts"] = [{"kind": "permission", "ref": "DEC-001"}]
    (harness_dir / "impact.yaml").write_text(yaml.safe_dump(impact))
    monkeypatch.chdir(tmp_path)
    real_read = controlplane.source_access.read_text
    reads = 0

    def corrupt_second_freeze_read(path):
        nonlocal reads
        if str(path).endswith("alignment-freeze.yaml"):
            reads += 1
            if reads == 2:
                return "not: [valid"
        return real_read(path)

    monkeypatch.setattr(controlplane.source_access, "read_text", corrupt_second_freeze_read)
    assert controlplane.cmd_gate() == 2
    assert "INVALID_HARNESS_STATE" in capsys.readouterr().err


def test_contract_changed_finding_with_scope_direction_is_invalid(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    document["goal"]["summary"] = "changed"
    (harness_dir / "alignment.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "findings" / "FND-009.yaml").write_text(yaml.safe_dump({
        "id": "FND-009", "category": "alignment", "task_id": "TASK-001",
        "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
        "detected_during": "IMPLEMENTING", "reason_code": "CONTRACT_CHANGED",
        "boundary_ref": "alignment.yaml", "expected_hash": document["freeze"]["contract_hash"],
        "actual_hash": alignment.contract_hash(document),
        "expected_boundary_present": False, "actual_boundary_present": True,
    }))
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 2
    assert "DECISION:" not in result.stdout


def test_scope_finding_with_partial_direction_is_invalid(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    (harness_dir / "findings" / "FND-009.yaml").write_text(yaml.safe_dump({
        "id": "FND-009", "category": "alignment", "task_id": "TASK-001",
        "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
        "detected_during": "IMPLEMENTING", "reason_code": "SCOPE_DRIFT_PERMISSION",
        "boundary_ref": "DEC-001", "expected_hash": document["freeze"]["contract_hash"],
        "actual_hash": alignment.contract_hash(document),
        "expected_boundary_present": False,
    }))
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 2
    assert "DECISION:" not in result.stdout


def test_live_drift_does_not_attach_other_tasks_audit_finding(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    document = _seal_alignment(harness_dir)
    document["goal"]["summary"] = "changed"
    (harness_dir / "alignment.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "findings" / "FND-009.yaml").write_text(
        yaml.safe_dump({
            "id": "FND-009", "category": "alignment", "task_id": "TASK-002",
            "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
            "detected_during": "IMPLEMENTING", "reason_code": "CONTRACT_CHANGED",
            "boundary_ref": "alignment.yaml", "expected_hash": "sha256:" + "0" * 64,
            "actual_hash": "sha256:" + "1" * 64,
        })
    )

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 0, result.stderr
    assert "DECISION: ESCALATED" in result.stdout
    blockers = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["gate"]["blocked_by"]
    assert next(b for b in blockers if b["code"] == "CONTRACT_CHANGED")["finding_id"] is None
