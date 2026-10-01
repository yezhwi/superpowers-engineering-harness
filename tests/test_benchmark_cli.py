"""P2 benchmark corpus contract tests."""

from pathlib import Path
import subprocess
import sys

from harness.benchmark import validate_corpus

REPO = Path(__file__).resolve().parents[1]


def test_plan_reconciliation_p2_benchmark_corpus():
    rows = validate_corpus(REPO / "benchmarks" / "corpus")
    p2 = {
        row["plan_reconciliation_case"]: row
        for row in rows
        if "plan-reconciliation-p2" in row["risk_tags"]
    }

    assert set(p2) == {
        "omission",
        "stale_fingerprint",
        "fake_completion",
        "replay_recovery",
        "proof_ambiguity",
        "trusted_projection_recovery",
    }
    assert all(row["level"] == "Q3" for row in p2.values())
    assert all(row["expected_profile"] == "STRICT" for row in p2.values())
    assert all(
        {"gate_pass", "regression_detected", "contract_violation_detected"}
        <= set(row["required_correctness"])
        for row in p2.values()
    )


def test_architecture_corpus_cli_validates_without_harness_state(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "benchmark",
            "architecture-corpus",
            "validate",
            "--corpus",
            str(REPO / "benchmarks/architecture"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src")},
    )

    assert result.returncode == 0
    assert result.stdout == "ARCHITECTURE_BENCHMARK_CORPUS_VALID: 10\n"
    assert not (tmp_path / ".harness").exists()


def test_architecture_corpus_cli_maps_invalid_input_to_stable_error(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "bad.txt").write_text("bad")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "benchmark",
            "architecture-corpus",
            "validate",
            "--corpus",
            str(corpus),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src")},
    )

    assert result.returncode == 2
    assert result.stderr == "ARCHITECTURE_BENCHMARK_CORPUS_INVALID\n"


def test_architecture_benchmark_template_is_pending_and_claim_free():
    template = (
        REPO / "docs/superpowers/reports/v030-architecture-benchmark-template.md"
    ).read_text()

    assert "Status: PENDING" in template
    assert "drift_detection" in template
    assert "context_recovery" in template
    assert "numerator" in template
    assert "denominator" in template
    assert "not_applicable" in template
    assert "At least three independent runs per fixture and arm" in template
    assert "No measured improvement is claimed" in template


def test_changelog_marks_architecture_p2_delivered_without_measurement_claim():
    changelog = (REPO / "CHANGELOG.md").read_text()

    assert "Architecture Evaluation P2" in changelog
    assert "remain deferred" not in changelog
    assert "No measured benchmark improvement is claimed" in changelog
