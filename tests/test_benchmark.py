import json
import subprocess

import pytest
import sys
from pathlib import Path

from harness.benchmark import run_benchmarks


REPO = Path(__file__).resolve().parent.parent


def test_cli_benchmark_run_writes_report(tmp_path):
    harness = tmp_path / ".harness"; harness.mkdir()
    (harness / "telemetry.json").write_text(json.dumps({"token_estimate": None, "workflow_profile": "FAST", "gate_result": "PASS"}))
    fixtures = tmp_path / "fixtures"; fixtures.mkdir()
    (fixtures / "q1.yaml").write_text("id: q1\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n")
    result = subprocess.run([sys.executable, "-m", "harness.cli", "benchmark", "run", "--fixtures", str(fixtures)], cwd=tmp_path, capture_output=True, text=True, env={"PYTHONPATH": str(REPO / "src")})
    assert result.returncode == 0
    assert (harness / "benchmark-report.json").is_file()


def test_benchmark_rejects_profile_or_gate_mismatch(tmp_path):
    fixtures = tmp_path / "fixtures"; fixtures.mkdir()
    (fixtures / "q1.yaml").write_text("id: q1\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n")
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(json.dumps({"workflow_profile": "STANDARD", "gate_result": "BLOCKED"}))
    with pytest.raises(ValueError, match="BENCHMARK_EXPECTATION_MISMATCH"):
        run_benchmarks(fixtures, telemetry)


def test_benchmark_report_uses_null_for_unavailable_metrics(tmp_path):
    fixtures = tmp_path / "fixtures"; fixtures.mkdir()
    (fixtures / "q1-fast.yaml").write_text("id: q1-fast\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n")
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(json.dumps({"workflow_profile": "FAST", "gate_result": "PASS", "token_estimate": None}))
    report = run_benchmarks(fixtures, telemetry)
    assert report["metrics"]["token_estimate"] is None
    assert report["fixtures"][0]["expected_profile"] == "FAST"
