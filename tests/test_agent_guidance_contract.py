"""Counterexamples for Guard/Gate separation and convergence write safety."""

import ast
import inspect

import pytest
import yaml
from test_autonomous_convergence import _seal_alignment, make_repo, run_cli

from harness import controlplane
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


def test_continue_directive_only_on_continue(tmp_path):
    harness_dir = make_repo(tmp_path, state="GATING")
    (harness_dir / "evidence" / "unit-test.json").unlink()

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 0
    assert "DECISION: CONTINUE" in result.stdout
    assert "DIRECTIVE: RESUME_TYPED_RECOVERY" in result.stdout


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
            "boundary_ref": "alignment.yaml", "expected_hash": "sha256:" + "0" * 64,
            "actual_hash": "sha256:" + "1" * 64,
        })
    )

    result = run_cli(tmp_path, "gate")

    assert result.returncode == 0, result.stderr
    assert "DECISION: ESCALATED" in result.stdout
    blockers = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["gate"]["blocked_by"]
    assert next(b for b in blockers if b["code"] == "CONTRACT_CHANGED")["finding_id"] == "FND-009"


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
