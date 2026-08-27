"""Shared Evidence freshness and regression-identity validation."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from evidence_validator import (
    EvidenceValidationError,
    validate_evidence,
    validate_finding_closure_evidence,
    ReuseRequest,
    can_reuse_evidence,
)

HEAD = "a" * 40
FP = "sha256:" + "b" * 64
TEST = "tests/test_refund.py::test_double_refund"


def record(**changes):
    base = {
        "type": "custom", "timestamp": "2026-01-01T00:00:00+00:00",
        "command": f"pytest {TEST}", "exit_code": 1, "commit": HEAD,
        "workspace_fingerprint": FP, "workspace_fingerprint_after": FP,
        "subject": {"kind": "finding", "id": "FND-001"},
        "test": {"node_id": TEST},
    }
    return {**base, **changes}


RUNTIME = {"implementation": "CPython", "version": "3.11.10", "executable": "/python", "platform": "Linux-x86_64"}


def generic_record(**changes):
    evidence = record(
        type="unit_test", command=f"pytest {TEST}", exit_code=0,
        scope="related", covered_tests=[TEST], runtime=RUNTIME,
    )
    evidence.pop("subject")
    evidence.pop("test")
    return {**evidence, **changes}


def reuse_request():
    return ReuseRequest("unit_test", f"pytest {TEST}", "related", (TEST,), None, None, None)


def test_reuse_requires_exact_generic_successful_evidence():
    evidence = generic_record()
    assert can_reuse_evidence(evidence, reuse_request(), current_head=HEAD,
                              current_workspace=FP, current_runtime=RUNTIME)


@pytest.mark.parametrize("changes", [
    {"command": "pytest other"}, {"exit_code": 1},
    {"workspace_fingerprint_after": "sha256:" + "0" * 64},
    {"runtime": {}}, {"subject": {"kind": "finding", "id": "FND-001"}},
])
def test_reuse_rejects_nonidentical_or_non_generic_proof(changes):
    evidence = generic_record(**changes)
    assert not can_reuse_evidence(evidence, reuse_request(), current_head=HEAD,
                                  current_workspace=FP, current_runtime=RUNTIME)


def test_rejects_workspace_stale_evidence():
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_WORKSPACE_STALE"):
        validate_evidence(record(), current_head=HEAD, current_workspace="sha256:" + "c" * 64)


def test_rejects_wrong_finding_subject():
    with pytest.raises(EvidenceValidationError, match="FINDING_SUBJECT_MISMATCH"):
        validate_evidence(record(subject={"kind": "finding", "id": "FND-002"}), current_head=HEAD, current_workspace=FP, finding_id="FND-001", test_id=TEST)


def test_rejects_unrelated_test_identity():
    with pytest.raises(EvidenceValidationError, match="REGRESSION_TEST_MISMATCH"):
        validate_evidence(record(test={"node_id": "tests/test_other.py::test_other"}), current_head=HEAD, current_workspace=FP, finding_id="FND-001", test_id=TEST)


def test_accepts_fresh_matching_failed_regression_evidence():
    validate_evidence(record(), current_head=HEAD, current_workspace=FP, expected_success=False, finding_id="FND-001", test_id=TEST)


def test_major_closure_accepts_related_evidence_covering_impact_tests():
    evidence = record(exit_code=0, scope="related", covered_tests=[TEST, "tests/test_api.py::test_save"])
    finding = {"id": "FND-001", "severity": "major"}
    impact = {"impact": {"required_tests": [TEST, "tests/test_api.py::test_save"], "full_suite": {"recommended": False}}}
    validate_finding_closure_evidence(finding, evidence, impact, current_head=HEAD, current_workspace=FP)


def test_major_closure_rejects_missing_related_coverage():
    evidence = record(exit_code=0, scope="related", covered_tests=[TEST])
    finding = {"id": "FND-001", "severity": "major"}
    impact = {"impact": {"required_tests": [TEST, "tests/test_api.py::test_save"], "full_suite": {"recommended": False}}}
    with pytest.raises(EvidenceValidationError, match="RELATED_TEST_COVERAGE_MISSING"):
        validate_finding_closure_evidence(finding, evidence, impact, current_head=HEAD, current_workspace=FP)


def test_major_closure_ignores_advisory_full_suite_recommendation():
    evidence = record(exit_code=0, scope="related", covered_tests=[TEST])
    finding = {"id": "FND-001", "severity": "major"}
    impact = {"impact": {"required_tests": [TEST], "full_suite": {"recommended": True}}}
    validate_finding_closure_evidence(finding, evidence, impact, current_head=HEAD, current_workspace=FP)
