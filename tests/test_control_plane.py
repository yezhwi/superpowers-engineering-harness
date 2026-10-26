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


@pytest.fixture(autouse=True)
def fixture_workspace(tmp_path, monkeypatch):
    """Direct calls and subprocesses consume same actual fixture repository."""
    monkeypatch.chdir(tmp_path)


def test_alignment_completeness_helper_uses_current_task_proposed_decisions(tmp_path):
    from test_alignment import complete_alignment

    harness = make_repo(tmp_path)
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-001"
    task_path.write_text(yaml.safe_dump(task))
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    from test_decision import proposal

    controlplane.decision.propose(harness, proposal())

    issues = controlplane._alignment_completeness_issues(
        harness,
        yaml.safe_load((harness / "current-task.yaml").read_text()),
        document,
    )

    assert [(issue.code, issue.subject_id) for issue in issues] == [
        ("OPEN_DECISION", "DEC-001")
    ]


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


def test_gate_preflight_appends_remediation_for_known_blocker(tmp_path, monkeypatch, capsys):
    from harness.blockers import GateBlocker

    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "gate.yaml").write_text("gate: {verification_commands: {}}\n")
    monkeypatch.chdir(tmp_path)
    gate = quality_gate.GateAssessment(
        "BLOCKED",
        (GateBlocker("EVIDENCE_MISSING", "verification", "missing unit evidence"),),
        {"status": "BLOCKED"},
        {"status": "NOT_READY", "reasons": []},
    )
    monkeypatch.setattr(quality_gate, "assess_gate", lambda *_args, **_kwargs: gate)

    assert controlplane.cmd_gate_preflight() == 1
    assert "Next: Run: harness status; then run: harness resume" in capsys.readouterr().out


def test_gate_preflight_appends_plan_preview_without_duplicate_plan_blocker(
    tmp_path, monkeypatch, capsys
):
    from harness import plan_reporting
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import PlanAssessment

    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "gate.yaml").write_text("gate: {verification_commands: {}}\n")
    monkeypatch.chdir(tmp_path)
    plan_blocker = GateBlocker(
        "PLAN_ITEM_UNRECONCILED",
        "implementation",
        "plan pending",
        source="P-001",
        recover_to="IMPLEMENTING",
    )
    other_blocker = GateBlocker(
        "BUILD_FAILED", "verification", "build failed", recover_to="VERIFYING"
    )
    carried = PlanAssessment(
        (plan_blocker,),
        (plan_blocker,),
        {"P-001": {"status": "PENDING"}},
        None,
        {"version": 1, "items": [{"id": "P-001", "intent": "work"}]},
    )
    gate = quality_gate.GateAssessment(
        "BLOCKED",
        (other_blocker, plan_blocker),
        {"status": "BLOCKED"},
        {"status": "NOT_READY", "reasons": ["quality_gate_blocked"]},
        carried,
    )
    monkeypatch.setattr(quality_gate, "assess_gate", lambda *_args, **_kwargs: gate)
    monkeypatch.setattr(
        controlplane,
        "load_task",
        lambda *_args, **_kwargs: {
            "plan_reconciliation": {"enabled": True, "mode": "task_and_final"}
        },
    )
    seen = []

    original_render = plan_reporting.gate_plan_preview

    def render(task, plan, assessment):
        seen.append((plan, assessment))
        return original_render(task, plan, assessment)

    monkeypatch.setattr(plan_reporting, "gate_plan_preview", render)

    assert controlplane.cmd_gate_preflight() == 1
    output = capsys.readouterr().out
    assert output == (
        "READY: no\n"
        "- BUILD_FAILED: build failed\n"
        "Plan:\n"
        "  Mode: task_and_final\n"
        "  Progress: 0 / 1 reconciled\n"
        "  Next: P-001\n"
        "  Final: BLOCKED\n"
        "  Blockers:\n"
        "- PLAN_ITEM_UNRECONCILED: plan pending\n"
        "  source: P-001\n"
    )
    assert output.count("PLAN_ITEM_UNRECONCILED") == 1
    assert seen == [(carried.plan, carried)]


def make_repo(tmp_path: Path, *, declared_test: bool = False, profile: str = "FAST", **task_overrides) -> Path:
    from harness import workspace

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com",
         "commit", "--allow-empty", "-qm", "fixture genesis"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    initialized = run_cli(tmp_path, "init")
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    bound = run_cli(tmp_path, "task", "migrate-id", "TASK-001")
    assert bound.returncode == 0, bound.stdout + bound.stderr
    h = tmp_path / ".harness"
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    unclassified_risk = task["risk"]
    task["state"] = "CLASSIFIED"
    task["risk"] = {
        "level": {"FAST": "Q1", "STANDARD": "Q2", "STRICT": "Q3"}[profile], "profile": profile,
        "dimensions": {"scope": "low", "contract": "none", "data": "none", "authorization": "none",
                       "security": "none", "concurrency": "none", "deployment": "none"},
        "escalation_history": [], "user_changes": {"paths": [], "fingerprint": workspace.protected_paths_fingerprint((), tmp_path)},
    }
    task["git"] = workspace.git_baseline(workspace.git_head(tmp_path))
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    if declared_test:
        declare_fixture_test(h)  # Declare before higher-risk Alignment fault setup.
    task.update(task_overrides)
    if task_overrides.get("state") == "CREATED":
        task["risk"] = unclassified_risk
    elif not task["risk"]["user_changes"]["paths"]:
        task["risk"]["user_changes"]["fingerprint"] = workspace.protected_paths_fingerprint((), tmp_path)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    return h


def declare_fixture_test(h: Path) -> None:
    source = h.parent / "tests/test_control_plane.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text("def test_fixture():\n    assert True\n")
    added = run_cli(h.parent, "impact", "add-test", "tests/test_control_plane.py")
    assert added.returncode == 0, added.stdout + added.stderr


@pytest.mark.parametrize(
    ("profile", "current", "target", "code"),
    [
        ("FAST", "CREATED", "SPECIFYING", "TASK_CLASSIFICATION_REQUIRED"),
        ("FAST", "CLASSIFIED", "SPECIFYING", "PROFILE_ENTRY_STATE_REQUIRED"),
        ("STANDARD", "CLASSIFIED", "IMPLEMENTING", "PROFILE_ENTRY_STATE_REQUIRED"),
        ("STRICT", "CLASSIFIED", "IMPLEMENTING", "PROFILE_ENTRY_STATE_REQUIRED"),
        ("FAST", "BLOCKED", "IMPLEMENTING", "RESUME_REQUIRED"),
        ("STANDARD", "BLOCKED", "IMPLEMENTING", "RESUME_REQUIRED"),
        ("STRICT", "BLOCKED", "IMPLEMENTING", "RESUME_REQUIRED"),
        ("FAST", "REVIEWING", "VERIFYING", "REVIEW_OUTCOME_REQUIRED"),
        ("STANDARD", "REVIEWING", "VERIFYING", "REVIEW_OUTCOME_REQUIRED"),
        ("STRICT", "REVIEWING", "VERIFYING", "REVIEW_OUTCOME_REQUIRED"),
        ("FAST", "GATING", "BLOCKED", "GATE_DECISION_REQUIRED"),
        ("STANDARD", "GATING", "BLOCKED", "GATE_DECISION_REQUIRED"),
        ("STRICT", "GATING", "BLOCKED", "GATE_DECISION_REQUIRED"),
    ],
)
def test_structural_target_does_not_authorize_ordinary_transition(
    tmp_path, profile, current, target, code
):
    from harness.state_machine import legal_targets

    harness = make_repo(tmp_path, profile=profile, state=current)
    task_path = harness / "current-task.yaml"
    before = task_path.read_bytes()
    assert target in legal_targets(current)

    result = run_cli(tmp_path, "transition", target)

    assert result.returncode == 1, result.stdout + result.stderr
    assert code in result.stderr
    assert task_path.read_bytes() == before


def test_structural_target_still_allows_admitted_fast_transition(tmp_path):
    from harness.state_machine import legal_targets

    harness = make_repo(tmp_path, state="IMPLEMENTING")
    assert "VERIFYING" in legal_targets("IMPLEMENTING")

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["state"] == "VERIFYING"


def test_align_revise_command_is_available(tmp_path):
    h = make_repo(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-001"
    task["state"] = "PLANNED"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    from test_alignment import complete_alignment
    from harness.alignment import contract_hash

    alignment = complete_alignment()
    alignment["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-10-10T00:00:00+00:00",
        "contract_hash": None,
    }
    alignment["freeze"]["contract_hash"] = contract_hash(alignment)
    (h / "alignment.yaml").write_text(yaml.safe_dump(alignment))
    (h / "alignment-freeze.yaml").write_text("version: 2\n")

    result = run_cli(tmp_path, "align", "revise", "--reason", "contract update")

    assert result.returncode == 0, result.stderr
    revised = yaml.safe_load((h / "alignment.yaml").read_text())
    assert revised["freeze"] == {"frozen": False, "frozen_at": None, "contract_hash": None}
    assert revised["revisions"][0]["reason"] == "contract update"
    assert not (h / "alignment-freeze.yaml").exists()


def test_implementing_task_with_changed_frozen_alignment_cannot_verify(tmp_path):
    h = make_repo(
        tmp_path,
        declared_test=True,
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
    assert len(findings) == 2
    records = {record["id"]: record for record in (yaml.safe_load(path.read_text()) for path in findings)}
    assert records[finding["id"]] == finding
    assert next(record for record in records.values() if record["id"] != finding["id"])["actual_hash"] == hash_contract(alignment)


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
        declared_test=True,
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
    h = make_repo(tmp_path, declared_test=True, state="IMPLEMENTING", risk={"level": "Q3", "profile": "STRICT", "dimensions": {"scope": "high", "contract": "high", "data": "high", "authorization": "high", "security": "high", "concurrency": "none", "deployment": "none"}, "escalation_history": [], "user_changes": {"paths": [], "fingerprint": "sha256:test"}})
    from harness.alignment import contract_hash
    document = {"version": 1, "task_id": "TASK-001", "goal": {"summary": "x"}, "scope": {"in": ["x"], "out": ["y"]}, "non_goals": ["z"], "boundaries": [], "constraints": [], "assumptions": [], "acceptance_criteria": [], "implementation_surfaces": [], "verification": [], "decision_ids": [], "interface_contract_ids": [], "open_questions": [], "open_decisions": [], "open_loops": [], "freeze": {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": None}}
    document["freeze"]["contract_hash"] = contract_hash(document)
    (h / "alignment.yaml").write_text(yaml.safe_dump(document))
    impact = yaml.safe_load((h / "impact.yaml").read_text())
    impact["impact"]["contracts"] = [{"ref": ref, "kind": kind}]
    (h / "impact.yaml").write_text(yaml.safe_dump(impact))

    result = run_cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 1
    finding = yaml.safe_load(next((h / "findings").glob("FND-*.yaml")).read_text())
    assert finding["reason_code"] == reason_code
    assert finding["boundary_ref"] == ref


def test_realign_clears_internal_and_sealed_freeze(tmp_path):
    h = make_repo(tmp_path, profile="STANDARD", state="IMPLEMENTING")
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
    make_repo(tmp_path, profile="STANDARD", state="VERIFYING")
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
    make_repo(tmp_path, declared_test=True, state="IMPLEMENTING")

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
    h = make_repo(tmp_path, profile="STANDARD", state="GATING")
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
    from test_alignment import complete_alignment

    document = complete_alignment()
    document["decision_ids"] = []
    document["interface_contract_ids"] = []
    (h / "alignment.yaml").write_text(yaml.safe_dump(document))
    frozen = run_cli(tmp_path, "align", "freeze")
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    return h


def test_fixture_audited_add_preserves_bound_origin(tmp_path):
    """Break caught: fixture forges origin or directly rewrites required tests."""
    from harness._scope_replay import load_scope

    h = make_repo(tmp_path)
    origin = (h / "test-scope-baseline.yaml").read_bytes()
    declare_fixture_test(h)
    task, impact, baseline, audit, _ = load_scope(h)
    assert (h / "test-scope-baseline.yaml").read_bytes() == origin
    assert task["task"]["id"] == baseline["task_id"] == "TASK-001"
    assert baseline["origin"]["kind"] == "new_task"
    assert baseline["required_tests"] == []
    assert impact["impact"]["required_tests"] == ["tests/test_control_plane.py"]
    assert [event["operation"] for event in audit["entries"]] == ["ADD"]


@pytest.mark.parametrize("fault", ["missing_origin", "unaudited_add", "identity_mismatch"])
def test_fixture_scope_guard_still_blocks_invalid_prerequisites(tmp_path, fault):
    """Break caught: fixture maintenance makes Gate ignore scope origin drift."""
    h = _passing_harness(tmp_path)
    origin = (h / "test-scope-baseline.yaml").read_bytes()
    if fault == "missing_origin":
        (h / "test-scope-baseline.yaml").unlink()
    elif fault == "unaudited_add":
        source = tmp_path / "tests/test_control_plane.py"
        source.parent.mkdir()
        source.write_text("def test_fixture():\n    assert True\n")
        impact = yaml.safe_load((h / "impact.yaml").read_text())
        impact["impact"]["required_tests"] = ["tests/test_control_plane.py"]
        (h / "impact.yaml").write_text(yaml.safe_dump(impact))
    else:
        task = yaml.safe_load((h / "current-task.yaml").read_text())
        task["task"]["id"] = "TASK-999"
        (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    result = run_cli(tmp_path, "gate")
    assert "TEST_SCOPE_AUDIT_INVALID" in result.stdout + result.stderr
    assert yaml.safe_load((h / "current-task.yaml").read_text())["gate"]["quality"]["status"] == "BLOCKED"
    if fault != "missing_origin":
        assert (h / "test-scope-baseline.yaml").read_bytes() == origin


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


def test_realign_task_write_failure_preserves_entire_contract(tmp_path, monkeypatch):
    from test_alignment import complete_alignment

    from harness import publication_fs
    from harness.alignment import contract_hash, freeze_record

    h = make_repo(tmp_path, profile="STANDARD", state="IMPLEMENTING")
    document = complete_alignment()
    document["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-01-01T00:00:00+00:00",
        "contract_hash": contract_hash(document),
    }
    (h / "alignment.yaml").write_text(yaml.safe_dump(document))
    seal = freeze_record(
        document,
        decisions=[],
        boundary_refs={"interface": [], "permission": [], "persistence": []},
        architecture_mode="off",
        architecture_fingerprint=None,
        declared_modules=(),
    )
    (h / "alignment-freeze.yaml").write_text(yaml.safe_dump(seal))
    before = {
        name: (h / name).read_bytes()
        for name in ("current-task.yaml", "alignment.yaml", "alignment-freeze.yaml")
    }
    original_replace, original_exchange = Path.replace, publication_fs.exchange
    failures = []

    def fail_once():
        if not failures:
            failures.append("task write")
            raise OSError("TEST_REALIGN_TASK_WRITE_FAILED")

    def replace(path, target):
        if Path(target).name == "current-task.yaml":
            fail_once()
        return original_replace(path, target)

    def exchange(src_fd, src_name, dst_fd, dst_name):
        if "current-task.yaml" in (src_name, dst_name):
            fail_once()
        return original_exchange(src_fd, src_name, dst_fd, dst_name)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(publication_fs, "exchange", exchange)

    with pytest.raises(OSError, match="TEST_REALIGN_TASK_WRITE_FAILED"):
        controlplane.cmd_transition("SPECIFYING", reason="CONTRACT_CHANGED")

    assert failures == ["task write"]
    assert all((h / name).is_file() for name in before), (
        "partial realignment removed canonical facts"
    )
    assert {name: (h / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("expected", ["CONVERGED", "BLOCKED", "ESCALATED"])
@pytest.mark.parametrize("closed_warning", [False, True])
def test_gate_committed_result_survives_broken_output(
    tmp_path, monkeypatch, expected, closed_warning
):
    import builtins

    from harness.blockers import GateBlocker

    h = make_repo(tmp_path, state="GATING")
    blockers = (
        ()
        if expected == "CONVERGED"
        else (
            GateBlocker(
                "DECISION_CONFLICT" if expected == "ESCALATED" else "EVIDENCE_MISSING",
                "harness",
                "fixture blocker",
            ),
        )
    )
    assessment = quality_gate.GateAssessment(
        "PASS" if not blockers else "BLOCKED",
        blockers,
        {"status": "PASS"},
        {"status": "NOT_READY", "reasons": []},
    )
    monkeypatch.setattr(quality_gate, "assess_gate", lambda *_a, **_k: assessment)
    real_print = builtins.print

    def failed_print(*args, **kwargs):
        if (args and str(args[0]).startswith("DECISION:")) or (
            closed_warning and kwargs.get("file") is sys.stderr
        ):
            raise OSError("TEST_OUTPUT_FAILED")
        return real_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", failed_print)

    try:
        result = controlplane.cmd_gate()
    except OSError:
        pytest.fail("committed Gate output failure escaped")

    assert result == 0
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == expected


@pytest.mark.parametrize("flow", ["transition", "resume"])
@pytest.mark.parametrize("failure", ["telemetry", "stdout", "unlock"])
def test_state_command_committed_result_survives_diagnostic_failure(
    tmp_path, monkeypatch, flow, failure
):
    import builtins
    from contextlib import contextmanager

    from harness.blockers import GateBlocker, blocker_document

    h = make_repo(tmp_path, state="VERIFYING" if flow == "transition" else "BLOCKED")
    if flow == "resume":
        task = yaml.safe_load((h / "current-task.yaml").read_text())
        task["gate"]["blocked_by"] = [
            blocker_document(GateBlocker("EVIDENCE_MISSING", "verification", "collect"))
        ]
        (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    if failure == "telemetry":

        def fail(*args, **kwargs):
            raise OSError("TEST_TELEMETRY_FAILED")

        monkeypatch.setattr(controlplane.telemetry, "update_telemetry", fail)
    elif failure == "stdout":
        real_print = builtins.print

        def fail(*args, **kwargs):
            if args and str(args[0]).startswith("OK:"):
                raise OSError("TEST_OUTPUT_FAILED")
            return real_print(*args, **kwargs)

        monkeypatch.setattr(builtins, "print", fail)
    else:
        original = controlplane.publication_admission

        @contextmanager
        def fail(root):
            with original(root):
                yield
            raise OSError("TEST_UNLOCK_FAILED")

        monkeypatch.setattr(controlplane, "publication_admission", fail)
    try:
        result = (
            controlplane.cmd_transition("IMPLEMENTING")
            if flow == "transition"
            else controlplane.cmd_resume()
        )
    except OSError:
        pytest.fail("committed state command reported I/O failure")
    assert result == 0
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == (
        "IMPLEMENTING" if flow == "transition" else "VERIFYING"
    )


def test_realignment_committed_result_survives_stage_retention_failure(
    tmp_path, monkeypatch
):
    h = make_repo(tmp_path, profile="STANDARD", state="IMPLEMENTING")

    def fail(*args, **kwargs):
        raise OSError("TEST_STAGE_RETENTION_FAILED")

    monkeypatch.setattr(controlplane.transaction, "_retain_stage", fail)
    try:
        result = controlplane.cmd_transition("SPECIFYING", reason="CONTRACT_CHANGED")
    except OSError:
        pytest.fail(
            "committed realignment reported retention failure as command failure"
        )
    assert result == 0
    assert (
        yaml.safe_load((h / "current-task.yaml").read_text())["state"] == "SPECIFYING"
    )


@pytest.mark.parametrize("closed_stderr", [False, True])
def test_gate_native_broken_pipe_keeps_process_success_after_commit(
    tmp_path, closed_stderr
):
    import os

    h = make_repo(tmp_path, state="GATING")
    code = """
from harness import controlplane, quality_gate
input()
quality_gate.assess_gate = lambda *a, **k: quality_gate.GateAssessment('PASS', (), {'status':'PASS'}, {'status':'READY','reasons':[]})
raise SystemExit(controlplane.cmd_gate())
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        child.stdout.close()
        if closed_stderr:
            child.stderr.close()
        child.stdin.write(b"go\n")
        child.stdin.close()
        result = child.wait(timeout=30)
        errors = "" if closed_stderr else child.stderr.read().decode()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        if not closed_stderr:
            child.stderr.close()
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == "CONVERGED"
    assert result == 0, errors


@pytest.mark.parametrize("authority", [True, False])
def test_planned_admission_next_step_respects_authority_halt(tmp_path, capsys, authority):
    from fixtures.harness import populate_complete_harness
    from test_alignment import complete_alignment
    from test_decision import proposal
    from test_minimal_implementation import _local_decision

    h = make_repo(tmp_path, state="PLANNED", profile="STANDARD")
    populate_complete_harness(tmp_path, h)
    (h / "evidence/minimal-implementation.yaml").write_text(yaml.safe_dump(_local_decision()))
    document = complete_alignment()
    if authority:
        controlplane.decision.propose(h, proposal())
    else:
        document["goal"]["summary"] = ""
        document["decision_ids"] = []
        document["interface_contract_ids"] = []
    (h / "alignment.yaml").write_text(yaml.safe_dump(document))
    before = (h / "current-task.yaml").read_bytes()
    capsys.readouterr()

    assert controlplane.cmd_transition("IMPLEMENTING") == 1
    output = capsys.readouterr()

    assert (h / "current-task.yaml").read_bytes() == before
    assert "ALIGNMENT_BLOCKED" in output.err
    if authority:
        assert "OPEN_DECISION" in output.err
        assert "DIRECTIVE: HALT_AND_WAIT" in output.err
        assert "Next:" not in output.err + output.out
    else:
        assert "DIRECTIVE: HALT_AND_WAIT" not in output.err
        assert "Next: harness check admission" in output.err


@pytest.mark.parametrize('same_task', [True, False])
def test_specifying_admission_checks_only_current_proposed_decisions(tmp_path, capsys, same_task):
    from fixtures.harness import populate_complete_harness
    from test_alignment import complete_alignment
    from test_decision import proposal

    h = make_repo(tmp_path, state='SPECIFYING', profile='STANDARD')
    populate_complete_harness(tmp_path, h)
    document = complete_alignment()
    document['decision_ids'] = []
    document['interface_contract_ids'] = []
    (h / 'alignment.yaml').write_text(yaml.safe_dump(document))
    record = controlplane.decision.propose(h, proposal())
    if not same_task:
        record['task_id'] = 'TASK-999'
        (h / 'decisions' / f"{record['id']}.yaml").write_text(yaml.safe_dump(record))
    before = (h / 'current-task.yaml').read_bytes()
    capsys.readouterr()

    result = controlplane.cmd_transition('PLANNED')
    output = capsys.readouterr()

    if same_task:
        assert result == 1
        assert 'OPEN_DECISION' in output.err
        assert (h / 'current-task.yaml').read_bytes() == before
    else:
        assert result == 0, output.err
        assert yaml.safe_load((h / 'current-task.yaml').read_text())['state'] == 'PLANNED'
