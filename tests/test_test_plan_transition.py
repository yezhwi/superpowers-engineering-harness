"""Test Plan entry Gate integration tests."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parent.parent
SAFE = {
    "scope": "low",
    "contract": "none",
    "data": "none",
    "authorization": "none",
    "security": "none",
    "concurrency": "none",
    "deployment": "none",
}


def cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def standard_repo_in_state(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    dimensions = {**SAFE, "scope": "high", "contract": "high"}
    flags = [
        value
        for name, setting in dimensions.items()
        for value in (f"--{name}", setting)
    ]
    assert cli(tmp_path, "task", "classify", "--level", "Q2", *flags).returncode == 0
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-004"
    task["state"] = "PLANNED"
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    return tmp_path


def test_q2_classification_persists_final_plan_reconciliation_enablement(tmp_path):
    repo = standard_repo_in_state(tmp_path)

    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())

    assert task["plan_reconciliation"] == {"enabled": True, "mode": "final"}


def write_plan_artifacts(repo: Path):
    from harness.plan_reconciliation import plan_fingerprint

    plan = {"version": 1, "items": []}
    (repo / ".harness/plan.yaml").write_text(yaml.safe_dump(plan))
    (repo / ".harness/plan-execution.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
                "items": {},
            }
        )
    )


def write_minimal_decision(repo: Path):
    decision = {
        "version": 1,
        "task": "TASK-004",
        "checks": {
            "existence": {"checked": True, "result": "required"},
            "reuse": {"checked": True, "result": "none"},
            "stdlib": {"checked": True, "result": "none"},
            "native": {"checked": True, "result": "none"},
            "existing_dependency": {"checked": True, "result": "none"},
            "minimum_local_implementation": {"checked": True, "result": "required"},
        },
        "decision": {"approach": "local_implementation", "rationale": "required"},
    }
    path = repo / ".harness/evidence/minimal-implementation.yaml"
    path.write_text(yaml.safe_dump(decision, sort_keys=False))


def write_alignment(repo: Path, *, open_decisions=None, frozen=False):
    document = {
        "version": 1,
        "task_id": "TASK-004",
        "goal": {"summary": "enter implementation with closed intent"},
        "scope": {"in": ["src/harness"], "out": ["CLI"]},
        "non_goals": ["scope drift"],
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [
            {
                "id": "AC-001",
                "description": "entry is ready",
                "requirement_ids": ["REQ-001"],
            }
        ],
        "implementation_surfaces": [
            {
                "id": "SURFACE-001",
                "acceptance_criteria": ["AC-001"],
                "paths": ["src/harness/controlplane.py"],
                "seam": "cmd_transition",
            }
        ],
        "verification": [
            {
                "id": "VER-001",
                "acceptance_criteria": ["AC-001"],
                "method": "test",
                "expected_evidence": "unit test evidence",
            }
        ],
        "decision_ids": [],
        "interface_contract_ids": [],
        "open_questions": [],
        "open_decisions": open_decisions or [],
        "open_loops": [],
        "freeze": {"frozen": frozen, "frozen_at": None, "contract_hash": None},
    }
    if frozen:
        from harness.alignment import contract_hash

        document["freeze"] = {
            "frozen": True,
            "frozen_at": "2026-09-18T00:00:00+00:00",
            "contract_hash": contract_hash(document),
        }
    (repo / ".harness/alignment.yaml").write_text(yaml.safe_dump(document))


def write_documents(repo: Path, *, valid: bool):
    strategies = ["unit"] if valid else []
    requirement = {
        "id": "REQ-001",
        "statement": "feature works",
        "priority": "must",
        "status": "pending",
        "test_plan": {
            "strategies": strategies,
            "cases": [
                {
                    "id": "TC-001",
                    "type": "happy_path",
                    "strategy": "unit",
                    "description": "works",
                }
            ],
        },
    }
    invariant = {
        "id": "INV-001",
        "statement": "safe",
        "category": "correctness",
        "severity": "critical",
        "status": "pending",
        "verification": [],
        "test_plan": {
            "strategies": ["integration"],
            "cases": [
                {
                    "id": "TC-002",
                    "type": "invariant",
                    "strategy": "integration",
                    "description": "holds",
                }
            ],
        },
    }
    (repo / ".harness/requirements.yaml").write_text(
        yaml.safe_dump({"requirements": [requirement]})
    )
    (repo / ".harness/invariants.yaml").write_text(
        yaml.safe_dump({"invariants": [invariant]})
    )


def test_standard_planned_to_implementing_rejects_invalid_test_plan(tmp_path):
    """Break caught: STANDARD task starts implementation without a strategy."""
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=False)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "TEST_PLAN_BLOCKED" in result.stderr
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["state"]
        == "PLANNED"
    )


def test_standard_planned_to_implementing_rejects_missing_declared_test_target(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    requirements_path = repo / ".harness/requirements.yaml"
    requirements = yaml.safe_load(requirements_path.read_text())
    requirements["requirements"][0]["test_plan"]["cases"][0]["tests"] = [
        "tests/does-not-exist.py"
    ]
    requirements_path.write_text(yaml.safe_dump(requirements))

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "TEST_PLAN_TARGET_MISSING" in result.stderr


def test_standard_planned_to_implementing_rejects_missing_alignment(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" not in result.stderr
    assert yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["state"] == "PLANNED"


def test_standard_entry_rejects_persisted_proposed_decision_not_listed_in_alignment(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    assert cli(repo, "decision", "propose", "--topic", "scope", "--question", "choose", "--context", "x", "--option", "a=A", "--recommend", "a", "--reason", "x").returncode == 0

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in result.stderr
    assert "OPEN_DECISION" in result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in result.stderr
    assert "DECISION_UNRESOLVED" not in result.stderr
    assert "STATUS: REJECTED" not in result.stderr
    assert "BLOCKER:" not in result.stderr


def test_standard_planned_to_implementing_rejects_open_alignment_decision(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, open_decisions=["DEC-001"])

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in result.stderr
    assert "OPEN_DECISION" in result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in result.stderr


def test_enabled_standard_entry_requires_matching_plan_artifacts(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "PLAN_REQUIRED" in result.stderr


def test_enabled_standard_entry_treats_malformed_plan_as_invalid_state(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    (repo / ".harness/plan.yaml").write_text("not: [valid")
    (repo / ".harness/plan-execution.yaml").write_text("version: 1")

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr


def test_legacy_standard_entry_ignores_malformed_plan_artifacts(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    task_path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task.pop("plan_reconciliation")
    task_path.write_text(yaml.safe_dump(task))
    (repo / ".harness/plan.yaml").write_text("not: [valid")

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr


def test_standard_planned_to_implementing_accepts_complete_alignment(tmp_path):
    """Break caught: complete intent closure cannot reach implementation."""
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    write_plan_artifacts(repo)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr


def q3_entry_repo(tmp_path: Path) -> Path:
    repo = standard_repo_in_state(tmp_path)
    task_path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["level"] = "Q3"
    task["risk"]["profile"] = "STRICT"
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    return repo


def write_entry_execution(repo: Path, *, version=2, transitions=None, items=None):
    from harness.plan_reconciliation import plan_fingerprint

    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "entry", "surfaces": ["src/first.py"]}
        ],
    }
    execution = {
        "version": version,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": items or {},
    }
    if version == 2:
        execution["sequence"] = len(transitions or [])
        execution["transitions"] = transitions or []
    (repo / ".harness/plan.yaml").write_text(yaml.safe_dump(plan, sort_keys=False))
    (repo / ".harness/plan-execution.yaml").write_text(
        yaml.safe_dump(execution, sort_keys=False)
    )


def test_q3_strict_entry_accepts_fresh_empty_v2(tmp_path):
    repo = q3_entry_repo(tmp_path)
    write_entry_execution(repo)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr


def test_q3_strict_entry_requires_execution_v2(tmp_path):
    repo = q3_entry_repo(tmp_path)
    write_entry_execution(repo, version=1)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "PLAN_TASK_LEVEL_REQUIRED" in result.stderr


def test_q3_strict_entry_rejects_nonempty_v2(tmp_path):
    repo = q3_entry_repo(tmp_path)
    transition = {
        "sequence": 1,
        "item": "P-001",
        "from": "PENDING",
        "to": "IN_PROGRESS",
        "action": "BEGIN",
    }
    write_entry_execution(
        repo,
        transitions=[transition],
        items={"P-001": {"status": "IN_PROGRESS"}},
    )

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "PLAN_SEQUENCE_INVALID" in result.stderr


def test_q3_strict_entry_rejects_replay_invalid_v2(tmp_path):
    repo = q3_entry_repo(tmp_path)
    transitions = [
        {
            "sequence": sequence,
            "item": "P-001",
            "from": "PENDING",
            "to": "IN_PROGRESS",
            "action": "BEGIN",
        }
        for sequence in (1, 2)
    ]
    write_entry_execution(
        repo,
        transitions=transitions,
        items={"P-001": {"status": "IN_PROGRESS"}},
    )

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "PLAN_SEQUENCE_INVALID" in result.stderr


def test_q2_entry_rejects_execution_v2_with_disposition_code(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    write_entry_execution(repo)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "PLAN_DISPOSITION_INVALID" in result.stderr
    assert "PLAN_SEQUENCE_INVALID" not in result.stderr


def q3_implementing_repo(tmp_path: Path, *, terminal: bool) -> Path:
    repo = q3_entry_repo(tmp_path)
    task_path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "IMPLEMENTING"
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    impact_path = repo / ".harness/impact.yaml"
    impact = yaml.safe_load(impact_path.read_text())
    impact["impact"]["required_tests"] = ["tests/test_test_plan_transition.py"]
    impact_path.write_text(yaml.safe_dump(impact, sort_keys=False))
    begin = {
        "sequence": 1,
        "item": "P-001",
        "from": "PENDING",
        "to": "IN_PROGRESS",
        "action": "BEGIN",
    }
    if not terminal:
        write_entry_execution(
            repo,
            transitions=[begin],
            items={"P-001": {"status": "IN_PROGRESS"}},
        )
        return repo
    receipt = {
        "head": "a" * 40,
        "workspace": "sha256:" + "b" * 64,
        "evidence": [],
        "surface_refs": ["src/first.py"],
    }
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": [],
        "surface_refs": ["src/first.py"],
        "proof_receipt": receipt,
    }
    write_entry_execution(
        repo,
        transitions=[begin, complete],
        items={
            "P-001": {"status": "COMPLETE", "surface_refs": ["src/first.py"]}
        },
    )
    return repo


def test_q3_verification_entry_accepts_terminal_history_with_stale_proof(tmp_path):
    repo = q3_implementing_repo(tmp_path, terminal=True)

    result = cli(repo, "transition", "VERIFYING")

    assert result.returncode == 0, result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["state"] == "VERIFYING"


def test_q3_verification_entry_rejects_active_item_without_state_change(tmp_path):
    repo = q3_implementing_repo(tmp_path, terminal=False)

    result = cli(repo, "transition", "VERIFYING")

    assert result.returncode == 1
    assert "PLAN_ITEM_UNRECONCILED" in result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["state"] == "IMPLEMENTING"


@pytest.mark.parametrize(
    ("kind", "ref", "reason_code"),
    [
        ("permission", "DEC-001", "SCOPE_DRIFT_PERMISSION"),
        ("persistence", "INT-001", "SCOPE_DRIFT_PERSISTENCE"),
    ],
)
def test_standard_entry_seals_typed_boundary_and_removal_drifts(
    tmp_path, kind, ref, reason_code
):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    write_plan_artifacts(repo)
    impact_path = repo / ".harness/impact.yaml"
    impact_path.write_text(yaml.safe_dump({"impact": {"contracts": [{"ref": ref, "kind": kind}], "required_tests": ["tests/test_test_plan_transition.py"]}}))

    assert cli(repo, "transition", "IMPLEMENTING").returncode == 0
    sealed = yaml.safe_load((repo / ".harness/alignment-freeze.yaml").read_text())
    assert sealed["boundary_refs"][kind] == [ref]

    impact_path.write_text(yaml.safe_dump({"impact": {"contracts": [], "required_tests": ["tests/test_test_plan_transition.py"]}}))
    result = cli(repo, "transition", "VERIFYING")

    assert result.returncode == 1
    assert "SCOPE_DRIFT" in result.stderr
    finding = yaml.safe_load(next((repo / ".harness/findings").glob("FND-*.yaml")).read_text())
    assert finding["reason_code"] == reason_code
    assert finding["boundary_ref"] == ref


def test_standard_planned_to_implementing_rejects_unfrozen_alignment(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in result.stderr
    assert "ALIGNMENT_FREEZE_INVALID" in result.stderr
    assert "POLICY: USER_AUTHORITY_REQUIRED" not in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" not in result.stderr


def test_standard_entry_live_contract_change_halts(tmp_path):
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)
    write_alignment(repo, frozen=True)
    from harness.alignment import contract_hash, validate_sealed_freeze

    harness = repo / ".harness"
    document = yaml.safe_load((harness / "alignment.yaml").read_text())
    validate_sealed_freeze(
        harness,
        document,
        decisions=[],
        boundary_refs={"interface": [], "permission": [], "persistence": []},
    )
    document["goal"]["summary"] = "rewritten after the seal"
    document["freeze"]["contract_hash"] = contract_hash(document)
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "POLICY: USER_AUTHORITY_REQUIRED" in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in result.stderr
    assert "CONTRACT_CHANGED" in result.stderr
    assert "STATUS: REJECTED" not in result.stderr
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["state"] == "PLANNED"


def test_fast_entry_creates_lightweight_alignment(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    flags = [value for name, setting in SAFE.items() for value in (f"--{name}", setting)]
    assert cli(tmp_path, "task", "classify", "--level", "Q1", *flags).returncode == 0
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-001"
    task_path.write_text(yaml.safe_dump(task))

    result = cli(tmp_path, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr
    draft = yaml.safe_load((tmp_path / ".harness/alignment.yaml").read_text())
    assert draft["freeze"]["frozen"] is False
    assert draft["acceptance_criteria"]
    assert draft["verification"]


def test_fast_entry_rejects_proposed_decision(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    flags = [value for name, setting in SAFE.items() for value in (f"--{name}", setting)]
    assert cli(tmp_path, "task", "classify", "--level", "Q1", *flags).returncode == 0
    task = yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())
    task["task"]["id"] = "TASK-001"
    (tmp_path / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    assert cli(tmp_path, "decision", "propose", "--topic", "scope", "--question", "choose", "--context", "x", "--option", "a=A", "--recommend", "a", "--reason", "x").returncode == 0

    result = cli(tmp_path, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "OPEN_DECISION" in result.stderr


def test_fast_classified_to_implementing_does_not_load_test_plan(tmp_path):
    """Break caught: v0.2.4 adds STANDARD ceremony to FAST path."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    flags = [
        value for name, setting in SAFE.items() for value in (f"--{name}", setting)
    ]
    assert cli(tmp_path, "task", "classify", "--level", "Q1", *flags).returncode == 0

    result = cli(tmp_path, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr
