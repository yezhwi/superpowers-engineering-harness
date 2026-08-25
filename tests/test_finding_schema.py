"""Finding schema covers the full lifecycle (review fix #4).

Each status has a representative, realistic finding record that MUST
validate against schemas/finding.schema.json.
"""

import json
from importlib import resources

import pytest

jsonschema = pytest.importorskip("jsonschema")

SCHEMA = json.loads(resources.files("harness").joinpath("schemas", "finding.schema.json").read_text())


def validate(finding: dict) -> None:
    jsonschema.validate(finding, SCHEMA)


BASE = {
    "id": "FND-001",
    "kind": "invariant_violation",
    "target": "INV-001",
    "scenario": "duplicate side effect under concurrent pickup",
    "severity": "critical",
}


def test_proposed_minimal():
    validate({**BASE, "status": "PROPOSED"})


def test_reproducing_with_attempts():
    validate({**BASE, "status": "REPRODUCING",
              "attempts": ["ran race twice with N=8 workers: reproduced 1/2"]})


def test_confirmed_with_red_test():
    validate({**BASE, "status": "CONFIRMED",
              "test": "tests/test_x.py::test_dup",
              "regression_test": {"path": "tests/test_x.py::test_dup", "red_evidence": "red.json"},
              "confirmed_at": "2026-01-01T00:00:00+00:00"})


def test_fixing_and_fixed():
    validate({**BASE, "status": "FIXING",
              "test": "tests/test_x.py::test_dup",
              "regression_test": {"path": "tests/test_x.py::test_dup", "red_evidence": "red.json"}})
    validate({**BASE, "status": "FIXED",
              "fix": "per-id lock",
              "regression_test": {
                  "path": "tests/test_x.py::test_dup",
                  "red_evidence": "run#1 RED",
                  "green_evidence": "run#2 GREEN"}})


def test_verified_and_closed():
    common = {"test": "t", "fix": "f",
              "regression_test": {"path": "t", "red_evidence": "red.json", "green_evidence": "green.json"}}
    validate({**BASE, "status": "VERIFIED", **common,
              "evidence": ".harness/evidence/unit-test.json",
              "verified_at": "2026-01-02T00:00:00+00:00"})
    validate({**BASE, "status": "CLOSED", **common,
              "evidence": ".harness/evidence/unit-test.json", "verified_at": "2026-01-02T00:00:00+00:00"})


def test_rejected_requires_attempts_and_reason():
    validate({**BASE, "status": "REJECTED",
              "attempts": ["a", "b"],
              "rejection_reason": "guard at worker.py:42 blocks duplicates"})


def test_unknown_status_rejected_by_schema():
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        validate({**BASE, "status": "MAGIC"})


def test_fnd_rejects_complexity_status_and_severity():
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        validate({**BASE, "severity": "high", "status": "PROPOSED"})
    with pytest.raises(ValidationError):
        validate({**BASE, "status": "open"})
