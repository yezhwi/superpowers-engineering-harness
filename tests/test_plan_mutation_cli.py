"""Public ``harness plan`` mutation command contract tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fixtures.harness import make_harness

REPO = Path(__file__).resolve().parents[1]


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "reconcile", "P-001"),
        (
            "plan",
            "reconcile",
            "P-001",
            "--complete",
            "--skipped",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
        ),
        ("plan", "reconcile", "P-001", "--complete", "--reason", "x"),
        ("plan", "reconcile", "P-001", "--complete", "--decision", "DEC-001"),
        ("plan", "reconcile", "P-001", "--complete", "--replacement", "P-002"),
        ("plan", "reconcile", "P-001", "--skipped", "--decision", "DEC-001"),
        ("plan", "reconcile", "P-001", "--skipped", "--reason", "x"),
        (
            "plan",
            "reconcile",
            "P-001",
            "--skipped",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
            "--surface",
            "src/x.py",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--superseded",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--superseded",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
            "--replacement",
            "P-002",
            "--evidence",
            "unit",
        ),
        ("plan", "begin", "P-001", "--reason", "x"),
        ("plan", "block", "P-001"),
        ("plan", "resume", "P-001", "--surface", "src/x.py"),
        ("plan", "refresh-proof", "P-001", "--reason", "x"),
        ("plan", "upgrade-execution", "P-001"),
    ],
)
def test_plan_mutation_parser_rejects_invalid_arguments(tmp_path, arguments):
    result = cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "begin", "P-001"),
        ("plan", "block", "P-001", "--reason", "waiting"),
        ("plan", "resume", "P-001"),
        (
            "plan",
            "reconcile",
            "P-001",
            "--complete",
            "--evidence",
            "unit-a",
            "--evidence",
            "unit-b",
            "--surface",
            "src/x.py",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--skipped",
            "--reason",
            "gone",
            "--decision",
            "DEC-001",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--superseded",
            "--reason",
            "split",
            "--decision",
            "DEC-001",
            "--replacement",
            "P-002",
        ),
        (
            "plan",
            "refresh-proof",
            "P-001",
            "--evidence",
            "unit",
            "--surface",
            "src/x.py",
        ),
        ("plan", "upgrade-execution"),
    ],
)
def test_plan_mutation_parser_accepts_valid_argument_shapes(tmp_path, arguments):
    result = cli(tmp_path, *arguments)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR:")
    assert "usage:" not in result.stderr


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def execution_bytes(root: Path) -> bytes:
    return (root / ".harness" / "plan-execution.yaml").read_bytes()


def mutation_repo(tmp_path: Path, *, stale: bool = False) -> Path:
    from harness.plan_reconciliation import plan_fingerprint

    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("fixture\n")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-qm", "fixture")
    head = git(tmp_path, "rev-parse", "HEAD")

    harness_dir = make_harness(tmp_path, state="IMPLEMENTING", risk="Q3")
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-062"
    task["git"] = {"head": head, "base_commit": head}
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    (harness_dir / "current-task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False)
    )
    plan = {
        "version": 1,
        "items": [{"id": "P-001", "intent": "first", "surfaces": ["src/first.py"]}],
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan, sort_keys=False))
    execution = {
        "version": 2,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": "sha256:" + "0" * 64 if stale else plan_fingerprint(plan),
        },
        "sequence": 0,
        "transitions": [],
        "items": {},
    }
    (harness_dir / "plan-execution.yaml").write_text(
        yaml.safe_dump(execution, sort_keys=False)
    )
    return harness_dir


def test_plan_mutation_cli_runs_lifecycle_and_exact_refresh_retry(tmp_path):
    harness_dir = mutation_repo(tmp_path)

    for arguments in (
        ("plan", "begin", "P-001"),
        ("plan", "block", "P-001", "--reason", "waiting"),
        ("plan", "resume", "P-001"),
    ):
        result = cli(tmp_path, *arguments)
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            "PLAN_EXECUTION_UPDATED\n",
            "",
        )

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "first.py").write_text("VALUE = 1\n")
    complete = cli(
        tmp_path,
        "plan",
        "reconcile",
        "P-001",
        "--complete",
        "--surface",
        "src/first.py",
    )
    refresh = cli(
        tmp_path,
        "plan",
        "refresh-proof",
        "P-001",
        "--surface",
        "src/first.py",
    )
    before_retry = execution_bytes(tmp_path)
    retry = cli(
        tmp_path,
        "plan",
        "refresh-proof",
        "P-001",
        "--surface",
        "src/first.py",
    )

    assert complete.returncode == refresh.returncode == retry.returncode == 0
    assert retry.stdout == "PLAN_EXECUTION_UNCHANGED\n"
    assert execution_bytes(tmp_path) == before_retry
    execution = yaml.safe_load(execution_bytes(tmp_path))
    assert [entry["action"] for entry in execution["transitions"]] == [
        "BEGIN",
        "BLOCK",
        "RESUME",
        "RECONCILE",
        "REFRESH_PROOF",
    ]
    assert execution["items"]["P-001"]["status"] == "COMPLETE"
    assert "proof_receipt" in execution["transitions"][-1]
    assert not (harness_dir / "plan-execution.yaml.tmp").exists()


def test_plan_mutation_cli_stale_plan_is_domain_refusal_without_write(tmp_path):
    mutation_repo(tmp_path, stale=True)
    before = execution_bytes(tmp_path)

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "PLAN_STALE\n",
    )
    assert execution_bytes(tmp_path) == before


def test_plan_mutation_cli_malformed_task_is_invalid_state_without_write(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    before = execution_bytes(tmp_path)
    (harness_dir / "current-task.yaml").write_text("[")

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert execution_bytes(tmp_path) == before


def test_plan_mutation_cli_malformed_plan_is_invalid_state_without_write(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    before = execution_bytes(tmp_path)
    (harness_dir / "plan.yaml").write_text("[")

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert execution_bytes(tmp_path) == before


def test_plan_mutation_cli_upgrades_all_pending_v1_and_retries_exactly(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    plan = yaml.safe_load((harness_dir / "plan.yaml").read_text())
    from harness.plan_reconciliation import plan_fingerprint

    legacy = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": {"P-001": {"status": "PENDING"}},
    }
    (harness_dir / "plan-execution.yaml").write_text(
        yaml.safe_dump(legacy, sort_keys=False)
    )

    upgraded = cli(tmp_path, "plan", "upgrade-execution")
    before_retry = execution_bytes(tmp_path)
    retry = cli(tmp_path, "plan", "upgrade-execution")

    assert (upgraded.returncode, upgraded.stdout, upgraded.stderr) == (
        0,
        "PLAN_EXECUTION_UPDATED\n",
        "",
    )
    assert (retry.returncode, retry.stdout, retry.stderr) == (
        0,
        "PLAN_EXECUTION_UNCHANGED\n",
        "",
    )
    assert execution_bytes(tmp_path) == before_retry
    assert yaml.safe_load(before_retry)["version"] == 2


@pytest.mark.parametrize(
    ("profile", "mode", "enabled"),
    [
        ("FAST", "task_and_final", True),
        ("STANDARD", "final", True),
        ("STRICT", "task_and_final", False),
    ],
)
def test_plan_mutation_cli_policy_refuses_before_malformed_plan_read(
    tmp_path, profile, mode, enabled
):
    harness_dir = mutation_repo(tmp_path)
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    task["risk"]["profile"] = profile
    task["risk"]["level"] = {"FAST": "Q1", "STANDARD": "Q2", "STRICT": "Q3"}[profile]
    task["plan_reconciliation"] = (
        {"enabled": enabled, "mode": mode} if enabled else {"enabled": False}
    )
    (harness_dir / "current-task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False)
    )
    (harness_dir / "plan.yaml").write_text("[")
    before = execution_bytes(tmp_path)

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "PLAN_TASK_LEVEL_DISABLED\n",
    )
    assert execution_bytes(tmp_path) == before
