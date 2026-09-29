"""Read-only ``harness plan status`` CLI contract tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml

REPO = Path(__file__).resolve().parents[1]
harness = test_context_builder.harness


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


def repository_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def test_plan_status_parser_requires_known_subcommand(harness):
    missing = cli(harness.parent, "plan")
    unknown = cli(harness.parent, "plan", "unknown")

    assert missing.returncode == 2
    assert unknown.returncode == 2
    assert missing.stdout == unknown.stdout == ""


def test_plan_status_disabled_json_is_exact_and_read_only(harness):
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")
    human = cli(harness.parent, "plan", "status")

    assert result.returncode == human.returncode == 0, result.stderr + human.stderr
    assert json.loads(result.stdout) == {"enabled": False}
    assert result.stdout == '{\n  "enabled": false\n}\n'
    assert human.stdout == "Plan Execution\n\nStatus: disabled\n"
    assert repository_bytes(harness.parent) == before


def test_plan_status_verbose_parser_accepts_text_and_json(harness):
    text = cli(harness.parent, "plan", "status", "--verbose")
    machine = cli(harness.parent, "plan", "status", "--json", "--verbose")

    assert text.returncode == machine.returncode == 0
    assert text.stdout == "Plan Execution\n\nStatus: disabled\n"
    assert json.loads(machine.stdout) == {"enabled": False, "items": []}


def test_plan_status_fast_ad_hoc_enablement_ignores_malformed_artifacts(harness):
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    (harness / "plan.yaml").write_text("items: [")
    (harness / "plan-execution.yaml").write_text("items: [")
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"enabled": False}
    assert repository_bytes(harness.parent) == before


def enable_plan_status(harness: Path) -> dict:
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["level"] = "Q2"
    task["risk"]["profile"] = "STANDARD"
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    return task


def write_plan_artifacts(harness: Path, *, stale: bool = False) -> tuple[dict, dict]:
    from harness.plan_reconciliation import plan_fingerprint

    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    execution = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": (
                "sha256:" + "0" * 64 if stale else plan_fingerprint(plan)
            ),
        },
        "items": {"P-001": {"status": "PENDING"}},
    }
    (harness / "plan.yaml").write_text(yaml.safe_dump(plan))
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    return plan, execution


@pytest.mark.parametrize("missing", ["both", "plan", "execution"])
def test_plan_status_enabled_missing_artifacts_are_blocked_reports(harness, missing):
    enable_plan_status(harness)
    if missing != "both":
        write_plan_artifacts(harness)
        (harness / f"{'plan' if missing == 'plan' else 'plan-execution'}.yaml").unlink()
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")
    human = cli(harness.parent, "plan", "status")

    assert result.returncode == human.returncode == 0, result.stderr + human.stderr
    report = json.loads(result.stdout)
    plan_present = missing not in {"both", "plan"}
    execution_present = missing not in {"both", "execution"}
    assert report["plan"]["present"] is plan_present
    assert report["plan"]["execution_present"] is execution_present
    assert report["plan"]["fingerprint_fresh"] is None
    assert report["progress"] is None
    assert report["next_plan_item"] is None
    assert report["final_status"] == "blocked"
    assert [row["code"] for row in report["blockers"]] == ["PLAN_REQUIRED"]
    assert (
        f"Artifacts: plan {'present' if plan_present else 'missing'}, "
        f"execution {'present' if execution_present else 'missing'}, "
        "fingerprint unavailable"
    ) in human.stdout
    assert "Progress: unavailable" in human.stdout
    assert "Next: -" in human.stdout
    assert "  PLAN_REQUIRED enabled task requires plan artifacts" in human.stdout
    assert repository_bytes(harness.parent) == before


@pytest.mark.parametrize(
    ("version", "expected"),
    [(1, "PLAN_TASK_LEVEL_REQUIRED"), (2, "PLAN_SEQUENCE_INVALID")],
)
def test_plan_status_untrusted_task_level_execution_hides_progress_and_final_truth(
    harness, version, expected
):
    from harness.plan_reconciliation import plan_fingerprint

    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["level"] = "Q3"
    task["risk"]["profile"] = "STRICT"
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {"version": 1, "items": []}
    execution = {
        "version": version,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": {},
    }
    if version == 2:
        execution.update({"sequence": 1, "transitions": []})
    (harness / "plan.yaml").write_text(yaml.safe_dump(plan))
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert [blocker["code"] for blocker in report["blockers"]] == [expected]
    assert report["progress"] is None
    assert report["next_plan_item"] is None
    assert report["final_status"] == "pass"
    for secret in ("transitions", "sequence", "proof_receipt", "decision_receipt"):
        assert secret not in result.stdout
    assert repository_bytes(harness.parent) == before


def test_plan_status_trusted_v2_progress_comes_from_replay_projection(harness):
    from harness.plan_reconciliation import plan_fingerprint

    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["level"] = "Q3"
    task["risk"]["profile"] = "STRICT"
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "first"},
            {"id": "P-002", "intent": "second"},
        ],
    }
    execution = {
        "version": 2,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "sequence": 1,
        "transitions": [
            {
                "sequence": 1,
                "item": "P-001",
                "from": "PENDING",
                "to": "IN_PROGRESS",
                "action": "BEGIN",
            }
        ],
        "items": {"P-001": {"status": "IN_PROGRESS"}},
    }
    (harness / "plan.yaml").write_text(yaml.safe_dump(plan))
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["progress"]["statuses"]["IN_PROGRESS"] == 1
    assert report["progress"]["statuses"]["PENDING"] == 0
    assert report["next_plan_item"] == "P-001"
    assert "transitions" not in result.stdout


def test_plan_status_enabled_stale_artifacts_are_blocked_report(harness):
    enable_plan_status(harness)
    write_plan_artifacts(harness, stale=True)
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")
    human = cli(harness.parent, "plan", "status")

    assert result.returncode == human.returncode == 0, result.stderr + human.stderr
    report = json.loads(result.stdout)
    assert report["plan"]["fingerprint_fresh"] is False
    assert report["progress"] is None
    assert report["next_plan_item"] is None
    assert report["final_status"] == "blocked"
    assert [row["code"] for row in report["blockers"]] == ["PLAN_STALE"]
    assert "Artifacts: plan present, execution present, fingerprint stale" in human.stdout
    assert "Progress: unavailable" in human.stdout
    assert "Next: -" in human.stdout
    assert "  PLAN_STALE plan fingerprint does not match canonical plan" in human.stdout
    assert repository_bytes(harness.parent) == before


def test_plan_status_text_matches_fresh_blocked_json_facts(harness):
    enable_plan_status(harness)
    write_plan_artifacts(harness)
    before = repository_bytes(harness.parent)

    machine = cli(harness.parent, "plan", "status", "--json")
    human = cli(harness.parent, "plan", "status")

    assert machine.returncode == human.returncode == 0, machine.stderr + human.stderr
    report = json.loads(machine.stdout)
    assert report["mode"] == "final"
    assert report["progress"]["reconciled"] == 0
    assert report["next_plan_item"] == "P-001"
    assert report["final_status"] == "blocked"
    assert report["blockers"] == [
        {
            "code": "PLAN_ITEM_UNRECONCILED",
            "source": "P-001",
            "message": "plan item lacks terminal reconciliation",
        }
    ]
    assert human.stdout == (
        "Plan Execution\n\n"
        "Mode: final\n"
        "Artifacts: plan present, execution present, fingerprint fresh\n"
        "Progress: 0 / 1 reconciled\n\n"
        "COMPLETE       0\n"
        "SKIPPED        0\n"
        "SUPERSEDED     0\n"
        "PENDING        1\n"
        "IN_PROGRESS    0\n"
        "BLOCKED        0\n\n"
        "Next: P-001\n"
        "Final: BLOCKED\n\n"
        "Blockers:\n"
        "  PLAN_ITEM_UNRECONCILED [P-001] plan item lacks terminal reconciliation\n"
    )
    assert repository_bytes(harness.parent) == before


def test_plan_status_passing_text_omits_empty_blockers(harness):
    enable_plan_status(harness)
    _, execution = write_plan_artifacts(harness)
    execution["items"]["P-001"] = {"status": "SKIPPED", "reason": "not needed"}
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    before = repository_bytes(harness.parent)

    machine = cli(harness.parent, "plan", "status", "--json")
    human = cli(harness.parent, "plan", "status")

    assert machine.returncode == human.returncode == 0, machine.stderr + human.stderr
    report = json.loads(machine.stdout)
    assert report["final_status"] == "pass"
    assert report["blockers"] == []
    assert report["progress"]["reconciled"] == 1
    assert "Final: PASS" in human.stdout
    assert "Next: -" in human.stdout
    assert "Blockers:" not in human.stdout
    assert repository_bytes(harness.parent) == before


def test_plan_status_verbose_projects_body_free_item_rows(harness):
    from harness.plan_reconciliation import plan_fingerprint

    enable_plan_status(harness)
    plan = {
        "version": 1,
        "items": [
            {
                "id": "P-001",
                "intent": "SECRET-INTENT",
                "surfaces": ["src/example.py"],
            },
            {
                "id": "P-002",
                "intent": "SECRET-SECOND",
                "test_case_refs": ["REQ-001/TC-001"],
            },
        ],
    }
    execution = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": {
            "P-001": {"status": "COMPLETE"},
            "P-002": {"status": "SKIPPED", "reason": "SECRET-REASON"},
        },
    }
    (harness / "plan.yaml").write_text(yaml.safe_dump(plan))
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    machine = cli(harness.parent, "plan", "status", "--json", "--verbose")
    human = cli(harness.parent, "plan", "status", "--verbose")

    assert machine.returncode == human.returncode == 0, machine.stderr + human.stderr
    report = json.loads(machine.stdout)
    assert report["final_status"] == "blocked"
    assert report["items"] == [
        {
            "id": "P-001",
            "status": "COMPLETE",
            "proof_branch": "surfaces",
            "proof_health": "missing",
            "blockers": [
                {"code": "PLAN_PROOF_MISSING", "recovery": "VERIFYING"}
            ],
        },
        {
            "id": "P-002",
            "status": "SKIPPED",
            "proof_branch": "tests",
            "proof_health": "not_applicable",
            "blockers": [
                {"code": "PLAN_DISPOSITION_INVALID", "recovery": "IMPLEMENTING"}
            ],
        },
    ]
    assert "Items:\n  P-001 COMPLETE surfaces missing" in human.stdout
    assert "P-002 SKIPPED tests not_applicable" in human.stdout
    for secret in ("SECRET-INTENT", "SECRET-SECOND", "SECRET-REASON"):
        assert secret not in machine.stdout
        assert secret not in human.stdout


def test_plan_status_verbose_untrusted_rows_have_null_status(harness):
    enable_plan_status(harness)
    _plan, execution = write_plan_artifacts(harness, stale=True)
    execution["items"]["P-001"] = {"status": "COMPLETE"}
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    result = cli(harness.parent, "plan", "status", "--json", "--verbose")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["items"] == [
        {
            "id": "P-001",
            "status": None,
            "proof_branch": "none",
            "proof_health": "untrusted",
            "blockers": [],
        }
    ]


def test_plan_status_complete_with_failed_proof_stays_reconciled_and_blocked(harness):
    from harness.plan_reconciliation import plan_fingerprint

    enable_plan_status(harness)
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "work", "surfaces": ["src/example.py"]}
        ],
    }
    execution = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": {"P-001": {"status": "COMPLETE"}},
    }
    (harness / "plan.yaml").write_text(yaml.safe_dump(plan))
    (harness / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["progress"]["reconciled"] == 1
    assert report["progress"]["statuses"]["COMPLETE"] == 1
    assert report["final_status"] == "blocked"
    assert report["blockers"][0]["code"] == "PLAN_PROOF_MISSING"
    assert repository_bytes(harness.parent) == before


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        ("decisions/DEC-001.yaml", "["),
        ("requirements.yaml", "["),
        ("invariants.yaml", "requirements: []"),
    ],
)
def test_plan_status_enabled_malformed_required_source_fails_closed(
    harness, relative_path, content
):
    enable_plan_status(harness)
    write_plan_artifacts(harness)
    path = harness / relative_path
    path.parent.mkdir(exist_ok=True)
    path.write_text(content)
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert repository_bytes(harness.parent) == before


def test_plan_status_enabled_unreadable_required_source_fails_closed(harness):
    enable_plan_status(harness)
    write_plan_artifacts(harness)
    (harness / "requirements.yaml").unlink()
    (harness / "requirements.yaml").mkdir()
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert repository_bytes(harness.parent) == before


@pytest.mark.parametrize("name", ["plan.yaml", "plan-execution.yaml"])
def test_plan_status_enabled_malformed_artifact_fails_closed(harness, name):
    enable_plan_status(harness)
    write_plan_artifacts(harness)
    (harness / name).write_text("items: [")
    before = repository_bytes(harness.parent)

    result = cli(harness.parent, "plan", "status", "--json")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert repository_bytes(harness.parent) == before


def test_plan_status_repository_discovery_keeps_existing_error_contract(tmp_path):
    result = cli(tmp_path, "plan", "status", "--json")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR:")
