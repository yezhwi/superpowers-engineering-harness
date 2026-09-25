"""Counterexamples for Guard/Gate separation and convergence write safety."""

import ast
import importlib
import inspect
from contextlib import contextmanager

import pytest
import yaml
from test_autonomous_convergence import _seal_alignment, make_repo, run_cli

from harness import alignment, controlplane
from harness.blockers import GateBlocker, select_recovery


def test_only_gate_emits_convergence_decision():
    """Catch future non-Gate CLI shortcuts, including state-machine bypasses."""
    tree = ast.parse(inspect.getsource(controlplane))
    decision_emitters = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "print":
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

    @contextmanager
    def failed_lock(_harness_dir):
        yield
        raise OSError("unlock failed")

    monkeypatch.setattr(importlib.import_module("harness.telemetry_lock"), "telemetry_lock", failed_lock)
    assert controlplane.cmd_gate() == 0
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
    (harness_dir / "alignment-freeze.yaml").write_text("broken: yes\n")
    impact_path = harness_dir / "impact.yaml"
    impact = yaml.safe_load(impact_path.read_text())
    impact["impact"]["required_tests"] = ["tests/test_agent_guidance_contract.py"]
    impact_path.write_text(yaml.safe_dump(impact))
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
