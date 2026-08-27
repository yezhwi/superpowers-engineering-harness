"""Single source of truth for Harness evidence proof validity."""

import json
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from pathlib import Path

from jsonschema import ValidationError, validate

SCHEMA = resources.files("harness").joinpath("schemas", "evidence.schema.json")


class EvidenceValidationError(Exception):
    pass


class EvidenceStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    FAILED = "FAILED"


@dataclass(frozen=True)
class EvidenceProjection:
    status: EvidenceStatus
    code: str | None
    record: dict | None
    expected_fingerprint: str | None
    current_fingerprint: str


def _projection(record, *, current_head, current_workspace, expected_success,
                require_current_workspace=True) -> EvidenceProjection:
    try:
        validate(record, json.loads(SCHEMA.read_text()))
    except (OSError, json.JSONDecodeError, ValidationError):
        return EvidenceProjection(EvidenceStatus.INVALID, "EVIDENCE_SCHEMA_INVALID",
                                  record if isinstance(record, dict) else None,
                                  None, current_workspace)
    if record.get("commit") != current_head:
        return EvidenceProjection(EvidenceStatus.STALE, "EVIDENCE_HEAD_MISMATCH",
                                  record, record.get("workspace_fingerprint"), current_workspace)
    before = record.get("workspace_fingerprint")
    after = record.get("workspace_fingerprint_after")
    if before != after or (require_current_workspace and (before != current_workspace or after != current_workspace)):
        return EvidenceProjection(EvidenceStatus.STALE, "EVIDENCE_WORKSPACE_STALE",
                                  record, before, current_workspace)
    if expected_success is not None:
        failed = ((record.get("exit_code") == 0) != expected_success)
        if failed:
            return EvidenceProjection(EvidenceStatus.FAILED, "EVIDENCE_RESULT_MISMATCH",
                                      record, before, current_workspace)
    return EvidenceProjection(EvidenceStatus.FRESH, None, record, before, current_workspace)


def project_evidence(path: Path, current_head: str, current_workspace: str,
                     expected_success: bool | None = True,
                     require_current_workspace: bool = True) -> EvidenceProjection:
    """Classify one Evidence record without mutating Harness state."""
    if not path.is_file():
        return EvidenceProjection(EvidenceStatus.MISSING, "EVIDENCE_MISSING", None,
                                  None, current_workspace)
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return EvidenceProjection(EvidenceStatus.INVALID, "EVIDENCE_SCHEMA_INVALID", None,
                                  None, current_workspace)
    return _projection(record, current_head=current_head,
                       current_workspace=current_workspace,
                       expected_success=expected_success,
                       require_current_workspace=require_current_workspace)


def _fail(code: str) -> None:
    raise EvidenceValidationError(code)


def validate_evidence(record, *, current_head, current_workspace,
                      expected_success=None, finding_id=None, test_id=None,
                      require_current_workspace=True):
    """Fail closed unless record proves required current evidence."""
    projection = _projection(
        record, current_head=current_head, current_workspace=current_workspace,
        expected_success=expected_success,
        require_current_workspace=require_current_workspace,
    )
    if projection.status is not EvidenceStatus.FRESH:
        _fail(projection.code or "EVIDENCE_SCHEMA_INVALID")
    subject = record.get("subject")
    test = record.get("test")
    if (subject is None) != (test is None):
        _fail("EVIDENCE_SCHEMA_INVALID: subject and test must be paired")
    if finding_id is not None and subject != {"kind": "finding", "id": finding_id}:
        _fail("FINDING_SUBJECT_MISMATCH")
    if test_id is not None and (not isinstance(test, dict) or test.get("node_id") != test_id):
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
