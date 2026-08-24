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

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
        (REPO / "templates" / "current-task.yaml").read_text())
    task["state"] = "GATING"
    h.mkdir(parents=True)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "gate.yaml").write_text(
        (REPO / "templates" / "gate.yaml").read_text())
    requirements = {"requirements": [
        {"id": "REQ-001", "statement": "works", "priority": "must",
         "status": "verified", "evidence": []},
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
            __import__("json").dumps({
                "type": etype,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "command": "true",
                "exit_code": 0,
                "commit": HEAD,
            }))

    (h / "findings").mkdir()
    return h


def write_finding(h: Path, **overrides):
    finding = {
        "id": "FND-001",
        "severity": "major",
        "status": "PROPOSED",
        "regression_test": {},
    }
    finding.update(overrides)
    (h / "findings" / f"{finding['id'].lower()}.yaml").write_text(
        yaml.safe_dump(finding))


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


def test_confirmed_without_regression_test_blocks(tmp_path):
    # Reproducer failed -> CONFIRMED. LAW 4: must carry regression test.
    h = make_harness(tmp_path)
    write_finding(h, status="CONFIRMED", regression_test={})
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any(
        "Confirmed finding FND-001 has no regression test" in b
        for b in blockers)


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
