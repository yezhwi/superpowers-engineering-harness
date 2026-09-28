"""Locked task-level Plan mutation domain tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def task(*, profile: str = "STRICT", mode: str = "task_and_final", state: str = "IMPLEMENTING") -> dict:
    return {
        "task": {"id": "TASK-062"},
        "state": state,
        "risk": {
            "profile": profile,
            "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
        },
        "git": {"base_commit": "HEAD"},
        "plan_reconciliation": {"enabled": True, "mode": mode},
    }


def plan() -> dict:
    return {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "first", "surfaces": ["src/first.py"]},
            {"id": "P-002", "intent": "second", "surfaces": ["src/second.py"]},
        ],
    }


def write_v2(harness_dir: Path, *, stale: bool = False) -> tuple[dict, dict]:
    from harness.plan_reconciliation import plan_fingerprint

    document = plan()
    execution = {
        "version": 2,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": "sha256:" + "0" * 64 if stale else plan_fingerprint(document),
        },
        "sequence": 0,
        "transitions": [],
        "items": {},
    }
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
    (harness_dir / "plan-execution.yaml").write_text(
        yaml.safe_dump(execution, sort_keys=False)
    )
    return document, execution


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    "configured",
    [
        {**task(), "plan_reconciliation": {"enabled": False}},
        task(profile="FAST"),
        task(profile="STANDARD", mode="final"),
    ],
)
def test_plan_mutation_policy_rejects_disabled_profiles_before_plan_reads(
    tmp_path, configured
):
    from harness.plan_reconciliation import (
        PlanMutationError,
        PlanMutationRequest,
        mutate_plan_execution,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "plan.yaml").write_text("[")
    (harness_dir / "plan-execution.yaml").write_text("[")
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_TASK_LEVEL_DISABLED"):
        mutate_plan_execution(
            harness_dir, configured, PlanMutationRequest(action="BEGIN", item_id="P-001")
        )

    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize(
    ("request_data", "state"),
    [
        ({"action": "BEGIN", "item_id": "P-001"}, "PLANNED"),
        ({"action": "BLOCK", "item_id": "P-001", "reason": "wait"}, "VERIFYING"),
        ({"action": "RESUME", "item_id": "P-001"}, "VERIFYING"),
        ({"action": "RECONCILE", "item_id": "P-001", "disposition": "SKIPPED", "reason": "gone", "decision_id": "DEC-001"}, "VERIFYING"),
        ({"action": "REFRESH_PROOF", "item_id": "P-001"}, "REVIEWING"),
        ({"action": "UPGRADE_EXECUTION"}, "GATING"),
    ],
)
def test_plan_mutation_policy_rejects_unsupported_state_before_plan_reads(
    tmp_path, request_data, state
):
    from harness.plan_reconciliation import (
        PlanMutationError,
        PlanMutationRequest,
        mutate_plan_execution,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "plan.yaml").write_text("[")
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_MUTATION_NOT_ALLOWED"):
        mutate_plan_execution(
            harness_dir, task(state=state), PlanMutationRequest(**request_data)
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_policy_reports_missing_artifacts_without_writes(tmp_path):
    from harness.plan_reconciliation import (
        PlanMutationError,
        PlanMutationRequest,
        mutate_plan_execution,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_REQUIRED"):
        mutate_plan_execution(
            harness_dir, task(), PlanMutationRequest(action="BEGIN", item_id="P-001")
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_policy_reports_stale_artifacts_without_writes(tmp_path):
    from harness.plan_reconciliation import (
        PlanMutationError,
        PlanMutationRequest,
        mutate_plan_execution,
    )

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir, stale=True)
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_STALE"):
        mutate_plan_execution(
            harness_dir, task(), PlanMutationRequest(action="BEGIN", item_id="P-001")
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_policy_keeps_malformed_present_source_as_invalid_state(tmp_path):
    from harness.plan_reconciliation import (
        PlanArtifactError,
        PlanMutationRequest,
        mutate_plan_execution,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "plan.yaml").write_text("[")
    (harness_dir / "plan-execution.yaml").write_text("version: 2")
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanArtifactError, match="PLAN_SCHEMA_INVALID"):
        mutate_plan_execution(
            harness_dir, task(), PlanMutationRequest(action="BEGIN", item_id="P-001")
        )

    assert tree_bytes(tmp_path) == before


def request(**values):
    from harness.plan_reconciliation import PlanMutationRequest

    return PlanMutationRequest(**values)


def mutate(harness_dir: Path, request_value, *, task_value: dict | None = None) -> bool:
    from harness.plan_reconciliation import mutate_plan_execution

    return mutate_plan_execution(harness_dir, task_value or task(), request_value)


def read_execution(harness_dir: Path) -> dict:
    return yaml.safe_load((harness_dir / "plan-execution.yaml").read_text())


def test_plan_mutation_begin_commits_canonical_next_item_and_exact_retry_is_noop(tmp_path):
    from harness.plan_execution import replay_plan_execution

    harness_dir = tmp_path / ".harness"
    document, _ = write_v2(harness_dir)
    begin = request(action="BEGIN", item_id="P-001")

    assert mutate(harness_dir, begin) is True
    committed = (harness_dir / "plan-execution.yaml").read_bytes()
    assert mutate(harness_dir, begin) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == committed

    execution = read_execution(harness_dir)
    assert execution["sequence"] == 1
    assert execution["items"] == {"P-001": {"status": "IN_PROGRESS"}}
    assert replay_plan_execution(document, execution).issues == ()


def test_plan_mutation_begin_rejects_non_next_or_second_active_item_without_writes(tmp_path):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_SEQUENCE_INVALID"):
        mutate(harness_dir, request(action="BEGIN", item_id="P-002"))
    assert tree_bytes(tmp_path) == before

    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    active = tree_bytes(tmp_path)
    with pytest.raises(PlanMutationError, match="PLAN_SEQUENCE_INVALID"):
        mutate(harness_dir, request(action="BEGIN", item_id="P-002"))
    assert tree_bytes(tmp_path) == active


def test_plan_mutation_block_and_resume_project_item_local_state_with_exact_retries(tmp_path):
    harness_dir = tmp_path / ".harness"
    document, _ = write_v2(harness_dir)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    block = request(action="BLOCK", item_id="P-001", reason="waiting")

    assert mutate(harness_dir, block) is True
    blocked_bytes = (harness_dir / "plan-execution.yaml").read_bytes()
    assert read_execution(harness_dir)["items"] == {
        "P-001": {"status": "BLOCKED", "reason": "waiting"}
    }
    assert mutate(harness_dir, block) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == blocked_bytes

    resume = request(action="RESUME", item_id="P-001")
    assert mutate(harness_dir, resume) is True
    resumed_bytes = (harness_dir / "plan-execution.yaml").read_bytes()
    execution = read_execution(harness_dir)
    assert execution["items"] == {"P-001": {"status": "IN_PROGRESS"}}
    assert execution["sequence"] == 3
    assert mutate(harness_dir, resume) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == resumed_bytes

    from harness.plan_execution import replay_plan_execution

    assert replay_plan_execution(document, execution).issues == ()


def test_plan_mutation_block_conflicting_reason_and_late_resume_write_nothing(tmp_path):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    mutate(
        harness_dir,
        request(action="BLOCK", item_id="P-001", reason="first reason"),
    )
    blocked = tree_bytes(tmp_path)
    with pytest.raises(PlanMutationError, match="PLAN_SEQUENCE_INVALID"):
        mutate(
            harness_dir,
            request(action="BLOCK", item_id="P-001", reason="different reason"),
        )
    assert tree_bytes(tmp_path) == blocked

    mutate(harness_dir, request(action="RESUME", item_id="P-001"))
    mutate(
        harness_dir,
        request(action="BLOCK", item_id="P-001", reason="second block"),
    )
    later = tree_bytes(tmp_path)
    with pytest.raises(PlanMutationError, match="PLAN_SEQUENCE_INVALID"):
        mutate(harness_dir, request(action="RESUME", item_id="P-002"))
    assert tree_bytes(tmp_path) == later


def test_plan_mutation_block_rejects_blank_reason_without_writes(tmp_path):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
        mutate(harness_dir, request(action="BLOCK", item_id="P-001", reason="  "))

    assert tree_bytes(tmp_path) == before


def write_decision(
    harness_dir: Path,
    *,
    decision_id: str = "DEC-031",
    task_id: str = "TASK-062",
    status: str = "ACCEPTED",
) -> bytes:
    selected = (
        {"option": "accept", "source": "accepted_recommendation", "decided_by": "user"}
        if status == "ACCEPTED"
        else None
    )
    record = {
        "id": decision_id,
        "task_id": task_id,
        "status": status,
        "topic": "plan disposition",
        "question": "accept item disposition?",
        "context": ["task-level reconciliation"],
        "options": [{"id": "accept", "description": "accept disposition"}],
        "recommendation": {
            "option": "accept",
            "reasons": ["matches contract"],
            "tradeoffs": [],
        },
        "selected": selected,
        "scope": ["P-001"],
        "constraints": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "accepted_at": "2026-01-01T00:00:00+00:00" if status == "ACCEPTED" else None,
        "supersedes": None,
        "superseded_by": None,
    }
    directory = harness_dir / "decisions"
    directory.mkdir(exist_ok=True)
    content = yaml.safe_dump(record, sort_keys=False).encode()
    (directory / f"{decision_id}.yaml").write_bytes(content)
    return content


def stable_workspace(monkeypatch, *, head: str = "head", fingerprint: str | None = None):
    from types import SimpleNamespace

    from harness import plan_reconciliation

    value = fingerprint or "sha256:" + "f" * 64
    monkeypatch.setattr(
        plan_reconciliation,
        "workspace_snapshot",
        lambda root=None: SimpleNamespace(head=head, fingerprint=value),
    )
    return value


def test_plan_mutation_reconcile_skip_requires_accepted_current_task_decision_and_retries(
    tmp_path
):
    import hashlib

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    decision_bytes = write_decision(harness_dir)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    reconcile = request(
        action="RECONCILE",
        item_id="P-001",
        disposition="SKIPPED",
        reason="requirement removed",
        decision_id="DEC-031",
    )

    assert mutate(harness_dir, reconcile) is True
    committed = (harness_dir / "plan-execution.yaml").read_bytes()
    assert mutate(harness_dir, reconcile) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == committed
    transition = read_execution(harness_dir)["transitions"][-1]
    assert transition["decision_receipt"] == {
        "decision_id": "DEC-031",
        "sha256": "sha256:" + hashlib.sha256(decision_bytes).hexdigest(),
        "task_id": "TASK-062",
        "status": "ACCEPTED",
    }


@pytest.mark.parametrize(
    ("decision_task", "status"),
    [("TASK-999", "ACCEPTED"), ("TASK-062", "PROPOSED")],
)
def test_plan_mutation_reconcile_skip_rejects_cross_task_or_unaccepted_decision(
    tmp_path, decision_task, status
):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    write_decision(harness_dir, task_id=decision_task, status=status)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE",
                item_id="P-001",
                disposition="SKIPPED",
                reason="removed",
                decision_id="DEC-031",
            ),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_supersede_normalizes_replacements_and_rejects_unknown_self_cycle(
    tmp_path
):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    write_decision(harness_dir)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))

    before = tree_bytes(tmp_path)
    for replacements in (("P-999",), ("P-001",)):
        with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
            mutate(
                harness_dir,
                request(
                    action="RECONCILE",
                    item_id="P-001",
                    disposition="SUPERSEDED",
                    reason="split",
                    decision_id="DEC-031",
                    replacements=replacements,
                ),
            )
        assert tree_bytes(tmp_path) == before

    assert mutate(
        harness_dir,
        request(
            action="RECONCILE",
            item_id="P-001",
            disposition="SUPERSEDED",
            reason="split",
            decision_id="DEC-031",
            replacements=("P-002", "P-002"),
        ),
    ) is True
    assert read_execution(harness_dir)["items"]["P-001"]["superseded_by"] == [
        "P-002"
    ]

    mutate(harness_dir, request(action="BEGIN", item_id="P-002"))
    cycle_before = tree_bytes(tmp_path)
    with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE",
                item_id="P-002",
                disposition="SUPERSEDED",
                reason="cycle",
                decision_id="DEC-031",
                replacements=("P-001",),
            ),
        )
    assert tree_bytes(tmp_path) == cycle_before


def test_plan_mutation_complete_and_refresh_proof_use_current_workspace_receipts(
    tmp_path, monkeypatch
):
    from harness import plan_reconciliation
    from harness.plan_execution import replay_plan_execution

    harness_dir = tmp_path / ".harness"
    document, _ = write_v2(harness_dir)
    workspace = stable_workspace(monkeypatch)
    monkeypatch.setattr(
        plan_reconciliation, "changed_paths_since", lambda base: ("src/first.py",)
    )
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    complete = request(
        action="RECONCILE",
        item_id="P-001",
        disposition="COMPLETE",
        surface_refs=("src/first.py", "src/first.py"),
    )

    assert mutate(harness_dir, complete) is True
    terminal_bytes = (harness_dir / "plan-execution.yaml").read_bytes()
    assert mutate(harness_dir, complete) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == terminal_bytes
    execution = read_execution(harness_dir)
    receipt = execution["transitions"][-1]["proof_receipt"]
    assert receipt == {
        "head": "head",
        "workspace": workspace,
        "evidence": [],
        "surface_refs": ["src/first.py"],
    }

    refresh = request(
        action="REFRESH_PROOF",
        item_id="P-001",
        surface_refs=("src/first.py",),
    )
    assert mutate(harness_dir, refresh, task_value=task(state="VERIFYING")) is True
    refreshed = (harness_dir / "plan-execution.yaml").read_bytes()
    assert mutate(harness_dir, refresh, task_value=task(state="VERIFYING")) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == refreshed
    execution = read_execution(harness_dir)
    assert execution["sequence"] == 3
    assert execution["items"]["P-001"] == {
        "status": "COMPLETE",
        "surface_refs": ["src/first.py"],
    }
    assert replay_plan_execution(document, execution).issues == ()


def test_plan_mutation_complete_rejects_missing_proof_branch_without_writes(
    tmp_path, monkeypatch
):
    from harness.plan_reconciliation import PlanMutationError, plan_fingerprint

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    document = {"version": 1, "items": [{"id": "P-001", "intent": "none"}]}
    execution = {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(document)},
        "sequence": 0,
        "transitions": [],
        "items": {},
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    stable_workspace(monkeypatch)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE", item_id="P-001", disposition="COMPLETE"
            ),
        )

    assert tree_bytes(tmp_path) == before


def write_test_proof_harness(harness_dir: Path, monkeypatch) -> tuple[dict, str]:
    import json

    from harness.plan_reconciliation import plan_fingerprint

    document = {
        "version": 1,
        "items": [
            {
                "id": "P-001",
                "intent": "test",
                "test_case_refs": ["REQ-001/TC-001"],
            }
        ],
    }
    execution = {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(document)},
        "sequence": 0,
        "transitions": [],
        "items": {},
    }
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    requirements = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "pending",
                "evidence": [],
                "test_plan": {
                    "strategies": ["manual"],
                    "cases": [
                        {
                            "id": "TC-001",
                            "type": "happy_path",
                            "strategy": "manual",
                            "description": "manual proof",
                            "tests": [],
                        }
                    ],
                },
            }
        ]
    }
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    (harness_dir / "invariants.yaml").write_text("invariants: []\n")
    workspace = stable_workspace(monkeypatch)
    evidence = {
        "type": "unit_test",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "command": "pytest tests/test_plan_mutation.py",
        "exit_code": 0,
        "commit": "head",
        "workspace_fingerprint": workspace,
        "workspace_fingerprint_after": workspace,
        "covered_test_cases": ["TC-001"],
    }
    evidence_dir = harness_dir / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "unit.json").write_text(json.dumps(evidence))
    return document, workspace


def test_plan_mutation_evidence_receipt_tracks_exact_bytes_and_refreshes_overwrite(
    tmp_path, monkeypatch
):
    import hashlib
    import json

    harness_dir = tmp_path / ".harness"
    write_test_proof_harness(harness_dir, monkeypatch)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    complete = request(
        action="RECONCILE",
        item_id="P-001",
        disposition="COMPLETE",
        evidence_refs=("unit", "unit"),
    )

    assert mutate(harness_dir, complete) is True
    evidence_path = harness_dir / "evidence" / "unit.json"
    original_digest = "sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    entry = read_execution(harness_dir)["transitions"][-1]["proof_receipt"]["evidence"][0]
    assert entry["ref"] == "unit"
    assert entry["sha256"] == original_digest
    assert entry["type"] == "unit_test"
    assert entry["exit_code"] == 0
    assert entry["commit"] == "head"

    record = json.loads(evidence_path.read_text())
    evidence_path.write_text(json.dumps(record, indent=2))
    changed_digest = "sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    assert changed_digest != original_digest
    before_conflict = tree_bytes(tmp_path)
    from harness.plan_reconciliation import PlanMutationError

    with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
        mutate(harness_dir, complete)
    assert tree_bytes(tmp_path) == before_conflict

    refresh = request(
        action="REFRESH_PROOF", item_id="P-001", evidence_refs=("unit",)
    )
    assert mutate(harness_dir, refresh, task_value=task(state="VERIFYING")) is True
    refreshed = read_execution(harness_dir)["transitions"][-1]
    assert refreshed["proof_receipt"]["evidence"][0]["sha256"] == changed_digest


def test_plan_mutation_workspace_race_aborts_without_write(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from harness import plan_reconciliation
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_test_proof_harness(harness_dir, monkeypatch)
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    before = tree_bytes(tmp_path)
    snapshots = iter(
        [
            SimpleNamespace(head="head", fingerprint="sha256:" + "f" * 64),
            SimpleNamespace(head="head", fingerprint="sha256:" + "e" * 64),
        ]
    )
    monkeypatch.setattr(plan_reconciliation, "workspace_snapshot", lambda root=None: next(snapshots))

    with pytest.raises(PlanMutationError, match="PLAN_PROOF_MISSING"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE",
                item_id="P-001",
                disposition="COMPLETE",
                evidence_refs=("unit",),
            ),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_atomic_write_failure_preserves_execution(tmp_path, monkeypatch):
    from harness import plan_reconciliation

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    before = tree_bytes(tmp_path)

    def fail(path, content):
        raise OSError("publish failed")

    monkeypatch.setattr(plan_reconciliation, "atomic_write", fail)
    with pytest.raises(OSError, match="publish failed"):
        mutate(harness_dir, request(action="BEGIN", item_id="P-001"))

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_concurrent_exact_begin_has_one_commit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    begin = request(action="BEGIN", item_id="P-001")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: mutate(harness_dir, begin), range(2)))

    assert sorted(results) == [False, True]
    execution = read_execution(harness_dir)
    assert execution["sequence"] == 1
    assert len(execution["transitions"]) == 1


def write_v1(harness_dir: Path, statuses: dict[str, str], *, stale: bool = False):
    from harness.plan_reconciliation import plan_fingerprint

    document = plan()
    execution = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": "sha256:" + "0" * 64 if stale else plan_fingerprint(document),
        },
        "items": {key: {"status": value} for key, value in statuses.items()},
    }
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(document))
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))


@pytest.mark.parametrize("statuses", [{}, {"P-001": "PENDING"}, {"P-001": "PENDING", "P-002": "PENDING"}])
def test_plan_mutation_upgrade_all_pending_v1_to_empty_v2_without_history(tmp_path, statuses):
    harness_dir = tmp_path / ".harness"
    write_v1(harness_dir, statuses)
    upgrade = request(action="UPGRADE_EXECUTION")

    assert mutate(harness_dir, upgrade, task_value=task(state="PLANNED")) is True
    execution = read_execution(harness_dir)
    assert execution["version"] == 2
    assert execution["sequence"] == 0
    assert execution["transitions"] == []
    assert execution["items"] == {}
    committed = (harness_dir / "plan-execution.yaml").read_bytes()
    assert mutate(harness_dir, upgrade, task_value=task(state="PLANNED")) is False
    assert (harness_dir / "plan-execution.yaml").read_bytes() == committed


@pytest.mark.parametrize("status", ["IN_PROGRESS", "BLOCKED", "COMPLETE", "SKIPPED", "SUPERSEDED"])
def test_plan_mutation_upgrade_refuses_progressed_v1_without_synthetic_history(tmp_path, status):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v1(harness_dir, {"P-001": status})
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_TASK_LEVEL_REQUIRED"):
        mutate(
            harness_dir,
            request(action="UPGRADE_EXECUTION"),
            task_value=task(state="SPECIFYING"),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_malformed_decision_source_fails_as_invalid_harness_state(tmp_path):
    from harness.decision import DecisionError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    decisions = harness_dir / "decisions"
    decisions.mkdir()
    (decisions / "DEC-031.yaml").write_text("[")
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    before = tree_bytes(tmp_path)

    with pytest.raises(DecisionError, match="DECISION_RECORD_INVALID"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE",
                item_id="P-001",
                disposition="SKIPPED",
                reason="removed",
                decision_id="DEC-031",
            ),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_malformed_evidence_source_fails_as_invalid_harness_state(
    tmp_path, monkeypatch
):
    from harness.plan_reconciliation import PlanArtifactError

    harness_dir = tmp_path / ".harness"
    write_test_proof_harness(harness_dir, monkeypatch)
    (harness_dir / "evidence" / "unit.json").write_text("{")
    mutate(harness_dir, request(action="BEGIN", item_id="P-001"))
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanArtifactError, match="PLAN_SOURCE_INVALID"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE",
                item_id="P-001",
                disposition="COMPLETE",
                evidence_refs=("unit",),
            ),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_upgrade_rejects_unknown_pending_v1_item(tmp_path):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v1(harness_dir, {"P-999": "PENDING"})
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_DISPOSITION_INVALID"):
        mutate(
            harness_dir,
            request(action="UPGRADE_EXECUTION"),
            task_value=task(state="PLANNED"),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_refresh_rejects_noncomplete_item_without_write(
    tmp_path, monkeypatch
):
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    stable_workspace(monkeypatch)
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_SEQUENCE_INVALID"):
        mutate(
            harness_dir,
            request(
                action="REFRESH_PROOF",
                item_id="P-001",
                surface_refs=("src/first.py",),
            ),
        )

    assert tree_bytes(tmp_path) == before


def test_plan_mutation_complete_rejects_modified_protected_surface_without_write(
    tmp_path, monkeypatch
):
    from harness import plan_reconciliation
    from harness.plan_reconciliation import PlanMutationError

    harness_dir = tmp_path / ".harness"
    write_v2(harness_dir)
    stable_workspace(monkeypatch)
    monkeypatch.setattr(
        plan_reconciliation, "changed_paths_since", lambda base: ("src/first.py",)
    )
    monkeypatch.setattr(
        plan_reconciliation, "protected_paths_fingerprint", lambda paths: "changed"
    )
    protected_task = task()
    protected_task["risk"]["user_changes"] = {
        "paths": ["src/first.py"],
        "fingerprint": "stored",
    }
    mutate(
        harness_dir,
        request(action="BEGIN", item_id="P-001"),
        task_value=protected_task,
    )
    before = tree_bytes(tmp_path)

    with pytest.raises(PlanMutationError, match="PLAN_PROTECTED_PATHS_MODIFIED"):
        mutate(
            harness_dir,
            request(
                action="RECONCILE",
                item_id="P-001",
                disposition="COMPLETE",
                surface_refs=("src/first.py",),
            ),
            task_value=protected_task,
        )

    assert tree_bytes(tmp_path) == before


def verification_plan() -> dict:
    return {
        "version": 1,
        "items": [{"id": "P-001", "intent": "first", "surfaces": ["src/first.py"]}],
    }


def complete_execution(document: dict) -> dict:
    from harness.plan_reconciliation import plan_fingerprint

    receipt = {
        "head": "a" * 40,
        "workspace": "sha256:" + "b" * 64,
        "evidence": [],
        "surface_refs": ["src/first.py"],
    }
    return {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(document)},
        "sequence": 2,
        "transitions": [
            {"sequence": 1, "item": "P-001", "from": "PENDING", "to": "IN_PROGRESS", "action": "BEGIN"},
            {
                "sequence": 2,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "COMPLETE",
                "action": "RECONCILE",
                "evidence_refs": [],
                "surface_refs": ["src/first.py"],
                "proof_receipt": receipt,
            },
        ],
        "items": {"P-001": {"status": "COMPLETE", "surface_refs": ["src/first.py"]}},
    }


def test_plan_verification_entry_accepts_terminal_history_without_current_proof_reads(
    tmp_path, monkeypatch
):
    from harness import plan_reconciliation
    from harness.plan_reconciliation import assess_plan_verification_entry_documents

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    document = verification_plan()
    execution = complete_execution(document)
    monkeypatch.setattr(
        plan_reconciliation,
        "workspace_snapshot",
        lambda *args, **kwargs: pytest.fail("verification entry read current workspace"),
    )
    monkeypatch.setattr(
        plan_reconciliation,
        "changed_paths_since",
        lambda *args, **kwargs: pytest.fail("verification entry checked current surfaces"),
    )

    blockers = assess_plan_verification_entry_documents(
        harness_dir, task(), document, execution
    )

    assert blockers == []


def test_plan_verification_entry_rejects_nonterminal_and_invalid_replay(tmp_path):
    from harness.plan_reconciliation import assess_plan_verification_entry_documents

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    document = verification_plan()
    nonterminal = complete_execution(document)
    nonterminal["sequence"] = 1
    nonterminal["transitions"] = nonterminal["transitions"][:1]
    nonterminal["items"] = {"P-001": {"status": "IN_PROGRESS"}}
    invalid = complete_execution(document)
    invalid["transitions"][1] = {**invalid["transitions"][0], "sequence": 2}
    invalid["items"] = {"P-001": {"status": "IN_PROGRESS"}}

    nonterminal_blockers = assess_plan_verification_entry_documents(
        harness_dir, task(), document, nonterminal
    )
    invalid_blockers = assess_plan_verification_entry_documents(
        harness_dir, task(), document, invalid
    )

    assert [blocker.code for blocker in nonterminal_blockers] == [
        "PLAN_ITEM_UNRECONCILED"
    ]
    assert [blocker.code for blocker in invalid_blockers] == ["PLAN_SEQUENCE_INVALID"]


def test_plan_verification_entry_rejects_decision_no_longer_accepted(tmp_path):
    import hashlib

    from harness.plan_reconciliation import (
        assess_plan_verification_entry_documents,
        plan_fingerprint,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    document = verification_plan()
    decision_bytes = write_decision(harness_dir, status="REJECTED")
    receipt = {
        "decision_id": "DEC-031",
        "sha256": "sha256:" + hashlib.sha256(decision_bytes).hexdigest(),
        "task_id": "TASK-062",
        "status": "ACCEPTED",
    }
    execution = {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(document)},
        "sequence": 2,
        "transitions": [
            {"sequence": 1, "item": "P-001", "from": "PENDING", "to": "IN_PROGRESS", "action": "BEGIN"},
            {
                "sequence": 2,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "SKIPPED",
                "action": "RECONCILE",
                "reason": "removed",
                "decision_id": "DEC-031",
                "decision_receipt": receipt,
            },
        ],
        "items": {"P-001": {"status": "SKIPPED", "reason": "removed", "decision_id": "DEC-031"}},
    }

    blockers = assess_plan_verification_entry_documents(
        harness_dir, task(), document, execution
    )

    assert [blocker.code for blocker in blockers] == ["PLAN_DISPOSITION_INVALID"]
