"""TASK-003: finding list/show + converge subcommands (guide section 34)."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

from evidence_factory import write_evidence

REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd, capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def make_repo(tmp_path: Path, state="GATING", iteration=0,
              max_iterations=5) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True,
                   capture_output=True)
    run_cli(tmp_path, "init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path,
                   check=True, capture_output=True)
    h = tmp_path / ".harness"
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task.update({"state": state, "iteration": iteration,
                 "max_iterations": max_iterations})
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": ["build.json"]}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    invs = {"invariants": [
        {"id": "INV-001", "statement": "safe", "category": "correctness",
         "severity": "critical", "status": "verified",
         "verification": ["build.json"]}]}
    (h / "invariants.yaml").write_text(yaml.safe_dump(invs))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()
    edir = h / "evidence"
    for etype in ("build", "unit_test"):
        write_evidence(tmp_path, h, etype)
    return h


def add_finding(h: Path, fid: str, status="PROPOSED", severity="major"):
    (h / "findings" / f"{fid.lower()}.yaml").write_text(yaml.safe_dump({
        "id": fid, "kind": "failure_scenario", "target": "REQ-001",
        "scenario": "attack", "severity": severity, "status": status}))


# -- finding list -------------------------------------------------------------

def test_finding_list_prints_records(tmp_path):
    h = make_repo(tmp_path)
    add_finding(h, "FND-0001")
    add_finding(h, "FND-0002", status="REJECTED", severity="minor")
    result = run_cli(tmp_path, "finding", "list")
    assert result.returncode == 0
    assert "FND-0001" in result.stdout and "PROPOSED" in result.stdout
    assert "FND-0002" in result.stdout and "REJECTED" in result.stdout


def test_finding_list_empty_ok(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "finding", "list").returncode == 0


# -- finding show -------------------------------------------------------------

def test_finding_show_full_record(tmp_path):
    h = make_repo(tmp_path)
    add_finding(h, "FND-0007")
    result = run_cli(tmp_path, "finding", "show", "FND-0007")
    assert result.returncode == 0
    assert "attack" in result.stdout  # scenario field present


def test_finding_show_unknown_id_exit_1(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "finding", "show", "FND-9999").returncode == 1


def test_finding_show_missing_id_exit_2(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "finding", "show").returncode == 2


# -- converge ------------------------------------------------------------------

def test_converge_pass_transitions_to_converged(tmp_path):
    make_repo(tmp_path, state="GATING")
    result = run_cli(tmp_path, "converge")
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load((tmp_path / ".harness" /
                           "current-task.yaml").read_text())
    assert task["state"] == "CONVERGED"
    assert "CONVERGED" in result.stdout or "PASS" in result.stdout


def test_converge_budget_exhausted_escalates(tmp_path):
    make_repo(tmp_path, state="GATING", iteration=5, max_iterations=5)
    # gate will be BLOCKED (no evidence yet written by this helper variant)
    h = tmp_path / ".harness"
    for f in ("build.json", "unit-test.json"):
        (h / "evidence" / f).unlink()
    result = run_cli(tmp_path, "converge")
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["state"] == "ESCALATED"
    assert "MAX_ITERATIONS" in result.stdout


def test_converge_blocked_under_budget_continues(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=2, max_iterations=5)
    for f in ("build.json", "unit-test.json"):
        (h / "evidence" / f).unlink()
    result = run_cli(tmp_path, "converge")
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["state"] == "BLOCKED"
    assert task["iteration"] == 3
    assert "CONTINUE" in result.stdout


def test_converge_from_wrong_state_exit_1(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING")
    assert run_cli(tmp_path, "converge").returncode == 1


# -- deterministic REPEATED_REGRESSION ----------------------------------------

def test_converge_reopened_verified_finding_escalates(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=1, max_iterations=5)
    add_finding(h, "FND-0009")
    import yaml as _y
    p = h / "findings" / "fnd-0009.yaml"
    rec = _y.safe_load(p.read_text())
    rec["status"] = "REPRODUCING"      # open again...
    rec["verified_at"] = "2026-01-01T00:00:00+00:00"   # ...after being VERIFIED
    p.write_text(_y.safe_dump(rec))
    result = run_cli(tmp_path, "converge")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REPEATED_REGRESSION" in result.stdout
    task = _y.safe_load((h / "current-task.yaml").read_text())
    assert task["state"] == "ESCALATED"


def test_converge_rejected_finding_does_not_escalate(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=1, max_iterations=5)
    add_finding(h, "FND-0010")
    import yaml as _y
    p = h / "findings" / "fnd-0010.yaml"
    rec = _y.safe_load(p.read_text())
    rec["status"] = "REJECTED"
    rec["attempts"] = ["reproduction attempt"]
    rec["rejection_reason"] = "scenario proven impossible"
    p.write_text(_y.safe_dump(rec))
    result = run_cli(tmp_path, "converge")
    assert "CONVERGED" in result.stdout
