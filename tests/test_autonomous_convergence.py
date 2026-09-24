"""Tests for Autonomous Convergence Policy (spec 2026-09-23).

Covers all 8 design requirements:
1. legacy task without convergence metadata returns CONTINUE and initializes fingerprint/count;
2. first blocker fingerprint returns CONTINUE and records count 1;
3. second consecutive identical blocker assessment returns ESCALATED: NO_PROGRESS;
4. changed blocker replaces fingerprint, resets count, and may continue;
5. PASS deletes fingerprint/count;
6. persisted metadata survives reload and schema rejects malformed present metadata;
7. CONTRACT_CHANGED, every SCOPE_DRIFT_* code, and DECISION_UNRESOLVED immediately escalate
   as USER_AUTHORITY_REQUIRED without entering the repair loop, including when an evidence
   blocker is also present;
8. existing five-iteration and reopened-regression escalation remain unchanged, and a
   simultaneous user-authority blocker outranks both.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from evidence_factory import write_complexity_review, write_evidence
from fixtures.harness import populate_complete_harness

from harness.blockers import (
    GateBlocker,
    compute_blocker_fingerprint,
    is_user_authority_blocker,
    select_recovery,
)

REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def make_repo(tmp_path: Path, state="GATING", iteration=0, max_iterations=5) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    run_cli(tmp_path, "init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=tmp_path, check=True, capture_output=True
    )
    h = tmp_path / ".harness"
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task.setdefault("task", {})["id"] = "TASK-001"
    task.update(
        {"state": state, "iteration": iteration, "max_iterations": max_iterations}
    )
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": ["build.json"],
                "test_plan": {
                    "strategies": ["manual"],
                    "cases": [
                        {
                            "id": "TC-900",
                            "type": "happy_path",
                            "strategy": "manual",
                            "description": "fixture baseline",
                            "tests": [],
                        }
                    ],
                },
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    invs = {
        "invariants": [
            {
                "id": "INV-001",
                "statement": "safe",
                "category": "correctness",
                "severity": "critical",
                "status": "verified",
                "verification": ["build.json"],
                "test_plan": {
                    "strategies": ["manual"],
                    "cases": [
                        {
                            "id": "TC-901",
                            "type": "invariant",
                            "strategy": "manual",
                            "description": "fixture invariant",
                            "tests": [],
                        }
                    ],
                },
            }
        ]
    }
    (h / "invariants.yaml").write_text(yaml.safe_dump(invs))
    edir = h / "evidence"
    for etype in ("build", "unit_test"):
        write_evidence(tmp_path, h, etype)
    write_complexity_review(tmp_path, h)
    build = json.loads((edir / "build.json").read_text())
    build["covered_test_cases"] = ["TC-900", "TC-901"]
    (edir / "build.json").write_text(json.dumps(build))
    return populate_complete_harness(tmp_path, h)


def add_finding(h: Path, fid: str, status="PROPOSED", severity="major"):
    (h / "findings" / f"{fid.lower()}.yaml").write_text(
        yaml.safe_dump(
            {
                "id": fid,
                "category": "adversarial",
                "kind": "failure_scenario",
                "target": "REQ-001",
                "scenario": "attack",
                "severity": severity,
                "status": status,
            }
        )
    )


# -----------------------------------------------------------------------------
# Fingerprint unit tests
# -----------------------------------------------------------------------------


def test_fingerprint_normalization_and_sorting():
    b1 = GateBlocker("EVIDENCE_MISSING", "verification", "message 1", source="build")
    b2 = GateBlocker("FINDING_OPEN", "defect", "message 2", finding_id="FND-001")

    fp_forward = compute_blocker_fingerprint([b1, b2])
    fp_reverse = compute_blocker_fingerprint([b2, b1])
    assert fp_forward == fp_reverse
    assert is_user_authority_blocker("CONTRACT_CHANGED")
    assert not is_user_authority_blocker("EVIDENCE_MISSING")

    # Cosmetic message difference does NOT alter fingerprint
    b1_cosmetic = GateBlocker("EVIDENCE_MISSING", "verification", "totally different text", source="build")
    assert compute_blocker_fingerprint([b1_cosmetic, b2]) == fp_forward

    # Missing vs None vs empty string normalization
    d1 = {"code": "EVIDENCE_MISSING", "category": "verification", "source": "build"}
    d2 = {"code": "EVIDENCE_MISSING", "category": "verification", "source": "build", "requirement_id": None}
    assert compute_blocker_fingerprint([d1]) == compute_blocker_fingerprint([d2])
    assert compute_blocker_fingerprint([d1]) == compute_blocker_fingerprint([b1])

    # Material difference alters fingerprint
    b3 = GateBlocker("INVARIANT_VIOLATED", "implementation", "violated", invariant_id="INV-001")
    assert compute_blocker_fingerprint([b3]) != fp_forward


# -----------------------------------------------------------------------------
# Requirement 1 & 2: Legacy task initializes metadata with count 1 and CONTINUE
# -----------------------------------------------------------------------------


def test_legacy_task_initializes_fingerprint_and_count_on_blocked(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=0, max_iterations=5)
    # Remove an evidence file so gate is BLOCKED
    (h / "evidence" / "unit-test.json").unlink()

    # Legacy task without convergence metadata
    task_before = yaml.safe_load((h / "current-task.yaml").read_text())
    assert "convergence" not in task_before

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONTINUE" in result.stdout

    task_after = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task_after["state"] == "BLOCKED"
    assert task_after["iteration"] == 1
    assert "convergence" in task_after
    assert task_after["convergence"]["count"] == 1
    assert task_after["convergence"]["fingerprint"].startswith("sha256:")


# -----------------------------------------------------------------------------
# Requirement 3: Second consecutive identical assessment produces ESCALATED: NO_PROGRESS
# -----------------------------------------------------------------------------


def test_second_consecutive_identical_blocker_escalates_no_progress(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=0, max_iterations=5)
    (h / "evidence" / "unit-test.json").unlink()

    # First blocked assessment
    first = run_cli(tmp_path, "gate")
    assert first.returncode == 0
    assert "CONTINUE" in first.stdout
    task1 = yaml.safe_load((h / "current-task.yaml").read_text())
    fp1 = task1["convergence"]["fingerprint"]
    assert task1["convergence"]["count"] == 1

    # Simulate resume to GATING without fixing the blocker
    task1["state"] = "GATING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task1))

    # Second blocked assessment with identical blocker
    second = run_cli(tmp_path, "gate")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "DECISION: ESCALATED" in second.stdout
    assert "REASON: NO_PROGRESS" in second.stdout
    # Spec: NO_PROGRESS includes current blockers and prior fingerprint in output for diagnosis
    assert fp1 in second.stdout

    task2 = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task2["state"] == "ESCALATED"
    assert task2["convergence"]["count"] == 2
    assert task2["convergence"]["fingerprint"] == fp1


# -----------------------------------------------------------------------------
# Repeated gate from BLOCKED is invalid and does not increment count
# -----------------------------------------------------------------------------


def test_repeated_gate_from_blocked_fails_and_never_increments_count(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=0, max_iterations=5)
    (h / "evidence" / "unit-test.json").unlink()

    run_cli(tmp_path, "gate")
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["state"] == "BLOCKED"
    assert task["convergence"]["count"] == 1

    # Calling gate again while state is BLOCKED must fail (exit 1) and never increment count
    second = run_cli(tmp_path, "gate")
    assert second.returncode == 1
    assert "converge requires state GATING" in second.stderr

    task_after = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task_after["convergence"]["count"] == 1


# -----------------------------------------------------------------------------
# Requirement 4: Changed blocker replaces fingerprint, resets count, and continues
# -----------------------------------------------------------------------------


def test_changed_blocker_replaces_fingerprint_resets_count_and_continues(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=0, max_iterations=5)
    (h / "evidence" / "unit-test.json").unlink()

    run_cli(tmp_path, "gate")
    task1 = yaml.safe_load((h / "current-task.yaml").read_text())
    fp1 = task1["convergence"]["fingerprint"]
    assert task1["convergence"]["count"] == 1

    # Restore unit-test evidence, but violate an invariant instead (materially different blocker)
    write_evidence(tmp_path, h, "unit_test")
    inv_path = h / "invariants.yaml"
    invs = yaml.safe_load(inv_path.read_text())
    invs["invariants"][0]["status"] = "violated"
    inv_path.write_text(yaml.safe_dump(invs))

    # Reset state to GATING
    task1["state"] = "GATING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task1))

    second = run_cli(tmp_path, "gate")
    assert second.returncode == 0
    assert "CONTINUE" in second.stdout

    task2 = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task2["state"] == "BLOCKED"
    assert task2["convergence"]["fingerprint"] != fp1
    assert task2["convergence"]["count"] == 1


# -----------------------------------------------------------------------------
# Requirement 5: PASS deletes fingerprint and count
# -----------------------------------------------------------------------------


def test_pass_deletes_fingerprint_and_count(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=1, max_iterations=5)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["convergence"] = {"fingerprint": "sha256:" + "a" * 64, "count": 1}
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "CONVERGED" in result.stdout

    task_after = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task_after["state"] == "CONVERGED"
    assert "convergence" not in task_after


# -----------------------------------------------------------------------------
# Requirement 6: Schema rejects malformed convergence metadata
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed_convergence",
    [
        {"fingerprint": "sha256:abc", "count": 0},  # count < 1
        {"fingerprint": "", "count": 1},  # empty fingerprint
        {"fingerprint": 12345, "count": 1},  # fingerprint not string
        {"count": 1},  # missing fingerprint
        {"fingerprint": "sha256:abc"},  # missing count
        {"fingerprint": "sha256:abc", "count": 1, "extra": "invalid"},  # extra property
        "not-a-dict",
    ],
)
def test_schema_rejects_malformed_convergence_metadata(tmp_path, malformed_convergence):
    h = make_repo(tmp_path, state="GATING")
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["convergence"] = malformed_convergence
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr


# -----------------------------------------------------------------------------
# Requirement 7: User-authority blockers immediately escalate without repair loop
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "CONTRACT_CHANGED",
        "SCOPE_DRIFT_API",
        "SCOPE_DRIFT_PERMISSION",
        "SCOPE_DRIFT_PERSISTENCE",
        "DECISION_UNRESOLVED",
    ],
)
def test_user_authority_codes_immediately_escalate_without_repair(tmp_path, code):
    h = make_repo(tmp_path, state="GATING")
    # Also unlink an evidence file to create a simultaneous evidence blocker
    (h / "evidence" / "unit-test.json").unlink()

    if code == "DECISION_UNRESOLVED":
        from harness import decision

        decision.propose(
            h,
            {
                "topic": "test-topic",
                "question": "test-question",
                "context": ["test-context"],
                "options": [{"id": "opt1", "description": "desc1"}],
                "recommendation": {"option": "opt1", "reasons": ["r"], "tradeoffs": ["t"]},
                "scope": ["internal"],
                "constraints": [],
            },
        )
    else:
        # Inject user authority blocker into gate
        # For alignment codes:
        finding_dir = h / "findings"
        finding_dir.mkdir(parents=True, exist_ok=True)
        (finding_dir / "fnd-0100.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "FND-0100",
                    "category": "alignment",
                    "task_id": "TASK-001",
                    "type": "contract_changed",
                    "severity": "blocking",
                    "status": "PROPOSED",
                    "detected_during": "IMPLEMENTING",
                    "reason_code": code,
                    "boundary_ref": "test",
                    "expected_hash": "sha256:" + "0" * 64,
                    "actual_hash": "sha256:" + "1" * 64,
                }
            )
        )

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DECISION: ESCALATED" in result.stdout
    assert "REASON: USER_AUTHORITY_REQUIRED" in result.stdout

    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["state"] == "ESCALATED"

    # Verify select_recovery never selects VERIFYING when user authority blocker is present
    blockers = [GateBlocker(code, "harness", "reason"), GateBlocker("EVIDENCE_MISSING", "verification", "ev")]
    assert select_recovery(blockers) is None


# -----------------------------------------------------------------------------
# Requirement 8: Precedence rules
# USER_AUTHORITY_REQUIRED > REPEATED_REGRESSION > NO_PROGRESS > MAX_ITERATIONS
# -----------------------------------------------------------------------------


def test_user_authority_outranks_repeated_regression_and_max_iterations(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=5, max_iterations=5)
    add_finding(h, "FND-0009")
    p = h / "findings" / "fnd-0009.yaml"
    rec = yaml.safe_load(p.read_text())
    rec["status"] = "REPRODUCING"
    rec["verified_at"] = "2026-01-01T00:00:00+00:00"  # REPEATED_REGRESSION trigger
    p.write_text(yaml.safe_dump(rec))

    # Add PROPOSED decision to trigger DECISION_UNRESOLVED
    from harness import decision

    decision.propose(
        h,
        {
            "topic": "test-topic",
            "question": "test-question",
            "context": ["test-context"],
            "options": [{"id": "opt1", "description": "desc1"}],
            "recommendation": {"option": "opt1", "reasons": ["r"], "tradeoffs": ["t"]},
            "scope": ["internal"],
            "constraints": [],
        },
    )

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "DECISION: ESCALATED" in result.stdout
    assert "REASON: USER_AUTHORITY_REQUIRED" in result.stdout
    assert "REPEATED_REGRESSION" not in result.stdout
    assert "MAX_ITERATIONS" not in result.stdout


def test_repeated_regression_outranks_no_progress_and_max_iterations(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=5, max_iterations=5)
    (h / "evidence" / "unit-test.json").unlink()
    add_finding(h, "FND-0009")
    p = h / "findings" / "fnd-0009.yaml"
    rec = yaml.safe_load(p.read_text())
    rec["status"] = "REPRODUCING"
    rec["verified_at"] = "2026-01-01T00:00:00+00:00"
    p.write_text(yaml.safe_dump(rec))

    # Set prior convergence count to 1 with matching fingerprint so next is NO_PROGRESS candidate
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    fp = compute_blocker_fingerprint([
        GateBlocker("EVIDENCE_MISSING", "verification", "unit-test", source="unit_test"),
        GateBlocker("FINDING_OPEN", "defect", "finding", finding_id="FND-0009"),
    ])
    task["convergence"] = {"fingerprint": fp, "count": 1}
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "DECISION: ESCALATED" in result.stdout
    assert "REASON: REPEATED_REGRESSION" in result.stdout
    assert "NO_PROGRESS" not in result.stdout
    assert "MAX_ITERATIONS" not in result.stdout


def test_no_progress_outranks_max_iterations(tmp_path):
    h = make_repo(tmp_path, state="GATING", iteration=5, max_iterations=5)
    (h / "evidence" / "unit-test.json").unlink()

    # Pre-set convergence count to 1 with same fingerprint
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    # Calculate exact fingerprint for unit-test evidence missing
    b = GateBlocker("EVIDENCE_MISSING", "verification", "missing unit-test evidence", source="unit_test")
    fp = compute_blocker_fingerprint([b])
    task["convergence"] = {"fingerprint": fp, "count": 1}
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "DECISION: ESCALATED" in result.stdout
    assert "REASON: NO_PROGRESS" in result.stdout
    assert "MAX_ITERATIONS" not in result.stdout


def test_alignment_next_action_stops_on_user_authority():
    from harness.alignment import AlignmentIssue
    from harness.controlplane import _alignment_next_action

    # User authority codes: CONTRACT_CHANGED and SCOPE_DRIFT_*
    for code in (
        "CONTRACT_CHANGED",
        "SCOPE_DRIFT_API",
        "SCOPE_DRIFT_PERMISSION",
        "SCOPE_DRIFT_PERSISTENCE",
    ):
        action = _alignment_next_action([AlignmentIssue(code)])
        assert action == "stop and wait: USER_AUTHORITY_REQUIRED"
        assert "harness gate" not in action
        assert "SPECIFYING" not in action
        assert "decision accept" not in action

    # OPEN_DECISION alone: must stop, report USER_AUTHORITY_REQUIRED, and NOT output decision accept or gate
    action_decision = _alignment_next_action([AlignmentIssue("OPEN_DECISION")])
    assert action_decision == "stop and wait: USER_AUTHORITY_REQUIRED"
    assert "harness gate" not in action_decision
    assert "decision accept" not in action_decision
    assert "SPECIFYING" not in action_decision

    # Mixed OPEN_DECISION and CONTRACT_CHANGED: must still stop and escalate, never decision accept or gate
    action_mixed = _alignment_next_action(
        [AlignmentIssue("OPEN_DECISION"), AlignmentIssue("CONTRACT_CHANGED")]
    )
    assert action_mixed == "stop and wait: USER_AUTHORITY_REQUIRED"
    assert "harness gate" not in action_mixed
    assert "decision accept" not in action_mixed
    assert "SPECIFYING" not in action_mixed


def test_real_drift_workflow_fails_and_preserves_implementing(tmp_path):
    """End-to-end integration test: alignment drift rejects transition VERIFYING without state change or DECISION:."""
    from harness.alignment import contract_hash

    h = make_repo(tmp_path, state="IMPLEMENTING")
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["risk"] = {
        "level": "Q2",
        "profile": "STANDARD",
        "dimensions": {
            "scope": "high",
            "contract": "high",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:test"},
    }
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    alignment_doc = {
        "version": 1,
        "task_id": "TASK-001",
        "goal": {"summary": "original goal"},
        "scope": {"in": ["feature"], "out": ["unrelated"]},
        "non_goals": ["everything else"],
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [],
        "implementation_surfaces": [],
        "verification": [],
        "decision_ids": [],
        "interface_contract_ids": [],
        "open_questions": [],
        "open_decisions": [],
        "open_loops": [],
        "freeze": {
            "frozen": True,
            "frozen_at": "2026-09-18T00:00:00+00:00",
            "contract_hash": None,
        },
    }
    alignment_doc["freeze"]["contract_hash"] = contract_hash(alignment_doc)
    # Induce drift: change goal summary after freeze
    alignment_doc["goal"]["summary"] = "changed goal summary"
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment_doc))

    impact = yaml.safe_load((h / "impact.yaml").read_text()) if (h / "impact.yaml").exists() else {}
    impact.setdefault("impact", {})["required_tests"] = ["tests/test_autonomous_convergence.py"]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    # 1. Attempt transition to VERIFYING -> fails with exit 1 and CONTRACT_CHANGED
    trans_result = run_cli(tmp_path, "transition", "VERIFYING")
    assert trans_result.returncode == 1
    assert "CONTRACT_CHANGED" in trans_result.stderr
    assert "DECISION:" not in trans_result.stdout

    # Task remains in IMPLEMENTING; convergence metadata is NOT written by transition
    task_final = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task_final["state"] == "IMPLEMENTING"
    assert "convergence" not in task_final
    assert not task_final["gate"]["blocked_by"]
    assert "POLICY: USER_AUTHORITY_REQUIRED" in trans_result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in trans_result.stderr

    # Finding is recorded
    findings = list((h / "findings").glob("FND-*.yaml"))
    assert len(findings) == 1
    finding = yaml.safe_load(findings[0].read_text())
    assert finding["reason_code"] == "CONTRACT_CHANGED"
    assert finding["status"] == "PROPOSED"

    # 2. Gate requires GATING; calling gate while IMPLEMENTING must fail with exit 1
    gate_result = run_cli(tmp_path, "gate")
    assert gate_result.returncode == 1
    assert "converge requires state GATING" in gate_result.stderr


@pytest.mark.parametrize(
    "boundary_key,boundary_val,expected_code",
    [
        ("interfaces", [{"contract_id": "INT-001", "visibility": "external"}], "SCOPE_DRIFT_API"),
        ("contracts", [{"kind": "permission", "ref": "DEC-001"}], "SCOPE_DRIFT_PERMISSION"),
        ("contracts", [{"kind": "persistence", "ref": "INT-002"}], "SCOPE_DRIFT_PERSISTENCE"),
    ],
)
def test_scope_drift_codes_reject_and_preserve_implementing(tmp_path, boundary_key, boundary_val, expected_code):
    """Transition VERIFYING rejects and preserves IMPLEMENTING state on each SCOPE_DRIFT_* code."""
    from harness.alignment import contract_hash, validate_sealed_freeze

    h = make_repo(tmp_path, state="IMPLEMENTING")
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["risk"] = {
        "level": "Q2",
        "profile": "STANDARD",
        "dimensions": {
            "scope": "high",
            "contract": "high",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:test"},
    }
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    alignment_doc = {
        "version": 1,
        "task_id": "TASK-001",
        "goal": {"summary": "original goal"},
        "scope": {"in": ["feature"], "out": ["unrelated"]},
        "non_goals": ["everything else"],
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [],
        "implementation_surfaces": [],
        "verification": [],
        "decision_ids": [],
        "interface_contract_ids": [],
        "open_questions": [],
        "open_decisions": [],
        "open_loops": [],
        "freeze": {
            "frozen": True,
            "frozen_at": "2026-09-18T00:00:00+00:00",
            "contract_hash": None,
        },
    }
    alignment_doc["freeze"]["contract_hash"] = contract_hash(alignment_doc)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment_doc))

    # Baseline seal with empty boundaries
    validate_sealed_freeze(
        h,
        alignment_doc,
        decisions=[],
        boundary_refs={"interface": [], "permission": [], "persistence": []},
    )

    # Induce boundary drift in impact.yaml
    impact = {
        "impact": {
            "changed": [],
            "direct_dependents": [],
            "contracts": [],
            "interfaces": [],
            "risks": [],
            "required_tests": ["tests/test_autonomous_convergence.py"],
        }
    }
    impact["impact"][boundary_key] = boundary_val
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    trans_result = run_cli(tmp_path, "transition", "VERIFYING")
    assert trans_result.returncode == 1
    assert "SCOPE_DRIFT" in trans_result.stderr
    assert "DECISION:" not in trans_result.stdout

    task_final = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task_final["state"] == "IMPLEMENTING"
    assert "convergence" not in task_final
    assert not task_final["gate"]["blocked_by"]
    assert "POLICY: USER_AUTHORITY_REQUIRED" in trans_result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in trans_result.stderr


def test_open_decision_align_check_stops_and_is_read_only(tmp_path):
    """Align check detects OPEN_DECISION, outputs stop-and-wait, and is strictly read-only."""
    from harness import decision
    from harness.alignment import contract_hash

    h = make_repo(tmp_path, state="IMPLEMENTING")

    # Propose a decision
    decision.propose(
        h,
        {
            "topic": "db-migration",
            "question": "Which database?",
            "context": ["need DB"],
            "options": [{"id": "opt1", "description": "Postgres"}],
            "recommendation": {"option": "opt1", "reasons": ["robust"], "tradeoffs": ["ops"]},
            "scope": ["internal"],
            "constraints": [],
        },
    )

    # Initialize a complete valid alignment document with freeze
    alignment_doc = {
        "version": 1,
        "task_id": "TASK-001",
        "goal": {"summary": "original goal"},
        "scope": {"in": ["feature"], "out": ["unrelated"]},
        "non_goals": ["everything else"],
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [],
        "implementation_surfaces": [],
        "verification": [],
        "decision_ids": [],
        "interface_contract_ids": [],
        "open_questions": [],
        "open_decisions": ["DEC-001"],
        "open_loops": [],
        "freeze": {
            "frozen": True,
            "frozen_at": "2026-09-18T00:00:00+00:00",
            "contract_hash": None,
        },
    }
    alignment_doc["freeze"]["contract_hash"] = contract_hash(alignment_doc)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment_doc))

    task_before = (h / "current-task.yaml").read_text()

    # Align check detects OPEN_DECISION, stops and waits, does NOT emit DECISION:
    check_result = run_cli(tmp_path, "align", "check")
    assert check_result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in check_result.stderr
    assert "OPEN_DECISION" in check_result.stderr
    assert "decision accept" not in check_result.stderr
    assert "SPECIFYING" not in check_result.stderr
    assert "harness gate" not in check_result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" in check_result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in check_result.stderr
    assert "DECISION:" not in check_result.stdout

    # Verify task file is untouched
    assert (h / "current-task.yaml").read_text() == task_before

    # Second run produces identical output (idempotent)
    check_result2 = run_cli(tmp_path, "align", "check")
    assert check_result2.returncode == check_result.returncode
    assert check_result2.stderr == check_result.stderr
    assert check_result2.stdout == check_result.stdout
    assert (h / "current-task.yaml").read_text() == task_before


def test_align_check_on_terminal_state_never_mutates_state_or_convergence(tmp_path):
    """Running align check on an ESCALATED task is idempotent and never changes convergence or iteration."""
    from harness.alignment import contract_hash

    h = make_repo(tmp_path, state="ESCALATED", iteration=2)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["convergence"] = {"fingerprint": "sha256:frozenfp", "count": 1}
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    alignment_doc = {
        "version": 1,
        "task_id": "TASK-001",
        "goal": {"summary": "original goal"},
        "scope": {"in": ["feature"], "out": ["unrelated"]},
        "non_goals": ["everything else"],
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [],
        "implementation_surfaces": [],
        "verification": [],
        "decision_ids": [],
        "interface_contract_ids": [],
        "open_questions": [],
        "open_decisions": ["DEC-001"],
        "open_loops": [],
        "freeze": {
            "frozen": True,
            "frozen_at": "2026-09-18T00:00:00+00:00",
            "contract_hash": None,
        },
    }
    alignment_doc["freeze"]["contract_hash"] = contract_hash(alignment_doc)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment_doc))

    task_before = (h / "current-task.yaml").read_text()
    run_cli(tmp_path, "align", "check")

    task_after = (h / "current-task.yaml").read_text()
    assert task_after == task_before


def test_mixed_open_decision_and_contract_changed(tmp_path):
    """End-to-end integration test: mixed OPEN_DECISION + CONTRACT_CHANGED -> align check stops and is read-only."""
    from harness import decision
    from harness.alignment import contract_hash, validate_sealed_freeze

    h = make_repo(tmp_path, state="IMPLEMENTING")

    decision.propose(
        h,
        {
            "topic": "db-migration",
            "question": "Which database?",
            "context": ["need DB"],
            "options": [{"id": "opt1", "description": "Postgres"}],
            "recommendation": {"option": "opt1", "reasons": ["robust"], "tradeoffs": ["ops"]},
            "scope": ["internal"],
            "constraints": [],
        },
    )

    alignment_doc = {
        "version": 1,
        "task_id": "TASK-001",
        "goal": {"summary": "original goal"},
        "scope": {"in": ["feature"], "out": ["unrelated"]},
        "non_goals": ["everything else"],
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [],
        "implementation_surfaces": [],
        "verification": [],
        "decision_ids": [],
        "interface_contract_ids": [],
        "open_questions": [],
        "open_decisions": ["DEC-001"],
        "open_loops": [],
        "freeze": {
            "frozen": True,
            "frozen_at": "2026-09-18T00:00:00+00:00",
            "contract_hash": None,
        },
    }
    alignment_doc["freeze"]["contract_hash"] = contract_hash(alignment_doc)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment_doc))

    # Baseline seal with empty boundaries
    validate_sealed_freeze(
        h,
        alignment_doc,
        decisions=decision.load_decisions(h),
        boundary_refs={"interface": [], "permission": [], "persistence": []},
    )

    # Modify goal summary to also cause CONTRACT_CHANGED and update contract_hash so freeze is valid
    alignment_doc["goal"]["summary"] = "modified summary inducing drift"
    alignment_doc["freeze"]["contract_hash"] = contract_hash(alignment_doc)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment_doc))

    task_before = (h / "current-task.yaml").read_text()

    check_result = run_cli(tmp_path, "align", "check")
    assert check_result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in check_result.stderr
    assert "decision accept" not in check_result.stderr
    assert "SPECIFYING" not in check_result.stderr
    assert "harness gate" not in check_result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" in check_result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in check_result.stderr
    assert "DECISION:" not in check_result.stdout

    # Verify task file is untouched
    assert (h / "current-task.yaml").read_text() == task_before


def test_architecture_single_convergence_authority_invariant():
    """Permanent architectural invariant: only _cmd_gate_convergence can emit DECISION: and mutate task['convergence']."""
    import ast

    controlplane_path = REPO / "src" / "harness" / "controlplane.py"
    source = controlplane_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    decision_emitters = set()
    convergence_mutators = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str) and "DECISION:" in subnode.value:
                    decision_emitters.add(node.name)
                if isinstance(subnode, ast.Subscript):
                    if isinstance(subnode.slice, ast.Constant) and subnode.slice.value == "convergence":
                        # Check if it's in a write/delete context or reading
                        convergence_mutators.add(node.name)

    # harness gate convergence is the sole convergence authority
    assert decision_emitters == {"_cmd_gate_convergence"}
    assert convergence_mutators == {"_cmd_gate_convergence"}


def test_architecture_state_machine_strict_escalation_invariant():
    """Permanent architectural invariant: ESCALATED can only be entered from BLOCKED; no shortcuts from IMPLEMENTING."""
    from harness import state_machine

    entries_into_escalated = {
        source for source, target in state_machine.TRANSITIONS if target == "ESCALATED"
    }
    assert entries_into_escalated == {"BLOCKED"}
    assert ("IMPLEMENTING", "BLOCKED") not in state_machine.TRANSITIONS
    assert ("IMPLEMENTING", "ESCALATED") not in state_machine.TRANSITIONS
