"""Milestone 2: Deterministic Quality Gate tests.

Covers:
1. missing evidence -> BLOCKED
2. stale evidence -> BLOCKED
3. major finding -> BLOCKED
4. unverified requirement -> BLOCKED
5. violated invariant -> BLOCKED
6. all conditions satisfied -> PASS (exit 0)
plus INVALID_HARNESS_STATE (exit 2) cases.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO
).stdout.strip()


def _gate(harness_dir: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "quality_gate.py"),
         "--harness-dir", str(harness_dir)],
        capture_output=True, text=True, cwd=REPO,
    )


def make_harness(tmp_path: Path) -> Path:
    """Build a fully passing harness dir; individual tests break one thing."""
    h = tmp_path / ".harness"

    task = yaml.safe_load(
        (REPO / "templates" / "current-task.yaml").read_text())
    task["state"] = "GATING"
    h.mkdir(parents=True)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    gate_cfg = yaml.safe_load((REPO / "templates" / "gate.yaml").read_text())
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))

    requirements = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": ["build.json"]},
    ]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))

    invariants = {"invariants": [
        {"id": "INV-001", "statement": "safe", "category": "correctness",
         "severity": "critical", "status": "verified",
         "verification": []},
    ]}
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))

    evidence_dir = h / "evidence"
    evidence_dir.mkdir()
    for etype in ("build", "unit_test"):
        (evidence_dir / f"{etype.replace('_', '-')}.json").write_text(
            json.dumps({
                "type": etype,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "command": "true",
                "exit_code": 0,
                "commit": HEAD,
            }))

    findings_dir = h / "findings"
    findings_dir.mkdir()

    return h


def test_all_conditions_pass(tmp_path):
    h = make_harness(tmp_path)
    result = _gate(h)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "QUALITY GATE: PASS" in result.stdout


def test_gate_writes_back_status(tmp_path):
    h = make_harness(tmp_path)
    assert _gate(h).returncode == 0
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["gate"]["status"] == "PASS"
    assert task["git"]["head"] == HEAD


# 1. missing evidence -------------------------------------------------------

@pytest.mark.parametrize("missing", ["build", "unit-test"])
def test_missing_evidence_blocked(tmp_path, missing):
    h = make_harness(tmp_path)
    (h / "evidence" / f"{missing}.json").unlink()
    result = _gate(h)
    assert result.returncode == 1
    assert "BLOCKED" in result.stdout
    assert "missing" in result.stdout


def test_failed_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    ev = json.loads((h / "evidence" / "build.json").read_text())
    ev["exit_code"] = 2
    (h / "evidence" / "build.json").write_text(json.dumps(ev))
    result = _gate(h)
    assert result.returncode == 1
    assert "failed" in result.stdout


def test_optional_verification_not_required(tmp_path):
    h = make_harness(tmp_path)
    # integration_test is optional in template; no evidence for it -> still PASS
    assert _gate(h).returncode == 0


# 2. stale evidence ---------------------------------------------------------

def test_stale_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    ev = json.loads((h / "evidence" / "unit-test.json").read_text())
    ev["commit"] = "0" * 40
    (h / "evidence" / "unit-test.json").write_text(json.dumps(ev))
    result = _gate(h)
    assert result.returncode == 1
    assert "stale" in result.stdout


def test_stale_evidence_via_real_collection(tmp_path):
    """End-to-end: fresh evidence collected, then HEAD moves -> stale."""
    h = make_harness(tmp_path)
    # overwrite build evidence with commit from an older fake sha
    (h / "evidence" / "build.json").write_text(json.dumps({
        "type": "build", "timestamp": "2026-01-01T00:00:00+00:00",
        "command": "true", "exit_code": 0, "commit": "deadbeef"}))
    result = _gate(h)
    assert result.returncode == 1
    assert "build evidence is stale" in result.stdout


# 3. major finding ----------------------------------------------------------

def finding_doc(fid, severity, status, **extra):
    finding = {
        "id": fid,
        "kind": "failure_scenario",
        "target": "REQ-001",
        "scenario": "concrete attack scenario",
        "severity": severity,
        "status": status,
    }
    finding.update(extra)
    return finding


def test_major_finding_blocked(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0001", "major", "PROPOSED")
    (h / "findings" / "FND-0001.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 1
    assert "Major finding FND-0001" in result.stdout


def test_critical_finding_blocked(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0002", "critical", "CONFIRMED")
    (h / "findings" / "FND-0002.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 1
    assert "Critical finding FND-0002" in result.stdout


def test_closed_findings_do_not_block(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0003", "major", "CLOSED")
    (h / "findings" / "FND-0003.yaml").write_text(yaml.safe_dump(finding))
    assert _gate(h).returncode == 0


def test_confirmed_finding_without_regression_test_blocked(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0004", "minor", "CONFIRMED")
    (h / "findings" / "FND-0004.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 1
    assert "no regression test" in result.stdout


def test_confirmed_finding_with_regression_test_ok(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc(
        "FND-0005", "minor", "CONFIRMED",
        regression_test={"path": "tests/test_fix.py"},
    )
    (h / "findings" / "FND-0005.yaml").write_text(yaml.safe_dump(finding))
    assert _gate(h).returncode == 0


# 4. unverified requirement -------------------------------------------------

def test_unverified_requirement_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = yaml.safe_load((h / "requirements.yaml").read_text())
    reqs["requirements"][0]["status"] = "implemented"
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = _gate(h)
    assert result.returncode == 1
    assert "REQ-001 not verified" in result.stdout


def test_should_requirement_unverified_does_not_block(tmp_path):
    h = make_harness(tmp_path)
    reqs = yaml.safe_load((h / "requirements.yaml").read_text())
    reqs["requirements"].append(
        {"id": "REQ-002", "statement": "nice", "priority": "should",
         "status": "pending", "evidence": []})
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    assert _gate(h).returncode == 0


# 5. violated invariant -----------------------------------------------------

def test_violated_invariant_blocked(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "violated"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 1
    assert "INV-001 violated" in result.stdout


def test_pending_critical_invariant_blocks(tmp_path):
    # pending = not proven = BLOCKED for critical/major (review fix #6)
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 1
    assert "not verified" in result.stdout


def test_pending_major_invariant_blocks(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["severity"] = "major"
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    assert _gate(h).returncode == 1


def test_pending_minor_invariant_passes_by_default(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["severity"] = "minor"
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    assert _gate(h).returncode == 0


def test_pending_minor_invariant_blocks_when_policy_requires(tmp_path):
    h = make_harness(tmp_path)
    gate_cfg = yaml.safe_load((h / "gate.yaml").read_text())
    gate_cfg["gate"]["invariants"]["minor_verified"] = True
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["severity"] = "minor"
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    assert _gate(h).returncode == 1


# INVALID_HARNESS_STATE (exit 2) ---------------------------------------------

def test_missing_current_task_invalid(tmp_path):
    h = tmp_path / ".harness"
    h.mkdir()
    result = _gate(h)
    assert result.returncode == 2


def test_wrong_state_invalid(tmp_path):
    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["state"] = "IMPLEMENTING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    result = _gate(h)
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr


def test_missing_requirements_file_invalid(tmp_path):
    h = make_harness(tmp_path)
    (h / "requirements.yaml").unlink()
    assert _gate(h).returncode == 2


def test_bad_evidence_json_invalid(tmp_path):
    h = make_harness(tmp_path)
    (h / "evidence" / "unit-test.json").write_text("{not json")
    assert _gate(h).returncode == 2


def test_malformed_finding_invalid(tmp_path):
    h = make_harness(tmp_path)
    (h / "findings" / "F-BAD.yaml").write_text("just_a_string\n")
    assert _gate(h).returncode == 2


def test_multiple_blockers_listed(tmp_path):
    h = make_harness(tmp_path)
    reqs = yaml.safe_load((h / "requirements.yaml").read_text())
    reqs["requirements"][0]["status"] = "pending"
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    (h / "evidence" / "build.json").unlink()
    finding = finding_doc("FND-0009", "major", "PROPOSED")
    (h / "findings" / "FND-0009.yaml").write_text(yaml.safe_dump(finding))

    out = _gate(h)
    assert out.returncode == 1
    stdout = out.stdout
    assert "REQ-001 not verified" in stdout
    assert "missing build evidence" in stdout
    assert "Major finding FND-0009" in stdout


# Requirement evidence validation (review fix #5) -----------------------------

def test_verified_requirement_without_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": []}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = _gate(h)
    assert result.returncode == 1
    assert "verified without evidence" in result.stdout


def test_verified_requirement_missing_evidence_file_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": ["nope.json"]}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    assert "evidence missing" in _gate(h).stdout


def test_verified_requirement_stale_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": ["build.json"]}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    ev = json.loads((h / "evidence" / "build.json").read_text())
    ev["commit"] = "0" * 40
    (h / "evidence" / "build.json").write_text(json.dumps(ev))
    assert "is stale" in _gate(h).stdout


def test_verified_requirement_failed_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": ["build.json"]}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    ev = json.loads((h / "evidence" / "build.json").read_text())
    ev["exit_code"] = 3
    (h / "evidence" / "build.json").write_text(json.dumps(ev))
    assert "failed" in _gate(h).stdout


def test_should_requirement_without_evidence_not_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "should",
         "status": "verified", "evidence": []}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    assert _gate(h).returncode == 0


def test_violated_invariant_blocks_even_if_allowance_configured(tmp_path):
    # No tolerance knob exists: violated_allowed was removed as a fake
    # config. Any violated invariant blocks, whatever the yaml says.
    h = make_harness(tmp_path)
    gate_cfg = yaml.safe_load((h / "gate.yaml").read_text())
    gate_cfg["gate"]["invariants"]["violated_allowed"] = 5
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "violated"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 1
    assert "violated" in result.stdout


# Schema validation: fail closed (CR-001 P0) ---------------------------------

def test_requirement_missing_priority_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    reqs = {"requirements": [
        {"id": "REQ-001", "statement": "must not duplicate side effects",
         "status": "pending", "evidence": []}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails requirement.schema.json" in result.stderr
    assert "priority" in result.stderr


def test_invariant_missing_severity_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    invs = {"invariants": [
        {"id": "INV-001", "statement": "at most one side effect",
         "category": "idempotency", "status": "pending",
         "verification": []}]}
    (h / "invariants.yaml").write_text(yaml.safe_dump(invs))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails invariant.schema.json" in result.stderr
    assert "severity" in result.stderr


def test_finding_missing_lifecycle_fields_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    # Gate must reject this malformed record before deciding its severity.
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump({
        "id": "FND-001", "severity": "major", "status": "PROPOSED"}))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails finding.schema.json" in result.stderr


def test_evidence_missing_commit_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    evidence = json.loads((h / "evidence" / "build.json").read_text())
    del evidence["commit"]
    (h / "evidence" / "build.json").write_text(json.dumps(evidence))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails evidence.schema.json" in result.stderr
