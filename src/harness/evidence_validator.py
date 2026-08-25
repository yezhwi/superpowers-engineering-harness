"""Single source of truth for Harness evidence proof validity."""

import json
from importlib import resources

from jsonschema import ValidationError, validate

SCHEMA = resources.files("harness").joinpath("schemas", "evidence.schema.json")


class EvidenceValidationError(Exception):
    pass


def _fail(code: str) -> None:
    raise EvidenceValidationError(code)


def validate_evidence(record, *, current_head, current_workspace,
                      expected_success=None, finding_id=None, test_id=None,
                      require_current_workspace=True):
    """Fail closed unless record proves required current evidence."""
    try:
        validate(record, json.loads(SCHEMA.read_text()))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise EvidenceValidationError(f"EVIDENCE_SCHEMA_INVALID: {exc}") from exc
    if record.get("commit") != current_head:
        _fail("EVIDENCE_HEAD_MISMATCH")
    before = record.get("workspace_fingerprint")
    after = record.get("workspace_fingerprint_after")
    if before != after or (require_current_workspace and (before != current_workspace or after != current_workspace)):
        _fail("EVIDENCE_WORKSPACE_STALE")
    if expected_success is not None and (record.get("exit_code") == 0) != expected_success:
        _fail("EVIDENCE_RESULT_MISMATCH")
    subject = record.get("subject")
    test = record.get("test")
    if (subject is None) != (test is None):
        _fail("EVIDENCE_SCHEMA_INVALID: subject and test must be paired")
    if finding_id is not None:
        if subject != {"kind": "finding", "id": finding_id}:
            _fail("FINDING_SUBJECT_MISMATCH")
    if test_id is not None:
        if not isinstance(test, dict) or test.get("node_id") != test_id:
            _fail("REGRESSION_TEST_MISMATCH")


def validate_finding_closure_evidence(finding, record, impact, *, current_head,
                                      current_workspace):
    """Validate policy proof for VERIFIED/CLOSED finding evidence."""
    validate_evidence(record, current_head=current_head,
                      current_workspace=current_workspace, expected_success=True)
    scope = record.get("scope")
    if scope is None:
        _fail("FINDING_SCOPE_MISSING")
    severity = finding.get("severity")
    policy = (impact or {}).get("impact", {})
    if scope != "related":
        return
    required = set(policy.get("required_tests", []))
    covered = set(record.get("covered_tests", []))
    if not required or not required <= covered:
        _fail("RELATED_TEST_COVERAGE_MISSING")
    if severity == "critical":
        closure = finding.get("closure", {})
        if not (closure.get("mode") == "related" and closure.get("critical_related_approved") is True and closure.get("source") == "user" and closure.get("approved_at")):
            _fail("CRITICAL_RELATED_APPROVAL_REQUIRED")
