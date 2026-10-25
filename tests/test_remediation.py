"""Operator remediation guidance contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )


def test_explain_plan_stale_offers_safe_next_step():
    result = cli("explain", "PLAN_STALE")

    assert result.returncode == 0
    assert "PLAN_STALE" in result.stdout
    assert "harness plan sync-fingerprint" in result.stdout
    assert "only when execution is empty" in result.stdout


def test_explain_authority_blocker_never_suggests_mutation():
    result = cli("explain", "CONTRACT_CHANGED")

    assert result.returncode == 0
    assert "User action required" in result.stdout
    assert "harness resume" not in result.stdout


def test_explain_recoverable_gate_code_suggests_resume_after_status():
    result = cli("explain", "EVIDENCE_MISSING")

    assert result.returncode == 0
    assert "harness status; then run: harness resume" in result.stdout


def test_execution_proof_failure_has_safe_existing_recovery():
    from harness.blockers import GateBlocker, select_recovery
    result = cli("explain", "EVIDENCE_TEST_EXECUTION_INVALID")
    assert result.returncode == 0
    assert "pytest" in result.stdout
    assert "EVIDENCE_TEST_EXECUTION_INVALID" in result.stdout
    assert select_recovery([GateBlocker("EVIDENCE_TEST_EXECUTION_INVALID", "verification", "fixture")]) == "VERIFYING"


@pytest.mark.parametrize("code", ["TASK_ID_ALREADY_USED", "TASK_ID_RESERVATION_INVALID"])
def test_task_identity_explain_works_without_task_or_state_mutation(tmp_path, code):
    result = subprocess.run(
        [sys.executable, "-B", "-m", "harness.cli", "explain", code],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert code in result.stdout
    assert "UNKNOWN_REMEDIATION_CODE" not in result.stderr
    assert "harness resume" not in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_explain_unknown_code_returns_invalid_usage():
    result = cli("explain", "NOT_A_CODE")

    assert result.returncode == 2
    assert "UNKNOWN_REMEDIATION_CODE" in result.stderr
