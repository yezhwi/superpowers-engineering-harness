"""Regression tests for v0.2.7 formal Code Review blocking fixes."""

import json
from pathlib import Path

import pytest
import yaml

from harness.quality_gate import validate_schema
from harness.test_plan import validate_test_coverage
from test_convergence_cli import make_repo, run_cli


def test_gating_cannot_transition_to_converged_or_blocked(tmp_path):
    make_repo(tmp_path, state="GATING")
    converged = run_cli(tmp_path, "transition", "CONVERGED")
    blocked = run_cli(tmp_path, "transition", "BLOCKED")
    assert converged.returncode == 1
    assert "GATE_DECISION_REQUIRED" in converged.stderr
    assert blocked.returncode == 1
    assert "GATE_DECISION_REQUIRED" in blocked.stderr
    task = yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())
    assert task["state"] == "GATING"


def test_lint_covered_tests_do_not_satisfy_automated_bindings():
    issues = validate_test_coverage(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "test_plan": {
                        "strategies": ["unit"],
                        "cases": [
                            {
                                "id": "TC-001",
                                "strategy": "unit",
                                "tests": ["tests/foo.py::test_bar"],
                            }
                        ],
                    },
                }
            ]
        },
        {"invariants": []},
        [
            {
                "type": "lint",
                "covered_tests": ["tests/foo.py::test_bar"],
                "command": "true",
                "exit_code": 0,
            }
        ],
        lambda record: True,
    )
    assert {issue.code for issue in issues} == {"TEST_EVIDENCE_MISSING"}


def test_pytest_without_selector_does_not_cover_bindings():
    issues = validate_test_coverage(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "test_plan": {
                        "strategies": ["unit"],
                        "cases": [
                            {
                                "id": "TC-001",
                                "strategy": "unit",
                                "tests": ["tests/foo.py::test_bar"],
                            }
                        ],
                    },
                }
            ]
        },
        {"invariants": []},
        [
            {
                "type": "unit_test",
                "covered_tests": ["tests/foo.py::test_bar"],
                "command": "pytest tests",
                "exit_code": 0,
            }
        ],
        lambda record: True,
    )
    assert {issue.code for issue in issues} == {"TEST_EVIDENCE_MISSING"}


def test_finding_path_escape_is_rejected(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING")
    result = run_cli(
        tmp_path,
        "evidence",
        "--type",
        "unit_test",
        "--finding",
        "../escape",
        "--test",
        "tests/foo.py::test_bar",
        "--phase",
        "red",
        "--command",
        "true",
    )
    assert result.returncode == 2
    assert "FINDING_ID_INVALID" in result.stderr
    assert not (tmp_path / "escape-red-unit-test.json").exists()
    assert not list((tmp_path / ".harness/evidence").glob("*escape*"))


def test_attach_type_cannot_escape_evidence_directory(tmp_path):
    make_repo(tmp_path, state="IMPLEMENTING")
    result = run_cli(
        tmp_path,
        "evidence",
        "attach",
        "--type",
        "../../tmp/pwned",
        "--command",
        "true",
        "--result-file",
        str(tmp_path / "missing.json"),
    )
    assert result.returncode == 2


def test_interface_finding_schema_accepts_closure_fields():
    validate_schema(
        {
            "id": "FND-001",
            "kind": "requirement_violation",
            "category": "interface",
            "target": "REQ-001",
            "scenario": "public DTO leak",
            "severity": "major",
            "status": "CONFIRMED",
            "location": {"file": "src/api.py", "line": 1},
            "test": "tests/test_api.py::test_dto",
            "confirmed_at": "2026-01-01T00:00:00+00:00",
            "regression_test": {
                "path": "tests/test_api.py::test_dto",
                "red_evidence": "FND-001-red-unit-test.json",
            },
        },
        "interface-finding.schema.json",
        Path("findings/FND-001.yaml"),
    )


def test_resume_review_rejects_non_mapping_finding_yaml(tmp_path):
    make_repo(tmp_path, state="REPRODUCING")
    findings = tmp_path / ".harness" / "findings"
    findings.mkdir(exist_ok=True)
    (findings / "FND-001.yaml").write_text("- not-a-mapping\n")
    result = run_cli(tmp_path, "finding", "resume-review", "FND-001")
    assert result.returncode == 2
    assert "FINDING_STATE_INVALID" in result.stderr
