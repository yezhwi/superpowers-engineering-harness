"""Counterexamples for Guard/Gate separation and convergence write safety."""

import ast
import inspect

import yaml
from test_autonomous_convergence import make_repo, run_cli

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
