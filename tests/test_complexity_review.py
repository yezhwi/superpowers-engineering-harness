"""v0.2 complexity finding persistence."""

import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from complexity import validate_complexity_finding


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


@pytest.mark.parametrize("kind", ["delete", "reuse", "stdlib", "native", "yagni", "shrink"])
def test_complexity_taxonomy_is_valid(kind):
    """Break caught: a supported taxonomy type is rejected."""
    validate_complexity_finding(finding(type=kind))


def test_accepted_complexity_finding_requires_reason():
    """Break caught: acceptance bypasses evidence-backed justification."""
    with pytest.raises(ValidationError):
        validate_complexity_finding(finding(status="accepted"))


def test_complexity_finding_requires_concrete_evidence():
    """Break caught: reviewer can emit unsupported complexity claim."""
    unsupported = finding()
    del unsupported["evidence"]
    with pytest.raises(ValidationError):
        validate_complexity_finding(unsupported)
