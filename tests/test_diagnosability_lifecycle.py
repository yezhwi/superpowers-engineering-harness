"""Static-compliance proof is isolated from ordinary regression proof."""

import pytest

from harness.diagnosability import validate_compliance_closure


def test_static_compliance_requires_current_passing_required_checks():
    finding = {
        "category": "diagnosability",
        "compliance": {"evidence_kind": "static_compliance", "required_checks": ["business_keys"]},
    }
    record = {
        "type": "diagnosability_review", "exit_code": 0, "commit": "head",
        "workspace_fingerprint": "sha256:" + "a" * 64,
        "workspace_fingerprint_after": "sha256:" + "a" * 64,
        "checks": {"business_keys": "pass"},
    }

    validate_compliance_closure(finding, record, current_head="head", current_workspace="sha256:" + "a" * 64)


def test_static_compliance_rejects_failed_required_check():
    finding = {"category": "diagnosability", "compliance": {"evidence_kind": "static_compliance", "required_checks": ["business_keys"]}}
    record = {"type": "diagnosability_review", "exit_code": 0, "commit": "head", "workspace_fingerprint": "sha256:" + "a" * 64, "workspace_fingerprint_after": "sha256:" + "a" * 64, "checks": {"business_keys": "fail"}}

    with pytest.raises(ValueError, match="DIAG_COMPLIANCE_CHECK_FAILED"):
        validate_compliance_closure(finding, record, current_head="head", current_workspace="sha256:" + "a" * 64)
