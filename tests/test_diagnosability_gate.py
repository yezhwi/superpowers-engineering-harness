"""Diagnosability Gate policy tests."""

import pytest

from harness.diagnosability import gate_blockers


def test_gate_blocks_persisted_review_with_empty_checks(tmp_path):
    import json
    harness = tmp_path / ".harness"
    (harness / "evidence").mkdir(parents=True)
    (harness / "findings").mkdir()
    (harness / "observability.yaml").write_text("""version: 1
required: true
applicability: {reasons: [security], inspected_paths: [src/order.py]}
business_keys: [order_id]
failure_boundaries: [payment]
critical_events: [created]
""")
    workspace = "sha256:" + "a" * 64
    (harness / "evidence/diagnosability-review.json").write_text(json.dumps({"type": "diagnosability_review", "timestamp": "2026-01-01T00:00:00+00:00", "command": "harness review diagnosability", "exit_code": 0, "commit": "head", "workspace_fingerprint": workspace, "workspace_fingerprint_after": workspace, "contract_required": True, "checks": {}, "finding_ids": [], "review_scope": {"files": [], "direct_dependencies": []}}))

    blockers = gate_blockers(harness, {"risk": {"level": "Q3"}, "task": {"type": "feature"}}, head="head", workspace=workspace)

    assert [blocker.code for blocker in blockers] == ["DIAGNOSABILITY_REVIEW_STALE"]


def test_persisted_review_rejects_unknown_check():
    from harness.diagnosability import validate_review_evidence
    record = {"type": "diagnosability_review", "timestamp": "t", "command": "harness review diagnosability", "exit_code": 0, "commit": "head", "workspace_fingerprint": "fp", "workspace_fingerprint_after": "fp", "contract_required": True, "finding_ids": [], "review_scope": {"files": [], "direct_dependencies": []}, "checks": {name: "pass" for name in ("business_keys", "external_failure_context", "state_transitions", "caller_rejections", "sensitive_data", "duplicate_exception_logging", "low_value_logging", "unknown")}}
    with pytest.raises(ValueError, match="DIAG_REVIEW_EVIDENCE_INVALID"):
        validate_review_evidence(record)


@pytest.mark.parametrize(("code", "category", "target"), [
    ("OBSERVABILITY_CONTRACT_INVALID", "implementation", "IMPLEMENTING"),
    ("DIAGNOSABILITY_REVIEW_MISSING", "verification", "VERIFYING"),
    ("DIAGNOSABILITY_REVIEW_STALE", "verification", "VERIFYING"),
])
def test_diagnosability_blockers_have_recovery_policy(code, category, target):
    from harness.blockers import GateBlocker, select_recovery
    assert select_recovery([GateBlocker(code, category, "blocked")]) == target


def test_q3_blocks_unassessed_contract(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "observability.yaml").write_text(
        "version: 1\nrequired: false\napplicability:\n  reasons: [not_assessed]\n  inspected_paths: ['.']\n"
    )
    blockers = gate_blockers(
        harness,
        {"risk": {"level": "Q3", "profile": "STRICT"}},
        head="head", workspace="sha256:" + "a" * 64,
    )
    assert [blocker.code for blocker in blockers] == ["OBSERVABILITY_CONTRACT_INVALID"]
