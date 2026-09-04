"""Reason-driven recovery must not let agents select a convenient state."""


def test_defect_blocker_beats_verification_and_routes_to_reproducing():
    """Break caught: open Finding can be bypassed by refreshing unrelated evidence."""
    from harness.blockers import GateBlocker, select_recovery

    target = select_recovery(
        [
            GateBlocker(
                "EVIDENCE_WORKSPACE_STALE",
                "verification",
                "refresh",
                recover_to="VERIFYING",
            ),
            GateBlocker(
                "FINDING_OPEN",
                "defect",
                "resolve",
                finding_id="FND-001",
                recover_to="REPRODUCING",
            ),
        ]
    )

    assert target == "REPRODUCING"


def test_verification_blocker_routes_to_verifying():
    """Break caught: stale evidence requires fake implementation work."""
    from harness.blockers import GateBlocker, select_recovery

    assert (
        select_recovery(
            [
                GateBlocker(
                    "EVIDENCE_MISSING",
                    "verification",
                    "collect",
                    recover_to="VERIFYING",
                ),
            ]
        )
        == "VERIFYING"
    )


def test_requirement_evidence_missing_routes_to_verifying_without_message_parsing():
    """Break caught: requirement proof gap is misclassified as implementation work."""
    from harness.blockers import GateBlocker, select_recovery

    blocker = GateBlocker(
        "EVIDENCE_MISSING",
        "verification",
        "REQ-001 evidence missing: unit-test.json",
        source="unit-test.json",
        requirement_id="REQ-001",
        recover_to="IMPLEMENTING",
    )

    assert select_recovery([blocker]) == "VERIFYING"


def test_violated_invariant_routes_to_implementing():
    """Break caught: proven invariant violation is treated as missing proof."""
    from harness.blockers import GateBlocker, select_recovery

    assert (
        select_recovery(
            [
                GateBlocker("INVARIANT_VIOLATED", "implementation", "INV-001 violated"),
            ]
        )
        == "IMPLEMENTING"
    )


def test_unrouteable_harness_blocker_fails_closed():
    """Break caught: corrupted Harness data receives guessed recovery route."""
    from harness.blockers import GateBlocker, select_recovery

    assert (
        select_recovery(
            [
                GateBlocker("HARNESS_SCHEMA_INVALID", "harness", "repair schema"),
            ]
        )
        is None
    )
