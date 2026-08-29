"""Milestone 3: Finding lifecycle tests.

Deterministic core of the finding lifecycle:
1. PROPOSED does not count as a confirmed bug (gate ignores it as debt,
   but it still blocks while open per severity policy).
2. State machine supports the full lifecycle path:
   REVIEWING -> REPRODUCING -> FIXING -> VERIFYING.
3. Reproducer fails -> CONFIRMED; CONFIRMED without regression test
   -> Gate BLOCKED (LAW 4).
4. Cannot reproduce -> REJECTED; REJECTED/CLOSED findings never block.
"""

import json
from importlib import resources
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from evidence_factory import write_complexity_review, write_evidence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from collect_evidence import workspace_fingerprint  # noqa: E402
from quality_gate import run_gate  # noqa: E402
from state_machine import is_legal  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO
).stdout.strip()


def make_harness(tmp_path: Path) -> Path:
    """Fully passing harness dir at GATING with empty findings."""
    h = tmp_path / ".harness"
    task = yaml.safe_load(
        resources.files("harness").joinpath("templates", "current-task.yaml").read_text())
    task["state"] = "GATING"
    h.mkdir(parents=True)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "gate.yaml").write_text(
        resources.files("harness").joinpath("templates", "gate.yaml").read_text())
    requirements = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must", "status": "verified", "evidence": ["build.json"], "test_plan": {"strategies": ["manual"], "cases": [{"id": "TC-700", "type": "happy_path", "strategy": "manual", "description": "fixture requirement", "tests": []}]}}] }
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    invariants = {"invariants": [
        {"id": "INV-001", "statement": "safe", "category": "correctness", "severity": "critical", "status": "verified", "verification": ["build.json"], "test_plan": {"strategies": ["manual"], "cases": [{"id": "TC-701", "type": "invariant", "strategy": "manual", "description": "fixture invariant", "tests": []}]}}] }
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))

    evidence_dir = h / "evidence"
    evidence_dir.mkdir()
    for etype in ("build", "unit_test"):
        write_evidence(REPO, h, etype)
    write_complexity_review(REPO, h)
    build = json.loads((evidence_dir / "build.json").read_text())
    build["covered_test_cases"] = ["TC-700", "TC-701"]
    (evidence_dir / "build.json").write_text(json.dumps(build))

    (h / "findings").mkdir()
    return h


def write_finding(h: Path, **overrides):
    finding = {
        "id": "FND-001",
        "kind": "failure_scenario",
        "target": "REQ-001",
        "scenario": "concrete lifecycle test attack",
        "severity": "major",
        "status": "PROPOSED",
    }
    finding.update(overrides)
    status = finding["status"]
    if status == "REJECTED":
        finding.setdefault("attempts", ["reproduction attempt"])
        finding.setdefault("rejection_reason", "scenario proven impossible")
    if status in {"CONFIRMED", "FIXING", "FIXED", "VERIFIED", "CLOSED"}:
        finding.setdefault("test", "tests/test_regress.py::test_bug")
        finding.setdefault("confirmed_at", "2026-01-01T00:00:00+00:00")
        rt = finding.setdefault("regression_test", {})
        rt.setdefault("path", finding["test"]); rt.setdefault("red_evidence", f"{finding['id']}-red.json")
        finding["test"] = rt["path"]
        fingerprint = workspace_fingerprint()
        (h / "evidence" / rt["red_evidence"]).write_text(json.dumps({"type":"custom","timestamp":"t","command":"false","exit_code":1,"commit":HEAD,"workspace_fingerprint":fingerprint,"workspace_fingerprint_after":fingerprint,"subject":{"kind":"finding","id":finding["id"]},"test":{"node_id":finding["test"]}}))
    if status in {"FIXED", "VERIFIED", "CLOSED"}:
        finding["regression_test"].setdefault("green_evidence", f"{finding['id']}-green.json")
        fingerprint = workspace_fingerprint()
        (h / "evidence" / finding["regression_test"]["green_evidence"]).write_text(json.dumps({"type":"custom","timestamp":"t","command":"true","exit_code":0,"commit":HEAD,"workspace_fingerprint":fingerprint,"workspace_fingerprint_after":fingerprint,"subject":{"kind":"finding","id":finding["id"]},"test":{"node_id":finding["test"]}}))
    if status in {"VERIFIED", "CLOSED"}:
        finding.setdefault("evidence", f"{finding['id']}-full.json"); finding.setdefault("verified_at", "2026-01-02T00:00:00+00:00")
        fingerprint = workspace_fingerprint()
        (h / "evidence" / finding["evidence"]).write_text(json.dumps({"type":"custom","timestamp":"t","command":"true","exit_code":0,"commit":HEAD,"workspace_fingerprint":fingerprint,"workspace_fingerprint_after":fingerprint,"scope":"full_suite","covered_tests":[]}))
    (h / "findings" / f"{finding['id'].lower()}.yaml").write_text(yaml.safe_dump(finding))


# 1. Lifecycle transitions ---------------------------------------------------

def test_reviewing_to_reproducing_legal():
    assert is_legal("REVIEWING", "REPRODUCING")


def test_reproducing_to_fixing_legal():
    assert is_legal("REPRODUCING", "FIXING")


def test_fixing_back_to_verifying_legal():
    assert is_legal("FIXING", "VERIFYING")


def test_finding_direct_to_done_illegal():
    # No matter the finding status, no working state reaches DONE directly.
    for state in ("IMPLEMENTING", "VERIFYING", "REVIEWING", "FIXING"):
        assert not is_legal(state, "DONE")


# 2. PROPOSED vs CONFIRMED semantics -----------------------------------------

def test_proposed_major_finding_blocks(tmp_path):
    # PROPOSED is an unconfirmed attack attempt but still open -> blocked.
    h = make_harness(tmp_path)
    write_finding(h, status="PROPOSED")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any("Major finding FND-001 is open" in b for b in blockers)


def test_confirmed_finding_blocks_until_fixed(tmp_path):
    h = make_harness(tmp_path)
    write_finding(h, status="CONFIRMED")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any("Major finding FND-001 is open" in b for b in blockers)


def test_confirmed_with_regression_test_still_open_until_fixed(tmp_path):
    # Regression debt cleared, but CONFIRMED is still open -> blocked
    # until the fix lands and status moves to VERIFIED/CLOSED.
    h = make_harness(tmp_path)
    write_finding(
        h, status="CONFIRMED",
        regression_test={"path": "tests/test_regress_fnd_001.py"})
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any("Major finding FND-001 is open" in b for b in blockers)


def test_verified_finding_accepts_historical_red_evidence(tmp_path):
    h = make_harness(tmp_path)
    write_finding(h, status="VERIFIED")
    red = json.loads((h / "evidence" / "FND-001-red.json").read_text())
    red["workspace_fingerprint"] = "sha256:" + "0" * 64
    red["workspace_fingerprint_after"] = "sha256:" + "0" * 64
    (h / "evidence" / "FND-001-red.json").write_text(json.dumps(red))

    status, blockers = run_gate(h)
    assert status == "PASS", blockers


def test_verified_finding_with_stale_full_evidence_is_invalid(tmp_path):
    h = make_harness(tmp_path)
    write_finding(h, status="VERIFIED")
    full_path = h / "evidence" / "FND-001-full.json"
    full = json.loads(full_path.read_text())
    full["workspace_fingerprint"] = "sha256:" + "0" * 64
    full["workspace_fingerprint_after"] = "sha256:" + "0" * 64
    full_path.write_text(json.dumps(full))

    with pytest.raises(Exception, match="EVIDENCE_WORKSPACE_STALE"):
        run_gate(h)


def test_verified_after_fix_passes(tmp_path):
    # Fix landed, full suite green, finding closed as VERIFIED.
    h = make_harness(tmp_path)
    write_finding(
        h, status="VERIFIED",
        regression_test={"path": "tests/test_regress_fnd_001.py"})
    status, blockers = run_gate(h)
    assert status == "PASS", blockers


@pytest.mark.parametrize("severity,label", [
    ("critical", "Critical finding"),
    ("major", "Major finding"),
])
def test_open_severity_blocks(tmp_path, severity, label):
    h = make_harness(tmp_path)
    write_finding(h, severity=severity, status="REPRODUCING")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any(f"{label} FND-001 is open" in b for b in blockers)


# 3. Rejected / closed findings never block -----------------------------------

def test_fixed_still_blocks_until_verified(tmp_path):
    # FIXED = reproduction test green but full regression not yet run.
    h = make_harness(tmp_path)
    write_finding(h, status="FIXED",
                  regression_test={"path": "tests/test_regress.py"})
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any("FND-001 is open" in b for b in blockers)


@pytest.mark.parametrize("status", ["REJECTED", "CLOSED"])
def test_terminal_finding_does_not_block(tmp_path, status):
    h = make_harness(tmp_path)
    write_finding(h, status=status)
    result_status, blockers = run_gate(h)
    assert result_status == "PASS", blockers


def test_mixed_findings_only_open_ones_block(tmp_path):
    h = make_harness(tmp_path)
    write_finding(h, id="FND-001", status="REJECTED")
    write_finding(h, id="FND-002", status="VERIFIED",
                  regression_test={"path": "tests/test_x.py"})
    write_finding(h, id="FND-003", status="FIXING")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any("FND-003" in b for b in blockers)
    assert not any("FND-001" in b or "FND-002" in b for b in blockers)
