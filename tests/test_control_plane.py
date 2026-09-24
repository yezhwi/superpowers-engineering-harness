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

from harness import controlplane, quality_gate
from evidence_factory import write_complexity_review, write_evidence

REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def test_alignment_finding_schema_accepts_closed_lifecycle_status(tmp_path):
    finding = {
        "id": "FND-001", "category": "alignment", "task_id": "TASK-001",
        "type": "contract_changed", "severity": "blocking", "status": "CLOSED",
        "detected_during": "IMPLEMENTING", "expected_hash": "sha256:" + "0" * 64,
        "actual_hash": "sha256:" + "1" * 64,
        "reason_code": "SCOPE_DRIFT_PERMISSION", "boundary_ref": "DEC-001",
    }
    quality_gate.validate_schema(
        finding, "alignment-finding.schema.json", tmp_path / "finding.yaml"
    )


def test_gate_preflight_requires_release_readiness_for_ready_output(tmp_path, monkeypatch, capsys):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "gate.yaml").write_text("gate: {verification_commands: {}}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        quality_gate,
        "assess_gate",
        lambda *_args, **_kwargs: quality_gate.GateAssessment(
            "PASS", (), {"status": "PASS"},
            {"status": "NOT_READY", "reasons": ["quality_gate_blocked"]},
        ),
    )

    assert controlplane.cmd_gate_preflight() == 0
    assert "READY: no" in capsys.readouterr().out


def make_repo(tmp_path: Path, **task_overrides) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    run_cli(tmp_path, "init")
    # gate/evidence need a resolvable HEAD
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=tmp_path, check=True, capture_output=True
    )
    h = tmp_path / ".harness"
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task.update(task_overrides)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    return h


def test_implementing_task_with_changed_frozen_alignment_cannot_verify(tmp_path):
    h = make_repo(
        tmp_path,
        state="IMPLEMENTING",
        risk={
            "level": "Q2",
            "profile": "STANDARD",
            "dimensions": {
                "scope": "high", "contract": "high", "data": "none",
                "authorization": "none", "security": "none", "concurrency": "none",
                "deployment": "none",
            },
            "escalation_history": [],
            "user_changes": {"paths": [], "fingerprint": "sha256:test"},
        },
    )
    alignment = {
        "version": 1, "task_id": "TASK-001", "goal": {"summary": "original"},
        "scope": {"in": ["x"], "out": ["y"]}, "non_goals": ["z"],
        "boundaries": [], "constraints": [], "assumptions": [],
        "acceptance_criteria": [], "implementation_surfaces": [], "verification": [],
        "decision_ids": [], "interface_contract_ids": [], "open_questions": [],
        "open_decisions": [], "open_loops": [],
        "freeze": {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": None},
    }
    from harness.alignment import contract_hash
    alignment["freeze"]["contract_hash"] = contract_hash(alignment)
    alignment["goal"]["summary"] = "changed"
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment))
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    impact["impact"]["required_tests"] = ["tests/test_control_plane.py"]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 1
    assert "CONTRACT_CHANGED" in result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in result.stderr
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == "IMPLEMENTING"
    findings = list((h / "findings").glob("FND-*.yaml"))
    assert len(findings) == 1
    finding = yaml.safe_load(findings[0].read_text())
    assert finding["category"] == "alignment"
    assert finding["type"] == "contract_changed"
    assert finding["expected_hash"] != finding["actual_hash"]
    # Guard Findings are audit records, never cached Gate results.
    assert not yaml.safe_load((h / "current-task.yaml").read_text())["gate"]["blocked_by"]
    task_before_inspection = (h / "current-task.yaml").read_bytes()
    for command in ("check", "status", "diff"):
        inspection = run_cli(tmp_path, "align", command)
        assert inspection.returncode == 1
        assert "POLICY: USER_AUTHORITY_REQUIRED" in inspection.stderr
        assert "DIRECTIVE: HALT_AND_WAIT" in inspection.stderr
        assert "DECISION:" not in inspection.stdout
        assert (h / "current-task.yaml").read_bytes() == task_before_inspection
    alignment["goal"]["summary"] = "changed again"
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment))
    from harness.alignment import contract_hash as hash_contract
    repeat = run_cli(tmp_path, "transition", "VERIFYING")
    assert repeat.returncode == 1
    findings = list((h / "findings").glob("FND-*.yaml"))
    assert len(findings) == 1
    updated = yaml.safe_load(findings[0].read_text())
    assert updated["actual_hash"] == hash_contract(alignment)
    assert updated["id"] == finding["id"]


def test_impact_add_contract_writes_typed_record_and_protects_ref(tmp_path, monkeypatch):
    h = make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert controlplane.cmd_impact("add-contract", "DEC-001", args=type("Args", (), {"kind": "permission"})()) == 0
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    assert impact["impact"]["contracts"] == [{"ref": "DEC-001", "kind": "permission"}]
    assert controlplane.cmd_impact("ignore-user-path", "DEC-001") == 1


def test_impact_legacy_contract_ref_remains_protected(tmp_path, monkeypatch):
    h = make_repo(tmp_path)
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    impact["impact"]["contracts"] = ["DEC-001"]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))
    monkeypatch.chdir(tmp_path)

    assert controlplane.cmd_impact("ignore-user-path", "DEC-001") == 1


def test_boundary_ref_adapters_keep_legacy_conservative_and_typed_explicit():
    document = {"interface_contract_ids": ["INT-001"]}
    impact = {"interfaces": [{"visibility": "external", "contract_id": "INT-002"}], "contracts": ["DEC-legacy", {"ref": "DEC-001", "kind": "permission"}, {"ref": "INT-003", "kind": "persistence"}]}

    assert controlplane.legacy_boundary_baseline(document) == {"interface": ["INT-001"], "permission": [], "persistence": []}
    assert controlplane.current_boundary_refs(document, impact) == {"interface": ["INT-002"], "permission": ["DEC-001"], "persistence": ["INT-003"]}


def test_typed_contracts_normalizes_legacy_and_validates_kinds():
    assert controlplane.typed_contracts({"contracts": ["DEC-001", {"ref": "INT-001", "kind": "permission"}]}) == [
        {"ref": "DEC-001", "kind": "generic"},
        {"ref": "INT-001", "kind": "permission"},
    ]
    with pytest.raises(ValueError, match="IMPACT_CONTRACT_KIND_INVALID"):
        controlplane.typed_contracts({"contracts": [{"ref": "DEC-001", "kind": "prefix:permission"}]})


def test_implementing_task_with_declared_api_drift_cannot_verify(tmp_path):
    h = make_repo(
        tmp_path,
        state="IMPLEMENTING",
        risk={
            "level": "Q3", "profile": "STRICT",
            "dimensions": {"scope": "high", "contract": "high", "data": "high", "authorization": "high", "security": "high", "concurrency": "none", "deployment": "none"},
            "escalation_history": [],
            "user_changes": {"paths": [], "fingerprint": "sha256:test"},
        },
    )
    from harness.alignment import contract_hash
    alignment = {
        "version": 1, "task_id": "TASK-001", "goal": {"summary": "original"},
        "scope": {"in": ["x"], "out": ["y"]}, "non_goals": ["z"], "boundaries": [], "constraints": [], "assumptions": [],
        "acceptance_criteria": [], "implementation_surfaces": [], "verification": [], "decision_ids": [], "interface_contract_ids": [],
        "open_questions": [], "open_decisions": [], "open_loops": [], "freeze": {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": None},
    }
    alignment["freeze"]["contract_hash"] = contract_hash(alignment)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment))
    # Declared boundary fact must block independently of private implementation paths.
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    impact["impact"]["interfaces"] = [{"id": "API-001", "visibility": "external", "contract_id": "INT-001"}]
    impact["impact"]["required_tests"] = ["tests/test_control_plane.py"]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 1
    assert "SCOPE_DRIFT" in result.stderr
    finding = yaml.safe_load(next((h / "findings").glob("FND-*.yaml")).read_text())
    assert finding["reason_code"] == "SCOPE_DRIFT_API"
    assert finding["boundary_ref"] == "INT-001"
    repeat = run_cli(tmp_path, "transition", "VERIFYING")
    assert repeat.returncode == 1
    assert len(list((h / "findings").glob("FND-*.yaml"))) == 1


@pytest.mark.parametrize(
    ("kind", "ref", "reason_code"),
    [
        ("permission", "DEC-001", "SCOPE_DRIFT_PERMISSION"),
        ("persistence", "INT-001", "SCOPE_DRIFT_PERSISTENCE"),
    ],
)
def test_implementing_task_with_typed_boundary_drift_cannot_verify(
    tmp_path, kind, ref, reason_code
):
    h = make_repo(tmp_path, state="IMPLEMENTING", risk={"level": "Q3", "profile": "STRICT", "dimensions": {"scope": "high", "contract": "high", "data": "high", "authorization": "high", "security": "high", "concurrency": "none", "deployment": "none"}, "escalation_history": [], "user_changes": {"paths": [], "fingerprint": "sha256:test"}})
    from harness.alignment import contract_hash
    document = {"version": 1, "task_id": "TASK-001", "goal": {"summary": "x"}, "scope": {"in": ["x"], "out": ["y"]}, "non_goals": ["z"], "boundaries": [], "constraints": [], "assumptions": [], "acceptance_criteria": [], "implementation_surfaces": [], "verification": [], "decision_ids": [], "interface_contract_ids": [], "open_questions": [], "open_decisions": [], "open_loops": [], "freeze": {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": None}}
    document["freeze"]["contract_hash"] = contract_hash(document)
    (h / "alignment.yaml").write_text(yaml.safe_dump(document))
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    impact["impact"]["contracts"] = [{"ref": ref, "kind": kind}]
    impact["impact"]["required_tests"] = ["tests/test_control_plane.py"]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 1
    finding = yaml.safe_load(next((h / "findings").glob("FND-*.yaml")).read_text())
    assert finding["reason_code"] == reason_code
    assert finding["boundary_ref"] == ref


def test_realign_clears_internal_and_sealed_freeze(tmp_path):
    h = make_repo(tmp_path, state="IMPLEMENTING")
    alignment = {"version": 1, "task_id": "TASK-001", "goal": {"summary": "x"}, "scope": {"in": ["x"], "out": ["y"]}, "non_goals": ["z"], "boundaries": [], "constraints": [], "assumptions": [], "acceptance_criteria": [], "implementation_surfaces": [], "verification": [], "decision_ids": [], "interface_contract_ids": [], "open_questions": [], "open_decisions": [], "open_loops": [], "freeze": {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": None}}
    from harness.alignment import contract_hash
    alignment["freeze"]["contract_hash"] = contract_hash(alignment)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment))
    (h / "alignment-freeze.yaml").write_text("version: 1\ntask_id: TASK-001\ncontract_hash: sha256:" + "0" * 64 + "\ndecision_selections: {}\nboundary_refs: {interface: [], permission: [], persistence: []}\nfrozen_at: now\n")

    result = run_cli(tmp_path, "transition", "SPECIFYING", "--reason", "SCOPE_DRIFT")

    assert result.returncode == 0
    assert not (h / "alignment-freeze.yaml").exists()
    assert yaml.safe_load((h / "alignment.yaml").read_text())["freeze"]["frozen"] is False


def test_implementing_task_realign_requires_whitelisted_reason(tmp_path):
    h = make_repo(
        tmp_path,
        state="IMPLEMENTING",
        risk={
            "level": "Q2", "profile": "STANDARD",
            "dimensions": {"scope": "high", "contract": "high", "data": "none", "authorization": "none", "security": "none", "concurrency": "none", "deployment": "none"},
            "escalation_history": [],
            "user_changes": {"paths": [], "fingerprint": "sha256:test"},
        },
    )

    rejected = run_cli(tmp_path, "transition", "SPECIFYING")
    accepted = run_cli(tmp_path, "transition", "SPECIFYING", "--reason", "CONTRACT_CHANGED")

    assert rejected.returncode == 1
    assert "REALIGN_REASON_REQUIRED" in rejected.stderr
    assert accepted.returncode == 0, accepted.stderr
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == "SPECIFYING"


def test_controlplane_has_no_generic_dynamic_module_loader():
    """Break caught: dependency navigation remains hidden behind _load."""
    source = (REPO / "src/harness/controlplane.py").read_text()
    assert "def _load(" not in source


# -- status ---------------------------------------------------------------


def test_status_renders_state(tmp_path):
    h = make_repo(tmp_path, state="GATING")
    result = run_cli(tmp_path, "status")
    assert result.returncode == 0
    assert "State        GATING" in result.stdout


def test_status_from_repository_subdirectory_uses_root_harness(tmp_path):
    h = make_repo(tmp_path, state="GATING")
    nested = tmp_path / "src" / "nested"
    nested.mkdir(parents=True)

    result = run_cli(nested, "status")

    assert result.returncode == 0
    assert "State        GATING" in result.stdout
    assert not (nested / ".harness").exists()


def test_cli_main_restores_callers_working_directory(tmp_path, monkeypatch):
    make_repo(tmp_path, state="GATING")
    nested = tmp_path / "src" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    from harness.cli import main

    assert main(["status"]) == 0
    assert Path.cwd() == nested


def test_status_invalid_state_exit_2(tmp_path):
    make_repo(tmp_path, state="WAT")
    assert run_cli(tmp_path, "status").returncode == 2


# -- transition ------------------------------------------------------------


def test_created_task_cannot_bypass_risk_classification_into_specifying(tmp_path):
    """Break caught: unclassified task skips protected-workspace baseline."""
    make_repo(tmp_path, state="CREATED")

    result = run_cli(tmp_path, "transition", "SPECIFYING")

    assert result.returncode == 1
    assert "TASK_CLASSIFICATION_REQUIRED" in result.stderr


def test_resume_guard_rejects_malformed_finding_without_traceback(tmp_path):
    """Break caught: malformed Finding crashes specialized transition guard."""
    h = make_repo(tmp_path, state="REPRODUCING")
    (h / "findings" / "FND-001.yaml").write_text("[not-a-mapping")

    result = run_cli(tmp_path, "transition", "REVIEWING")

    assert result.returncode == 2
    assert "FINDING_STATE_INVALID" in result.stderr
    assert "Traceback" not in result.stderr


def test_fast_realign_requires_task_escalation(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING", risk={
        "level": "Q1", "profile": "FAST",
        "dimensions": {"scope": "low", "contract": "none", "data": "none", "authorization": "none", "security": "none", "concurrency": "none", "deployment": "none"},
        "escalation_history": [], "user_changes": {"paths": [], "fingerprint": "sha256:test"},
    })

    result = run_cli(tmp_path, "transition", "SPECIFYING", "--reason", "SCOPE_DRIFT")

    assert result.returncode == 1
    assert "RISK_ESCALATION_REQUIRED" in result.stderr
    assert "harness task escalate Q2 --reason SCOPE_DRIFT" in result.stderr


def test_transition_cannot_reenter_specifying_without_realign_reason(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING")

    result = run_cli(tmp_path, "transition", "SPECIFYING")

    assert result.returncode == 1
    assert "REALIGN_REASON_REQUIRED" in result.stderr


def test_transition_legal_persists_new_state(tmp_path):
    h = make_repo(tmp_path, state="PLANNED")
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-001"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    decision = {
        "version": 1,
        "task": "TASK-001",
        "checks": {
            "existence": {"checked": True, "result": "required"},
            "reuse": {"checked": True, "result": "none"},
            "stdlib": {"checked": True, "result": "none"},
            "native": {"checked": True, "result": "none"},
            "existing_dependency": {"checked": True, "result": "none"},
            "minimum_local_implementation": {"checked": True, "result": "required"},
        },
        "decision": {"approach": "local_implementation", "rationale": "test fixture"},
    }
    (h / "evidence" / "minimal-implementation.yaml").write_text(
        yaml.safe_dump(decision)
    )
    result = run_cli(tmp_path, "transition", "IMPLEMENTING")
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load((tmp_path / ".harness" / "current-task.yaml").read_text())
    assert task["state"] == "IMPLEMENTING"


def test_verifying_to_reviewing_rejects_stale_required_evidence(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path, state="VERIFYING")
    monkeypatch.chdir(tmp_path)
    blocker = quality_gate.GateBlocker(
        "EVIDENCE_WORKSPACE_STALE", "verification", "unit evidence invalid"
    )
    monkeypatch.setattr(
        quality_gate,
        "run_gate",
        lambda *_args, **_kwargs: ("BLOCKED", [blocker]),
    )

    assert controlplane.cmd_transition("REVIEWING") == 1
    assert "EVIDENCE_WORKSPACE_STALE" in capsys.readouterr().err


def test_transition_illegal_rejected_and_unchanged(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING")
    result = run_cli(tmp_path, "transition", "DONE")
    assert result.returncode == 1
    assert "INVALID TRANSITION" in result.stdout + result.stderr
    task = yaml.safe_load((tmp_path / ".harness" / "current-task.yaml").read_text())
    assert task["state"] == "IMPLEMENTING"


def test_related_required_tests_do_not_block_verifying(tmp_path):
    h = make_repo(tmp_path, state="IMPLEMENTING")
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    impact["impact"]["required_tests"] = ["tests/test_control_plane.py"]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 0, result.stderr


def test_transition_missing_target_exit_2(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "transition").returncode == 2


def test_transition_unknown_state_exit_2(tmp_path):
    make_repo(tmp_path)
    assert run_cli(tmp_path, "transition", "NOT_A_STATE").returncode == 2


# -- evidence ---------------------------------------------------------------


def test_evidence_writes_head_bound_json(tmp_path):
    make_repo(tmp_path)
    result = run_cli(tmp_path, "evidence", "--type", "build", "--command", "true")
    assert result.returncode == 0, result.stdout + result.stderr
    ev = json.loads((tmp_path / ".harness" / "evidence" / "build.json").read_text())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    assert ev["exit_code"] == 0
    assert ev["commit"] == head
    assert ev["type"] == "build"


def test_evidence_failing_command_still_saved(tmp_path):
    make_repo(tmp_path)
    result = run_cli(
        tmp_path,
        "evidence",
        "--type",
        "unit_test",
        "--scope",
        "related",
        "--covered-test",
        "tests/test_control_plane.py::test_evidence_failing_command_still_saved",
        "--command",
        "false",
    )
    # evidence is recorded; the wrapper reports the underlying failure
    [path] = (tmp_path / ".harness" / "evidence").glob("unit-test-*.json")
    ev = json.loads(path.read_text())
    assert ev["exit_code"] != 0


def test_evidence_invalid_type_exit_2(tmp_path):
    make_repo(tmp_path)
    result = run_cli(tmp_path, "evidence", "--type", "vibes", "--command", "true")
    assert result.returncode == 2


# -- gate -----------------------------------------------------------------


def _passing_harness(tmp_path):
    h = make_repo(tmp_path, state="GATING")
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": ["unit-test.json"],
                "test_plan": {
                    "strategies": ["manual"],
                    "cases": [
                        {
                            "id": "TC-800",
                            "type": "happy_path",
                            "strategy": "manual",
                            "description": "fixture requirement",
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
                            "id": "TC-801",
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
    build["covered_test_cases"] = ["TC-800", "TC-801"]
    (edir / "build.json").write_text(json.dumps(build))
    return h


def test_gate_pass_maps_to_zero_and_writes_back(tmp_path):
    _passing_harness(tmp_path)
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    task = yaml.safe_load((tmp_path / ".harness" / "current-task.yaml").read_text())
    assert task["gate"]["status"] == "PASS"


def test_done_rejected_when_workspace_changes_after_convergence(tmp_path):
    _passing_harness(tmp_path)
    assert run_cli(tmp_path, "gate").returncode == 0
    (tmp_path / "business.py").write_text("changed")

    result = run_cli(tmp_path, "transition", "DONE")

    assert result.returncode == 1
    assert "CURRENT_GATE_PASS_REQUIRED" in result.stderr
    task = yaml.safe_load((tmp_path / ".harness" / "current-task.yaml").read_text())
    assert task["state"] == "CONVERGED"


def test_done_allowed_when_current_gate_passes(tmp_path):
    _passing_harness(tmp_path)
    assert run_cli(tmp_path, "gate").returncode == 0

    result = run_cli(tmp_path, "transition", "DONE")

    assert result.returncode == 0


def test_gate_blocked_transitions_to_blocked(tmp_path):
    h = _passing_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "pending",
                "evidence": [],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = run_cli(tmp_path, "gate")
    assert result.returncode == 0
    assert "not verified" in result.stdout
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["state"] == "BLOCKED"
    assert task["gate"]["quality"]["status"] == "BLOCKED"
    assert task["gate"]["release_readiness"]["status"] == "NOT_READY"
