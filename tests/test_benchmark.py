import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.benchmark import (
    compare_benchmarks,
    evaluate_acceptance,
    run_benchmarks,
    summarize_runs,
    tokens_per_success,
    validate_corpus,
)

REPO = Path(__file__).resolve().parent.parent


def test_summarize_three_runs_reports_median_p90_success_rate_and_tps():
    assert summarize_runs(
        [
            {"total_tokens": 10, "success": True},
            {"total_tokens": 20, "success": False},
            {"total_tokens": 30, "success": True},
        ]
    ) == {
        "median_tokens": 20.0,
        "p90_tokens": 30.0,
        "success_rate": 2 / 3,
        "tokens_per_success": 30,
        "tool_calls_per_success": "INCONCLUSIVE",
        "elapsed_per_success": "INCONCLUSIVE",
        "search_rounds_per_success": "INCONCLUSIVE",
        "file_reads_per_success": "INCONCLUSIVE",
    }


@pytest.mark.parametrize(
    "runs",
    [
        [{"total_tokens": 10, "success": True}] * 2,
        [
            {"total_tokens": 10, "success": True},
            {"total_tokens": None, "success": True},
            {"total_tokens": 20, "success": True},
        ],
    ],
)
def test_summarize_runs_is_inconclusive_without_three_complete_runs(runs):
    assert summarize_runs(runs) == "INCONCLUSIVE"


def test_summarize_runs_reports_agent_metrics_per_success():
    result = summarize_runs(
        [
            {
                "total_tokens": 10,
                "tool_calls": 3,
                "elapsed_seconds": 2,
                "success": True,
            },
            {
                "total_tokens": 20,
                "tool_calls": 6,
                "elapsed_seconds": 4,
                "success": False,
            },
            {
                "total_tokens": 30,
                "tool_calls": 9,
                "elapsed_seconds": 6,
                "success": True,
            },
        ]
    )

    assert result["tool_calls_per_success"] == 9
    assert result["elapsed_per_success"] == 6


def test_tokens_per_success_counts_failed_attempt_tokens():
    assert (
        tokens_per_success(
            [
                {"total_tokens": 100, "success": True},
                {"total_tokens": 900, "success": False},
            ]
        )
        == 1000
    )


@pytest.mark.parametrize(
    "attempts",
    [
        [],
        [{"total_tokens": 100, "success": False}],
        [{"total_tokens": None, "success": True}],
        [{"total_tokens": 100, "success": None}],
    ],
)
def test_tokens_per_success_is_inconclusive_without_complete_success_data(attempts):
    assert tokens_per_success(attempts) == "INCONCLUSIVE"


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


def _write_artifact(root, mode, correctness, metrics, usage=None):
    path = root / mode
    path.mkdir()
    (path / "q1.json").write_text(
        json.dumps(
            {
                "fixture_id": "q1",
                "mode": mode,
                "correctness": correctness,
                "metrics": metrics,
                **({"usage": usage} if usage is not None else {}),
            }
        )
    )


@pytest.mark.parametrize(
    "usage",
    [
        {"total_tokens": 10, "source": "bogus"},
        {"total_tokens": 10, "source": "runtime", "unexpected": 1},
        {
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 9,
            "source": "runtime",
        },
    ],
)
def test_compare_rejects_artifact_with_invalid_usage(usage, tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {}, usage)
    _write_artifact(
        tmp_path,
        "adaptive",
        {"gate_pass": True},
        {},
        {"total_tokens": 5, "source": "runtime"},
    )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["overall"] == "INCONCLUSIVE"
    assert report["fixtures"][0]["baseline"] is None


def test_compare_rejects_artifact_with_invalid_usage_source(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(
        tmp_path,
        "baseline",
        {"gate_pass": True},
        {},
        {"total_tokens": 10, "source": "bogus"},
    )
    _write_artifact(
        tmp_path,
        "adaptive",
        {"gate_pass": True},
        {},
        {"total_tokens": 5, "source": "runtime"},
    )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["overall"] == "INCONCLUSIVE"
    assert report["fixtures"][0]["baseline"] is None


@pytest.mark.parametrize(
    "metrics",
    [
        {"tool_calls": -1},
        {"elapsed_seconds": -0.5},
        {"search_rounds": 1.5},
    ],
)
def test_compare_rejects_artifact_with_invalid_efficiency_metric(metrics, tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, metrics)
    _write_artifact(tmp_path, "adaptive", {"gate_pass": True}, {})

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["fixtures"][0]["baseline"] is None
    assert report["overall"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "agent",
    [{"tool_calls": -1}, {"unexpected": 1}],
)
def test_compare_rejects_artifact_with_invalid_agent_metric(agent, tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    baseline = tmp_path / "baseline"
    adaptive = tmp_path / "adaptive"
    baseline.mkdir()
    adaptive.mkdir()
    for directory, mode, run_agent in (
        (baseline, "baseline", agent),
        (adaptive, "adaptive", {"tool_calls": 1}),
    ):
        (directory / "q1.json").write_text(
            json.dumps(
                {
                    "fixture_id": "q1",
                    "mode": mode,
                    "runs": [
                        {
                            "correctness": {"gate_pass": True},
                            "metrics": {},
                            "agent": run_agent,
                        }
                    ],
                }
            )
        )

    report = compare_benchmarks(fixtures, baseline, adaptive)

    assert report["fixtures"][0]["baseline"] is None


def test_compare_accepts_three_run_artifact_and_reports_statistics(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    runs = [
        {
            "correctness": {"gate_pass": True},
            "metrics": {"elapsed_seconds": elapsed},
            "agent": {"tool_calls": calls},
            "usage": {"total_tokens": tokens, "source": "runtime"},
        }
        for tokens, calls, elapsed in ((10, 1, 2), (20, 2, 4), (30, 3, 6))
    ]
    for mode in ("baseline", "adaptive"):
        directory = tmp_path / mode
        directory.mkdir()
        (directory / "q1.json").write_text(
            json.dumps({"fixture_id": "q1", "mode": mode, "runs": runs})
        )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["overall"] == "CORRECTNESS_PRESERVED"
    assert report["fixtures"][0]["run_statistics"]["adaptive"] == {
        "median_tokens": 20.0,
        "p90_tokens": 30.0,
        "success_rate": 1.0,
        "tokens_per_success": 20,
        "tool_calls_per_success": 2,
        "elapsed_per_success": 4,
        "search_rounds_per_success": "INCONCLUSIVE",
        "file_reads_per_success": "INCONCLUSIVE",
    }
    assert report["fixtures"][0]["tokens_per_success"]["adaptive"] == 20
    assert report["metrics"]["tokens_per_success"]["adaptive"] == 20


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


def test_experiment_failure_overrides_missing_usage_metrics(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    _write_artifact(tmp_path, "adaptive", {"gate_pass": False}, {})

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_experiment_integrity_failure_overrides_estimated_usage(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    estimated = {"total_tokens": 10, "source": "estimated"}
    _write_artifact(
        tmp_path,
        "baseline",
        {"gate_pass": True},
        {},
        estimated,
    )
    _write_artifact(
        tmp_path,
        "adaptive",
        {"gate_pass": True, "integrity": False},
        {},
        estimated,
    )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_run_integrity_failure_overrides_missing_run_count(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    for mode in ("baseline", "adaptive"):
        directory = tmp_path / mode
        directory.mkdir()
        (directory / "q1.json").write_text(
            json.dumps(
                {
                    "fixture_id": "q1",
                    "mode": mode,
                    "runs": [
                        {
                            "correctness": {
                                "gate_pass": True,
                                "integrity": False,
                            },
                            "metrics": {},
                            "usage": {"total_tokens": 10, "source": "runtime"},
                        }
                    ],
                }
            )
        )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_missing_usage_is_inconclusive_without_efficiency_claim(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    _write_artifact(tmp_path, "adaptive", {"gate_pass": True}, {})

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["experiment"] == {"status": "INCONCLUSIVE", "confidence": "high"}


def test_estimated_usage_is_low_confidence_and_not_efficiency_pass(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    usage = {"total_tokens": 10, "source": "estimated"}
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {}, usage)
    _write_artifact(tmp_path, "adaptive", {"gate_pass": True}, {}, usage)

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["experiment"] == {"status": "INCONCLUSIVE", "confidence": "low"}


def test_single_run_q1_improvement_is_inconclusive_experiment(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    baseline = tmp_path / "baseline"
    adaptive = tmp_path / "adaptive"
    baseline.mkdir()
    adaptive.mkdir()
    for index in range(20):
        fixture_id = f"q1-{index}"
        (fixtures / f"{fixture_id}.yaml").write_text(
            f"id: {fixture_id}\nlevel: Q1\nrequired_correctness: [gate_pass]\n"
        )
        for directory, mode, tokens, calls in (
            (baseline, "baseline", 100, 10),
            (adaptive, "adaptive", 50, 5),
        ):
            (directory / f"{fixture_id}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": fixture_id,
                        "mode": mode,
                        "correctness": {"gate_pass": True},
                        "metrics": {"tool_calls": calls, "elapsed_seconds": 10},
                        "usage": {"total_tokens": tokens, "source": "runtime"},
                    }
                )
            )

    report = compare_benchmarks(fixtures, baseline, adaptive)

    assert report["experiment"] == {"status": "INCONCLUSIVE", "confidence": "high"}


def test_missing_correctness_in_complete_q1_corpus_is_inconclusive(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    baseline = tmp_path / "baseline"
    adaptive = tmp_path / "adaptive"
    baseline.mkdir()
    adaptive.mkdir()
    for index in range(20):
        fixture_id = f"q1-{index}"
        (fixtures / f"{fixture_id}.yaml").write_text(
            f"id: {fixture_id}\nlevel: Q1\nrequired_correctness: [gate_pass]\n"
        )
        for directory, mode, tokens, correctness in (
            (baseline, "baseline", 100, {"gate_pass": True}),
            (adaptive, "adaptive", 50, {} if index == 0 else {"gate_pass": True}),
        ):
            (directory / f"{fixture_id}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": fixture_id,
                        "mode": mode,
                        "correctness": correctness,
                        "metrics": {"tool_calls": 5},
                        "usage": {"total_tokens": tokens, "source": "runtime"},
                    }
                )
            )

    report = compare_benchmarks(fixtures, baseline, adaptive)

    assert report["experiment"] == {"status": "INCONCLUSIVE", "confidence": "high"}


def test_three_run_q1_improvement_passes_experiment(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    baseline = tmp_path / "baseline"
    adaptive = tmp_path / "adaptive"
    baseline.mkdir()
    adaptive.mkdir()
    for index in range(20):
        fixture_id = f"q1-{index}"
        (fixtures / f"{fixture_id}.yaml").write_text(
            f"id: {fixture_id}\nlevel: Q1\nrequired_correctness: [gate_pass]\n"
        )
        for directory, mode, tokens, calls in (
            (baseline, "baseline", (100, 110, 120), 10),
            (adaptive, "adaptive", (40, 50, 60), 5),
        ):
            (directory / f"{fixture_id}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": fixture_id,
                        "mode": mode,
                        "runs": [
                            {
                                "correctness": {"gate_pass": True},
                                "metrics": {
                                    "tool_calls": calls,
                                    "search_rounds": 2,
                                    "file_reads": 3,
                                    "elapsed_seconds": 10,
                                },
                                "usage": {"total_tokens": value, "source": "runtime"},
                            }
                            for value in tokens
                        ],
                    }
                )
            )

    report = compare_benchmarks(fixtures, baseline, adaptive)

    assert report["experiment"] == {"status": "PASS", "confidence": "high"}


def test_single_run_q1_without_token_reduction_is_inconclusive(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    baseline = tmp_path / "baseline"
    adaptive = tmp_path / "adaptive"
    baseline.mkdir()
    adaptive.mkdir()
    for index in range(20):
        fixture_id = f"q1-{index}"
        (fixtures / f"{fixture_id}.yaml").write_text(
            f"id: {fixture_id}\nlevel: Q1\nrequired_correctness: [gate_pass]\n"
        )
        for directory, mode, tokens in (
            (baseline, "baseline", 100),
            (adaptive, "adaptive", 100),
        ):
            (directory / f"{fixture_id}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": fixture_id,
                        "mode": mode,
                        "correctness": {"gate_pass": True},
                        "metrics": {"tool_calls": 5},
                        "usage": {"total_tokens": tokens, "source": "runtime"},
                    }
                )
            )

    report = compare_benchmarks(fixtures, baseline, adaptive)

    assert report["experiment"] == {"status": "INCONCLUSIVE", "confidence": "high"}


def test_compare_aggregates_tokens_per_success_across_failed_attempts(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for fixture_id in ("success", "failure"):
        (fixtures / f"{fixture_id}.yaml").write_text(
            f"id: {fixture_id}\nrequired_correctness: [gate_pass]\n"
        )
    baseline = tmp_path / "baseline"
    adaptive = tmp_path / "adaptive"
    baseline.mkdir()
    adaptive.mkdir()
    for fixture_id, success, tokens in (
        ("success", True, 100),
        ("failure", False, 900),
    ):
        for directory, mode in ((baseline, "baseline"), (adaptive, "adaptive")):
            (directory / f"{fixture_id}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": fixture_id,
                        "mode": mode,
                        "correctness": {"gate_pass": success},
                        "metrics": {},
                        "usage": {"total_tokens": tokens, "source": "runtime"},
                    }
                )
            )

    report = compare_benchmarks(fixtures, baseline, adaptive)

    assert report["metrics"]["tokens_per_success"] == {
        "baseline": 1000,
        "adaptive": 1000,
    }


def test_compare_aggregate_tokens_per_success_is_inconclusive_with_zero_success(
    tmp_path,
):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    usage = {"total_tokens": 100, "source": "runtime"}
    _write_artifact(tmp_path, "baseline", {"gate_pass": False}, {}, usage)
    _write_artifact(tmp_path, "adaptive", {"gate_pass": False}, {}, usage)

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["metrics"]["tokens_per_success"] == {
        "baseline": "INCONCLUSIVE",
        "adaptive": "INCONCLUSIVE",
    }


def test_compare_reports_tokens_per_success_for_known_attempts(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    usage = {"total_tokens": 100, "source": "runtime"}
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {}, usage)
    _write_artifact(tmp_path, "adaptive", {"gate_pass": True}, {}, usage)

    report = compare_benchmarks(fixtures, tmp_path / "baseline", tmp_path / "adaptive")

    assert report["fixtures"][0]["tokens_per_success"] == {
        "baseline": 100,
        "adaptive": 100,
    }


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


@pytest.fixture
def complete_experiment(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for mode in ("baseline", "adaptive"):
        (tmp_path / mode).mkdir()
    for index in range(20):
        fid = f"q1-{index}"
        (fixtures / f"{fid}.yaml").write_text(
            f"id: {fid}\nlevel: Q1\nrequired_correctness: [gate_pass]\n"
        )
        for mode, cost in (("baseline", 10), ("adaptive", 5)):
            run = {
                "correctness": {"gate_pass": True, "integrity": True},
                "metrics": {"elapsed_seconds": 10},
                "agent": dict.fromkeys(
                    ("tool_calls", "search_rounds", "file_reads"), cost
                ),
                "usage": {"total_tokens": cost * 10, "source": "runtime"},
            }
            (tmp_path / mode / f"{fid}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": fid,
                        "mode": mode,
                        "runs": [run] * 3,
                    }
                )
            )
    return tmp_path


def _compare_complete(root):
    return compare_benchmarks(root / "fixtures", root / "baseline", root / "adaptive")


def _mutate_run(root, change):
    path = root / "adaptive" / "q1-0.json"
    artifact = json.loads(path.read_text())
    change(artifact["runs"][0])
    path.write_text(json.dumps(artifact))


@pytest.mark.parametrize(
    "key", ["tool_calls", "search_rounds", "file_reads", "elapsed_seconds"]
)
@pytest.mark.parametrize("missing", [True, False])
def test_missing_efficiency_field_blocks_pass(complete_experiment, key, missing):
    def change(run):
        values = run["metrics"] if key == "elapsed_seconds" else run["agent"]
        if missing:
            values.pop(key)
        else:
            values[key] = None

    _mutate_run(complete_experiment, change)
    assert (
        _compare_complete(complete_experiment)["experiment"]["status"] == "INCONCLUSIVE"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_elapsed_rejects_artifact(complete_experiment, value):
    _mutate_run(
        complete_experiment, lambda run: run["metrics"].update(elapsed_seconds=value)
    )
    report = _compare_complete(complete_experiment)
    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"]["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("key", ["tool_calls", "search_rounds", "file_reads"])
def test_counter_conflict_rejects_artifact(complete_experiment, key):
    _mutate_run(complete_experiment, lambda run: run["metrics"].update({key: 0}))
    report = _compare_complete(complete_experiment)
    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"]["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("key", ["tool_calls", "search_rounds", "file_reads"])
@pytest.mark.parametrize("source", ["agent", "metrics"])
@pytest.mark.parametrize("other", [None, 0])
def test_counter_merge_preserves_zero_and_matching_values(
    complete_experiment, key, source, other
):
    def change(run):
        run[source][key] = 0
        run["metrics" if source == "agent" else "agent"][key] = other

    _mutate_run(complete_experiment, change)
    report = _compare_complete(complete_experiment)
    assert report["experiment"]["status"] == "PASS"
    assert (
        report["fixtures"][0]["run_statistics"]["adaptive"][f"{key}_per_success"]
        == 10 / 3
    )


def test_all_agent_counters_reach_statistics(complete_experiment):
    report = _compare_complete(complete_experiment)
    assert report["experiment"]["status"] == "PASS"
    for key in ("tool_calls", "search_rounds", "file_reads"):
        assert (
            report["fixtures"][0]["run_statistics"]["adaptive"][f"{key}_per_success"]
            == 5
        )


@pytest.mark.parametrize(
    "failure", [("correctness", "gate_pass"), ("integrity", "integrity")]
)
@pytest.mark.parametrize("invalid", ["nonfinite", "counter_conflict"])
def test_known_failure_overrides_invalid_efficiency_artifact(
    complete_experiment, failure, invalid
):
    _, key = failure

    def change(run):
        run["correctness"][key] = False
        if invalid == "nonfinite":
            run["metrics"]["elapsed_seconds"] = float("inf")
        else:
            run["metrics"]["tool_calls"] = run["agent"]["tool_calls"] + 1

    _mutate_run(complete_experiment, change)
    report = _compare_complete(complete_experiment)
    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_known_failure_after_malformed_run_still_overrides_inconclusive(
    complete_experiment,
):
    path = complete_experiment / "adaptive" / "q1-0.json"
    artifact = json.loads(path.read_text())
    artifact["runs"].insert(0, {"correctness": None, "metrics": {}})
    artifact["runs"][1]["correctness"]["gate_pass"] = False
    path.write_text(json.dumps(artifact))

    report = _compare_complete(complete_experiment)

    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_known_failure_survives_when_both_artifacts_are_invalid(complete_experiment):
    for mode in ("baseline", "adaptive"):
        path = complete_experiment / mode / "q1-0.json"
        artifact = json.loads(path.read_text())
        artifact["runs"][0]["metrics"]["elapsed_seconds"] = float("inf")
        if mode == "adaptive":
            artifact["runs"][0]["correctness"]["gate_pass"] = False
        path.write_text(json.dumps(artifact))

    report = _compare_complete(complete_experiment)

    assert report["fixtures"][0]["baseline"] is None
    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_legacy_top_level_failure_survives_malformed_runs(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    adaptive = tmp_path / "adaptive"
    adaptive.mkdir()
    (adaptive / "q1.json").write_text(
        json.dumps(
            {
                "fixture_id": "q1",
                "mode": "adaptive",
                "correctness": {"gate_pass": False},
                "metrics": {},
                "runs": "malformed",
            }
        )
    )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", adaptive)

    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}


def test_integrity_failure_survives_malformed_run_correctness(tmp_path):
    fixtures = _write_fixture(tmp_path, ["gate_pass"])
    _write_artifact(tmp_path, "baseline", {"gate_pass": True}, {})
    adaptive = tmp_path / "adaptive"
    adaptive.mkdir()
    (adaptive / "q1.json").write_text(
        json.dumps(
            {
                "fixture_id": "q1",
                "mode": "adaptive",
                "runs": [{"correctness": None, "metrics": {}, "integrity": False}],
            }
        )
    )

    report = compare_benchmarks(fixtures, tmp_path / "baseline", adaptive)

    assert report["fixtures"][0]["adaptive"] is None
    assert report["experiment"] == {"status": "FAIL", "confidence": "high"}
