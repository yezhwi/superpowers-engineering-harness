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
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from evidence_factory import synthetic_execution
from fixtures.harness import populate_complete_harness
from test_alignment import complete_alignment

from harness.init import init_harness
from harness.test_scope import add_required_test, bind_scope_identity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from collect_evidence import workspace_fingerprint
from quality_gate import run_gate
from state_machine import is_legal

REPO = Path(__file__).resolve().parent.parent

@pytest.fixture(autouse=True)
def fixture_workspace(tmp_path, monkeypatch):
    """Gate and scope must consume facts from the same actual fixture repo."""
    monkeypatch.chdir(tmp_path)


def make_harness(tmp_path: Path) -> Path:
    """Native trusted genesis, then complete Q2/STANDARD lifecycle preconditions."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com",
         "commit", "--allow-empty", "-qm", "fixture genesis"], check=True, capture_output=True,
    )
    h = init_harness(tmp_path).harness_dir
    bind_scope_identity(h, "TASK-001")
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["state"] = "GATING"
    task["task"]["type"] = "feature"
    task["risk"] = {
        "level": "Q2", "profile": "STANDARD",
        "dimensions": {"scope": "low", "contract": "low", "data": "none",
                       "authorization": "none", "security": "none", "concurrency": "none", "deployment": "none"},
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "observability.yaml").write_text(yaml.safe_dump({
        "version": 1,
        "required": False,
        "applicability": {"reasons": ["not_assessed"], "inspected_paths": ["src/example.py"]},
    }))
    for filename in ("test_regress.py", "test_regress_fnd_001.py", "test_x.py"):
        path = tmp_path / "tests" / filename
        path.parent.mkdir(exist_ok=True)
        path.write_text("def test_bug():\n    pass\n")
    populate_complete_harness(tmp_path, h)
    document = complete_alignment()
    document["decision_ids"] = []
    document["interface_contract_ids"] = []
    (h / "alignment.yaml").write_text(yaml.safe_dump(document))
    frozen = subprocess.run(
        [sys.executable, "-m", "harness.cli", "align", "freeze"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"}, timeout=40,
    )
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    return h


def write_finding(h: Path, **overrides):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=h.parent, capture_output=True, text=True, check=True,
    ).stdout.strip()
    finding = {
        "id": "FND-001",
        "category": "adversarial",
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
        rt.setdefault("path", finding["test"])
        rt.setdefault("red_evidence", f"{finding['id']}-red.json")
        finding["test"] = rt["path"]
        fingerprint = workspace_fingerprint()
        (h / "evidence" / rt["red_evidence"]).write_text(
            json.dumps(
                {
                    "type": "custom",
                    "timestamp": "t",
                    "command": "false",
                    "exit_code": 1,
                    "test_execution": synthetic_execution([finding["test"]], exit_code=1),
                    "commit": head,
                    "workspace_fingerprint": fingerprint,
                    "workspace_fingerprint_after": fingerprint,
                    "subject": {"kind": "finding", "id": finding["id"]},
                    "test": {"node_id": finding["test"]},
                }
            )
        )
    if status in {"FIXED", "VERIFIED", "CLOSED"}:
        finding["regression_test"].setdefault(
            "green_evidence", f"{finding['id']}-green.json"
        )
        fingerprint = workspace_fingerprint()
        (h / "evidence" / finding["regression_test"]["green_evidence"]).write_text(
            json.dumps(
                {
                    "type": "custom",
                    "timestamp": "t",
                    "command": "true",
                    "exit_code": 0,
                    "commit": head,
                    "workspace_fingerprint": fingerprint,
                    "workspace_fingerprint_after": fingerprint,
                    "subject": {"kind": "finding", "id": finding["id"]},
                    "test": {"node_id": finding["test"]},
                    "test_execution": synthetic_execution([finding["test"]]),
                }
            )
        )
    if status in {"VERIFIED", "CLOSED"}:
        finding.setdefault("evidence", f"{finding['id']}-full.json")
        finding.setdefault("verified_at", "2026-01-02T00:00:00+00:00")
        fingerprint = workspace_fingerprint()
        (h / "evidence" / finding["evidence"]).write_text(
            json.dumps(
                {
                    "type": "custom",
                    "timestamp": "t",
                    "command": "true",
                    "exit_code": 0,
                    "commit": head,
                    "workspace_fingerprint": fingerprint,
                    "workspace_fingerprint_after": fingerprint,
                    "scope": "related",
                    "covered_tests": [finding["test"]],
                    "test_execution": synthetic_execution([finding["test"]]),
                }
            )
        )
    if status in {"VERIFIED", "CLOSED"}:
        selector = finding["regression_test"]["path"]
        assert (h.parent / selector.split("::", 1)[0]).is_file()
        add_required_test(h, selector)
    (h / "findings" / f"{finding['id']}.yaml").write_text(
        yaml.safe_dump(finding)
    )


@pytest.mark.parametrize("damage", ["alignment", "scope_origin", "unaudited_shrink"])
def test_lifecycle_fixture_prerequisites_remain_fail_closed(tmp_path, damage):
    h = make_harness(tmp_path)
    write_finding(h, status="REJECTED")
    add_required_test(h, "tests/test_regress.py::test_bug")
    assert run_gate(h) == ("PASS", [])
    if damage == "alignment":
        (h / "alignment.yaml").unlink()
        from harness.quality_gate import InvalidHarnessState
        with pytest.raises(InvalidHarnessState, match="ALIGNMENT_MISSING"):
            run_gate(h)
    else:
        if damage == "scope_origin":
            (h / "test-scope-baseline.yaml").unlink()
            expected = "TEST_SCOPE_AUDIT_INVALID"
        else:
            impact = yaml.safe_load((h / "impact.yaml").read_text())
            impact["impact"]["required_tests"] = []
            (h / "impact.yaml").write_text(yaml.safe_dump(impact))
            expected = "TEST_SCOPE_RETIREMENT_UNAUDITED"
        status, blockers = run_gate(h)
        assert status == "BLOCKED"
        assert expected in {blocker.code for blocker in blockers}


def test_lifecycle_fixture_add_preserves_native_origin_and_alignment_seal(tmp_path):
    h = make_harness(tmp_path)
    preserved = {name: (h / name).read_bytes()
                 for name in ("test-scope-baseline.yaml", "alignment.yaml", "alignment-freeze.yaml")}
    baseline = yaml.safe_load(preserved["test-scope-baseline.yaml"])
    assert baseline["origin"]["kind"] == "new_task" and baseline["required_tests"] == []
    assert baseline["task_id"] == "TASK-001"
    assert yaml.safe_load(preserved["alignment-freeze.yaml"])["version"] == 3
    write_finding(h, status="VERIFIED")
    assert all((h / name).read_bytes() == data for name, data in preserved.items())
    audit = yaml.safe_load((h / "test-scope-audit.yaml").read_text())
    assert len(audit["entries"]) == 1
    assert audit["entries"][0]["operation"] == "ADD"
    assert audit["entries"][0]["before_tests"] == []
    assert audit["entries"][0]["after_tests"] == ["tests/test_regress.py::test_bug"]
    assert run_gate(h) == ("PASS", [])


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


def test_confirmed_diagnosability_finding_blocks_without_regression_test(tmp_path):
    h = make_harness(tmp_path)
    finding = {
        "id": "FND-001",
        "kind": "requirement_violation",
        "target": "REQ-001",
        "scenario": "missing diagnostic context",
        "severity": "major",
        "status": "CONFIRMED",
        "category": "diagnosability",
        "reason_code": "DIAG_MISSING_BUSINESS_ID",
        "location": {"file": "src/order.py"},
        "compliance": {
            "evidence_kind": "static_compliance",
            "required_checks": ["business_keys"],
        },
        "confirmed_at": "2026-01-01T00:00:00+00:00",
    }
    (h / "findings" / "FND-001.yaml").write_text(yaml.safe_dump(finding))

    status, blockers = run_gate(h)

    assert status == "BLOCKED"
    assert any(
        "Major finding FND-001 is open" in blocker.message for blocker in blockers
    )


def test_confirmed_with_regression_test_still_open_until_fixed(tmp_path):
    # Regression debt cleared, but CONFIRMED is still open -> blocked
    # until the fix lands and status moves to VERIFIED/CLOSED.
    h = make_harness(tmp_path)
    write_finding(
        h, status="CONFIRMED", regression_test={"path": "tests/test_regress_fnd_001.py"}
    )
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


def test_verified_finding_with_stale_related_evidence_is_invalid(tmp_path):
    h = make_harness(tmp_path)
    write_finding(h, status="VERIFIED")
    evidence_path = h / "evidence" / "FND-001-full.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["workspace_fingerprint"] = "sha256:" + "0" * 64
    evidence["workspace_fingerprint_after"] = "sha256:" + "0" * 64
    evidence_path.write_text(json.dumps(evidence))

    with pytest.raises(Exception, match="EVIDENCE_WORKSPACE_STALE"):
        run_gate(h)


def test_verified_after_fix_passes(tmp_path):
    # Fix landed, related regression proof green, finding closed as VERIFIED.
    h = make_harness(tmp_path)
    write_finding(
        h, status="VERIFIED", regression_test={"path": "tests/test_regress_fnd_001.py"}
    )
    status, blockers = run_gate(h)
    assert status == "PASS", blockers


@pytest.mark.parametrize(
    "severity,label",
    [
        ("critical", "Critical finding"),
        ("major", "Major finding"),
    ],
)
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
    write_finding(h, status="FIXED", regression_test={"path": "tests/test_regress.py"})
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
    write_finding(
        h, id="FND-002", status="VERIFIED", regression_test={"path": "tests/test_x.py"}
    )
    write_finding(h, id="FND-003", status="FIXING")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any("FND-003" in b for b in blockers)
    assert not any("FND-001" in b or "FND-002" in b for b in blockers)
