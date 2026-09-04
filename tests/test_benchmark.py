import json
import subprocess

import pytest
import sys
from pathlib import Path

from harness.benchmark import (
    compare_benchmarks,
    evaluate_acceptance,
    run_benchmarks,
    validate_corpus,
)


REPO = Path(__file__).resolve().parent.parent


def test_acceptance_marks_complete_improving_q1_metrics_pass():
    rows = []
    for index in range(20):
        rows.append(
            {
                "id": f"q1-{index}",
                "level": "Q1",
                "status": "CORRECTNESS_PRESERVED",
                "baseline": {
                    "correctness": {"gate_pass": True, "regression_detected": True},
                    "metrics": {
                        "tool_calls": 10,
                        "token_estimate": 100,
                        "elapsed_seconds": 20,
                    },
                },
                "adaptive": {
                    "correctness": {"gate_pass": True, "regression_detected": True},
                    "metrics": {
                        "tool_calls": 5,
                        "token_estimate": 50,
                        "elapsed_seconds": 10,
                    },
                },
            }
        )
    report = {"fixtures": rows}
    result = evaluate_acceptance(report, [])
    assert (
        result["AC16"]["status"]
        == result["AC17"]["status"]
        == result["AC18"]["status"]
        == "PASS"
    )


def test_acceptance_passes_success_and_detection_only_with_complete_corpus_rows():
    rows = []
    fixtures = []
    for level, count in (("Q0", 10), ("Q1", 20), ("Q2", 10), ("Q3", 10)):
        for index in range(count):
            required = [] if level == "Q0" else ["gate_pass", "regression_detected"]
            fixtures.append(
                {
                    "id": f"{level}-{index}",
                    "level": level,
                    "required_correctness": required,
                }
            )
            proof = {"correctness": {key: True for key in required}}
            rows.append(
                {
                    "id": f"{level}-{index}",
                    "level": level,
                    "status": "CORRECTNESS_PRESERVED",
                    "baseline": proof,
                    "adaptive": proof,
                }
            )
    result = evaluate_acceptance({"fixtures": rows}, fixtures)
    assert result["AC19"]["status"] == result["AC20"]["status"] == "PASS"


def test_validate_corpus_requires_exact_level_distribution(tmp_path):
    corpus = tmp_path / "corpus"
    for level, count in {"Q0": 10, "Q1": 20, "Q2": 10, "Q3": 9}.items():
        directory = corpus / level.lower()
        directory.mkdir(parents=True)
        for index in range(count):
            profile = {"Q0": "null", "Q1": "FAST", "Q2": "STANDARD", "Q3": "STRICT"}[
                level
            ]
            (directory / f"{level.lower()}-{index:02d}-case.yaml").write_text(
                f"id: {level.lower()}-{index:02d}-case\nlevel: {level}\nexpected_profile: {profile}\nscenario: case\nrisk_tags: [tag]\nrequired_correctness: []\n"
            )
    with pytest.raises(ValueError, match="BENCHMARK_CORPUS_INVALID"):
        validate_corpus(corpus)


def _write_fixture(root, required):
    fixtures = root / "fixtures"
    fixtures.mkdir()
    (fixtures / "q1.json.yaml").write_text(
        "id: q1\nrequired_correctness:\n"
        + "".join(f"  - {item}\n" for item in required)
    )
    return fixtures


def _write_artifact(root, mode, correctness, metrics):
    path = root / mode
    path.mkdir()
    (path / "q1.json").write_text(
        json.dumps(
            {
                "fixture_id": "q1",
                "mode": mode,
                "correctness": correctness,
                "metrics": metrics,
            }
        )
    )


def test_compare_reports_correctness_preserved_and_numeric_deltas(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass", "regression_detected"])
    _write_artifact(
        tmp_path,
        "baseline",
        {"gate_pass": True, "regression_detected": True},
        {"tool_calls": 10, "elapsed_seconds": 20},
    )
    _write_artifact(
        tmp_path,
        "adaptive",
        {"gate_pass": True, "regression_detected": True},
        {"tool_calls": 5, "elapsed_seconds": 10},
    )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["overall"] == "CORRECTNESS_PRESERVED"
    assert report["fixtures"][0]["metrics"]["tool_calls_delta"] == -5


def test_compare_reports_adaptive_required_false_as_regression(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    _write_artifact(tmp_path, "adaptive", {"gate_pass": False}, {})
    assert (
        compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")[
            "overall"
        ]
        == "CORRECTNESS_REGRESSION"
    )


def test_compare_is_inconclusive_for_missing_artifact(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    assert (
        compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")[
            "overall"
        ]
        == "INCONCLUSIVE"
    )


def test_cli_benchmark_compare_writes_correctness_report(tmp_path):
    (tmp_path / ".harness").mkdir()
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    _write_artifact(tmp_path, "adaptive", {"gate_pass": True}, {})
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "benchmark",
            "compare",
            "--fixtures",
            str(fixtures),
            "--baseline",
            str(tmp_path / "baseline"),
            "--adaptive",
            str(tmp_path / "adaptive"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src")},
    )
    assert result.returncode == 0
    report = json.loads((tmp_path / ".harness/benchmark-report.json").read_text())
    assert report["overall"] == "CORRECTNESS_PRESERVED"
    assert report["acceptance"]["AC16"]["status"] == "INCONCLUSIVE"


def test_cli_benchmark_run_writes_report(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "telemetry.json").write_text(
        json.dumps(
            {"token_estimate": None, "workflow_profile": "FAST", "gate_result": "PASS"}
        )
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "q1.yaml").write_text(
        "id: q1\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "benchmark",
            "run",
            "--fixtures",
            str(fixtures),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src")},
    )
    assert result.returncode == 0
    assert (harness / "benchmark-report.json").is_file()


def test_benchmark_rejects_profile_or_gate_mismatch(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "q1.yaml").write_text(
        "id: q1\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n"
    )
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(
        json.dumps({"workflow_profile": "STANDARD", "gate_result": "BLOCKED"})
    )
    with pytest.raises(ValueError, match="BENCHMARK_EXPECTATION_MISMATCH"):
        run_benchmarks(fixtures, telemetry)


def test_benchmark_report_uses_null_for_unavailable_metrics(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "q1-fast.yaml").write_text(
        "id: q1-fast\nrisk_level: Q1\nexpected_profile: FAST\nexpected_gate: PASS\n"
    )
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(
        json.dumps(
            {"workflow_profile": "FAST", "gate_result": "PASS", "token_estimate": None}
        )
    )
    report = run_benchmarks(fixtures, telemetry)
    assert report["metrics"]["token_estimate"] is None
    assert report["fixtures"][0]["expected_profile"] == "FAST"
