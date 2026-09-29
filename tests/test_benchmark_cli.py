"""P2 benchmark corpus contract tests."""

from pathlib import Path

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
