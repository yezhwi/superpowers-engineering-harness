"""v0.2 complexity finding persistence."""

import json
import sys
from pathlib import Path

import yaml

import pytest
from jsonschema import ValidationError

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from complexity import validate_complexity_finding, write_complexity_review


def finding(**changes):
    base = {
        "id": "CPLX-001",
        "category": "complexity",
        "type": "reuse",
        "severity": "high",
        "status": "open",
        "location": {"file": "src/date_helper.py", "line": 12},
        "summary": "Duplicate date formatter.",
        "reason": "src/date.py already exports format_date.",
        "evidence": {"existing_candidate": "src/date.py"},
        "recommendation": "Reuse format_date.",
    }
    return {**base, **changes}


@pytest.mark.parametrize(
    "kind", ["delete", "reuse", "stdlib", "native", "yagni", "shrink"]
)
def test_complexity_taxonomy_is_valid(kind):
    """Break caught: a supported taxonomy type is rejected."""
    validate_complexity_finding(finding(type=kind))


def test_accepted_complexity_finding_requires_reason():
    """Break caught: acceptance bypasses evidence-backed justification."""
    with pytest.raises(ValidationError):
        validate_complexity_finding(finding(status="accepted"))


def test_complexity_validator_rejects_adversarial_finding():
    with pytest.raises(ValidationError):
        validate_complexity_finding(
            {
                "id": "FND-001",
                "kind": "failure_scenario",
                "target": "REQ-001",
                "scenario": "wrong consumer",
                "severity": "major",
                "status": "PROPOSED",
            }
        )


def audit_checks(result="pass"):
    return {
        name: {"result": result, "evidence": "reviewed"}
        for name in ("delete", "reuse", "stdlib", "native", "yagni", "shrink")
    }


def test_complexity_audit_requires_all_dimension_decisions(tmp_path):
    harness_dir = tmp_path / ".harness"
    review = {"task": "TASK-004", "checks": audit_checks(), "findings": []}
    write_complexity_review(harness_dir, review)
    metadata = json.loads((harness_dir / "evidence/complexity-review.json").read_text())
    assert metadata["checks"]["reuse"]["result"] == "pass"


def test_complexity_failed_check_requires_finding(tmp_path):
    harness_dir = tmp_path / ".harness"
    checks = audit_checks()
    checks["yagni"]["result"] = "fail"
    with pytest.raises(ValidationError):
        write_complexity_review(
            harness_dir, {"task": "TASK-004", "checks": checks, "findings": []}
        )


def test_write_complexity_review_persists_findings_and_metadata(tmp_path):
    """Break caught: review output does not become gate-readable records."""
    harness_dir = tmp_path / ".harness"
    review = {
        "task": "TASK-004",
        "base": "HEAD~1",
        "head": "HEAD",
        "findings": [finding()],
    }

    paths = write_complexity_review(harness_dir, review)

    assert paths == [harness_dir / "findings" / "CPLX-001.yaml"]
    assert yaml.safe_load(paths[0].read_text())["type"] == "reuse"
    metadata = json.loads(
        (harness_dir / "evidence" / "complexity-review.json").read_text()
    )
    assert metadata["type"] == "review"
    assert metadata["finding_ids"] == ["CPLX-001"]


def test_complexity_review_validation_failure_leaves_no_canonical_artifacts(tmp_path):
    harness_dir = tmp_path / ".harness"
    invalid = finding(id="CPLX-002")
    del invalid["evidence"]

    with pytest.raises(ValidationError):
        write_complexity_review(
            harness_dir,
            {"task": "TASK-004", "findings": [finding(), invalid]},
        )

    assert not list((harness_dir / "findings").glob("CPLX-*.yaml"))
    assert not (harness_dir / "evidence" / "complexity-review.json").exists()


def test_complexity_finding_requires_concrete_evidence():
    """Break caught: reviewer can emit unsupported complexity claim."""
    unsupported = finding()
    del unsupported["evidence"]
    with pytest.raises(ValidationError):
        validate_complexity_finding(unsupported)
