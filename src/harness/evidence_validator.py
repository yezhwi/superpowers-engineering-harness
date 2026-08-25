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
                      expected_success=None, finding_id=None, test_id=None):
    """Fail closed unless record proves required current evidence."""
    try:
        validate(record, json.loads(SCHEMA.read_text()))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise EvidenceValidationError(f"EVIDENCE_SCHEMA_INVALID: {exc}") from exc
    if record.get("commit") != current_head:
        _fail("EVIDENCE_HEAD_MISMATCH")
    before = record.get("workspace_fingerprint")
    after = record.get("workspace_fingerprint_after")
    if before != current_workspace or after != current_workspace or before != after:
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
