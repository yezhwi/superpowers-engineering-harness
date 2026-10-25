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


def test_interface_verification_recovery_is_order_independent():
    from harness.blockers import GateBlocker, select_recovery

    interface = GateBlocker(
        "INTERFACE_VERIFICATION_MISSING", "verification", "collect interface proof"
    )
    evidence = GateBlocker("EVIDENCE_MISSING", "verification", "collect proof")
    assert select_recovery([interface, evidence]) == "VERIFYING"
    assert select_recovery([evidence, interface]) == "VERIFYING"


def test_known_decision_conflicts_require_user_authority():
    from harness.blockers import RECOVERY_POLICY, is_user_authority_blocker

    for code in (
        "DECISION_CONFLICT",
        "DECISION_SUPERSEDE_INVALID",
        "DECISION_REFERENCE_INVALID",
        "DECISION_REFERENCE_STATUS_INVALID",
        "INTERFACE_BREAKING_CHANGE_UNAPPROVED",
    ):
        assert is_user_authority_blocker(code), code
        assert RECOVERY_POLICY[code] == "ESCALATED"


def test_unknown_blocker_cannot_hide_behind_known_recovery():
    from harness.blockers import GateBlocker, select_recovery

    unknown = GateBlocker("HARNESS_SCHEMA_INVALID", "harness", "repair schema")
    known = GateBlocker("EVIDENCE_MISSING", "verification", "collect")
    assert select_recovery([unknown, known]) is None
    assert select_recovery([known, unknown]) is None


def test_gate_literal_blocker_codes_have_explicit_routes():
    import ast
    from pathlib import Path

    from harness import quality_gate
    from harness.blockers import RECOVERY_POLICY, is_user_authority_blocker

    tree = ast.parse(Path(quality_gate.__file__).read_text())
    codes = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"block", "GateBlocker"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert not {
        code
        for code in codes
        if code not in RECOVERY_POLICY and not is_user_authority_blocker(code)
    }
