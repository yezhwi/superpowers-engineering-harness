"""TASK-002: control-plane subcommands status/transition/evidence/gate.

Each wraps the existing deterministic script logic; no re-implementation.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from evidence_factory import write_evidence

REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd, capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def make_repo(tmp_path: Path, **task_overrides) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True,
                   capture_output=True)
    run_cli(tmp_path, "init")
    # gate/evidence need a resolvable HEAD
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path,
                   check=True, capture_output=True)
    h = tmp_path / ".harness"
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task.update(task_overrides)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    return h


# -- status ---------------------------------------------------------------

def test_status_renders_state(tmp_path):
    h = make_repo(tmp_path, state="GATING")
    result = run_cli(tmp_path, "status")
    assert result.returncode == 0
    assert "State        GATING" in result.stdout


def test_status_invalid_state_exit_2(tmp_path):
    make_repo(tmp_path, state="WAT")
    assert run_cli(tmp_path, "status").returncode == 2


# -- transition ------------------------------------------------------------

def test_transition_legal_persists_new_state(tmp_path):
    make_repo(tmp_path, state="PLANNED")
    result = run_cli(tmp_path, "transition", "IMPLEMENTING")
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load((tmp_path / ".harness" /
                           "current-task.yaml").read_text())
    assert task["state"] == "IMPLEMENTING"


def test_transition_illegal_rejected_and_unchanged(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING")
    result = run_cli(tmp_path, "transition", "DONE")
    assert result.returncode == 1
    assert "INVALID TRANSITION" in result.stdout + result.stderr
    task = yaml.safe_load((tmp_path / ".harness" /
                           "current-task.yaml").read_text())
    assert task["state"] == "IMPLEMENTING"


def test_transition_missing_target_exit_2(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "transition").returncode == 2


def test_transition_unknown_state_exit_2(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "transition", "NOT_A_STATE").returncode == 2


# -- evidence ---------------------------------------------------------------

def test_evidence_writes_head_bound_json(tmp_path):
    make_repo(tmp_path)
    result = run_cli(tmp_path, "evidence", "--type", "build",
                     "--command", "true")
    assert result.returncode == 0, result.stdout + result.stderr
    ev = json.loads((tmp_path / ".harness" / "evidence" /
                     "build.json").read_text())
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()
    assert ev["exit_code"] == 0
    assert ev["commit"] == head
    assert ev["type"] == "build"


def test_evidence_failing_command_still_saved(tmp_path):
    make_repo(tmp_path)
    result = run_cli(tmp_path, "evidence", "--type", "unit_test",
                     "--command", "false")
    # evidence is recorded; the wrapper reports the underlying failure
    ev = json.loads((tmp_path / ".harness" / "evidence" /
                     "unit-test.json").read_text())
    assert ev["exit_code"] != 0


def test_evidence_invalid_type_exit_2(tmp_path):
    make_repo(tmp_path)
    result = run_cli(tmp_path, "evidence", "--type", "vibes",
                     "--command", "true")
    assert result.returncode == 2


# -- gate -----------------------------------------------------------------

def _passing_harness(tmp_path):
    h = make_repo(tmp_path, state="GATING")
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": ["unit-test.json"]}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    invs = {"invariants": [
        {"id": "INV-001", "statement": "safe", "category": "correctness",
         "severity": "critical", "status": "verified",
         "verification": ["build.json"]}]}
    (h / "invariants.yaml").write_text(yaml.safe_dump(invs))
    edir = h / "evidence"
    for etype in ("build", "unit_test"):
        write_evidence(tmp_path, h, etype)
    return h


def test_gate_pass_maps_to_zero_and_writes_back(tmp_path):
    _passing_harness(tmp_path)
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    task = yaml.safe_load((tmp_path / ".harness" /
                           "current-task.yaml").read_text())
    assert task["gate"]["status"] == "PASS"


def test_gate_blocked_maps_to_one(tmp_path):
    h = _passing_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "pending", "evidence": []}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 1
    assert "not verified" in result.stdout
