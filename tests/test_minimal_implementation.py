"""v0.2 Minimal Implementation Decision contract."""

import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from complexity import validate_minimal_decision, write_minimal_decision


def _check(result: str, checked: bool = True, **extra) -> dict:
    return {"checked": checked, "result": result, **extra}


def _local_decision() -> dict:
    return {
        "version": 1,
        "task": "TASK-004",
        "checks": {
            "existence": _check("required"),
            "reuse": _check("none"),
            "stdlib": _check("none"),
            "native": _check("none"),
            "existing_dependency": _check("none"),
            "minimum_local_implementation": _check("required"),
        },
        "decision": {
            "approach": "local_implementation",
            "rationale": "No earlier capability satisfies requirement.",
        },
    }


def _skipped() -> dict:
    return _check("skipped", checked=False)


def test_reuse_short_circuits_ladder():
    """Break caught: later search runs after repository reuse was found."""
    decision = _local_decision()
    decision["checks"]["reuse"] = _check("found", candidate="src/date.py")
    for name in (
        "stdlib",
        "native",
        "existing_dependency",
        "minimum_local_implementation",
    ):
        decision["checks"][name] = _skipped()
    decision["decision"] = {
        "approach": "reuse",
        "rationale": "src/date.py already formats dates.",
    }

    validate_minimal_decision(decision)


def test_found_reuse_rejects_non_skipped_later_check():
    """Break caught: short circuit no longer prevents unnecessary checks."""
    decision = _local_decision()
    decision["checks"]["reuse"] = _check("found", candidate="src/date.py")
    decision["decision"] = {"approach": "reuse", "rationale": "existing formatter"}

    with pytest.raises(ValidationError, match="short-circuit"):
        validate_minimal_decision(decision)


def test_unnecessary_decision_requires_unnecessary_existence():
    """Break caught: non-required work can be misrepresented as unnecessary."""
    decision = _local_decision()
    decision["decision"]["approach"] = "unnecessary"

    with pytest.raises(ValidationError, match="existence"):
        validate_minimal_decision(decision)


def test_write_minimal_decision_uses_required_evidence_path(tmp_path):
    """Break caught: decision records persist outside canonical evidence path."""
    harness_dir = tmp_path / ".harness"

    path = write_minimal_decision(harness_dir, _local_decision())

    assert path == harness_dir / "evidence" / "minimal-implementation.yaml"
    assert path.is_file()
