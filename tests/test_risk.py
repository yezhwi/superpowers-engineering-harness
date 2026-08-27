import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from harness.risk import RiskClassificationError, classify, validate_escalation


SAFE = {
    "scope": "low", "contract": "none", "data": "none",
    "authorization": "none", "security": "none", "concurrency": "none",
    "deployment": "none",
}


def test_safe_q1_selects_fast():
    assert classify("Q1", SAFE) == "FAST"


def test_q1_with_contract_risk_fails_closed():
    with pytest.raises(RiskClassificationError, match="RISK_LEVEL_UNDERSPECIFIED"):
        classify("Q1", {**SAFE, "contract": "low"})


@pytest.mark.parametrize("dimension", ["data", "authorization", "security", "concurrency", "deployment"])
def test_q1_with_high_risk_fails_closed(dimension):
    with pytest.raises(RiskClassificationError, match="RISK_LEVEL_UNDERSPECIFIED"):
        classify("Q1", {**SAFE, dimension: "high"})


def test_q2_to_q1_downgrade_is_rejected():
    with pytest.raises(RiskClassificationError, match="RISK_DOWNGRADE_FORBIDDEN"):
        validate_escalation("Q2", "Q1")


REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args], cwd=cwd,
        capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def test_task_classify_persists_fast_profile_and_enters_classified(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert run_cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    flags = [item for pair in SAFE.items() for item in (f"--{pair[0]}", pair[1])]

    result = run_cli(tmp_path, "task", "classify", "--level", "Q1", *flags)

    task = yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())
    assert result.returncode == 0, result.stderr
    assert task["state"] == "CLASSIFIED"
    assert task["risk"]["profile"] == "FAST"
    assert task["risk"]["workspace_fingerprint"]
