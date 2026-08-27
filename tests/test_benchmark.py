import json
from pathlib import Path

from harness.benchmark import run_benchmarks


def test_benchmark_report_uses_null_for_unavailable_metrics(tmp_path):
    fixtures = tmp_path / "fixtures"; fixtures.mkdir()
    (fixtures / "q1-fast.yaml").write_text("id: q1-fast\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n")
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(json.dumps({"workflow_profile": "FAST", "gate_result": "PASS", "token_estimate": None}))
    report = run_benchmarks(fixtures, telemetry)
    assert report["metrics"]["token_estimate"] is None
    assert report["fixtures"][0]["expected_profile"] == "FAST"
