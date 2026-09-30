"""Architecture P0 lifecycle integration tests."""


def test_mode_off_gate_ignores_malformed_architecture_artifact(tmp_path):
    from harness.quality_gate import assess_gate
    from test_quality_gate import make_harness

    harness = make_harness(tmp_path)
    (harness / "architecture.yaml").write_text("malformed: [")

    assessment = assess_gate(harness, allow_preflight=True)

    assert assessment.status == "PASS"
    assert not any(
        blocker.code.startswith("ARCHITECTURE_") for blocker in assessment.blockers
    )
