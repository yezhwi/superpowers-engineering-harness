"""Production diagnosability contract tests."""

from importlib import resources

from pathlib import Path

import pytest
import yaml

from harness.diagnosability import load_contract, validate_contract


VALID_REQUIRED = {
    "version": 1,
    "required": True,
    "applicability": {
        "reasons": ["external_dependency"],
        "inspected_paths": ["src/pay.py"],
    },
    "business_keys": ["order_id"],
    "failure_boundaries": ["payment_refund"],
    "external_dependencies": [
        {
            "name": "payment_gateway",
            "operations": ["refund"],
            "required_context": ["dependency", "operation", "order_id"],
        }
    ],
}


def test_required_contract_needs_business_key_failure_boundary_and_dimension():
    with pytest.raises(ValueError, match="OBSERVABILITY_CONTRACT_INVALID"):
        validate_contract(
            {
                "version": 1,
                "required": True,
                "applicability": {
                    "reasons": ["external_dependency"],
                    "inspected_paths": ["src/pay.py"],
                },
                "business_keys": ["order_id"],
                "failure_boundaries": [],
            },
            task_type="feature",
        )


def test_bugfix_gap_false_rejects_improvement_fields():
    with pytest.raises(ValueError, match="OBSERVABILITY_CONTRACT_INVALID"):
        validate_contract(
            {
                "version": 1,
                "required": False,
                "applicability": {
                    "reasons": ["pure_calculation"],
                    "inspected_paths": ["src/math.py"],
                },
                "bug_fix": {
                    "observability_gap": False,
                    "basis": "existing trace has order id",
                    "improvement": "add log",
                },
            },
            task_type="bugfix",
        )


def test_bugfix_gap_false_is_valid_without_logging_improvement():
    document = {
        "version": 1,
        "required": False,
        "applicability": {
            "reasons": ["pure_calculation"],
            "inspected_paths": ["src/math.py"],
        },
        "bug_fix": {
            "observability_gap": False,
            "basis": "existing trace identifies order id and failure boundary",
        },
    }

    validate_contract(document, task_type="bugfix")


def test_required_contract_accepts_external_dependency_dimension():
    validate_contract(VALID_REQUIRED, task_type="feature")


def test_bugfix_contract_loads_with_task_type(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "observability.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "required": False,
                "applicability": {
                    "reasons": ["pure_calculation"],
                    "inspected_paths": ["src/math.py"],
                },
                "bug_fix": {
                    "observability_gap": False,
                    "basis": "existing context identifies failure boundary",
                },
            }
        )
    )

    assert (
        load_contract(harness, task_type="bugfix")["bug_fix"]["observability_gap"]
        is False
    )


def test_load_contract_rejects_missing_artifact(tmp_path):
    with pytest.raises(ValueError, match="OBSERVABILITY_CONTRACT_INVALID"):
        load_contract(tmp_path / ".harness")


@pytest.mark.parametrize(
    "fixture", Path("tests/fixtures/diagnosability").glob("*.yaml")
)
def test_fixture_contracts_validate(fixture):
    case = yaml.safe_load(fixture.read_text())
    validate_contract(case["contract"], task_type=case["task_type"])


def test_review_readiness_rejects_contract_mismatch():
    from harness.diagnosability import validate_review_readiness

    with pytest.raises(ValueError, match="DIAG_CONTRACT_REQUIRED_MISMATCH"):
        validate_review_readiness(
            {"required": True},
            {"contract_required": False, "checks": {}, "finding_ids": []},
            [],
            scope_files=(),
        )


def test_review_readiness_rejects_not_applicable_required_dimension():
    from harness.diagnosability import validate_review_readiness

    with pytest.raises(ValueError, match="DIAG_NOT_APPLICABLE_INVALID"):
        validate_review_readiness(
            {"required": True, "business_keys": ["order_id"]},
            {
                "contract_required": True,
                "checks": {"business_keys": "not_applicable"},
                "finding_ids": [],
            },
            [],
            scope_files=(),
        )


def test_review_readiness_rejects_failed_check_without_linked_finding():
    from harness.diagnosability import validate_review_readiness

    with pytest.raises(ValueError, match="DIAG_FINDING_REQUIRED"):
        validate_review_readiness(
            {
                "required": True,
                "business_keys": ["order_id"],
                "failure_boundaries": ["payment"],
                "critical_events": ["created"],
            },
            {
                "contract_required": True,
                "checks": {"business_keys": "fail"},
                "finding_ids": [],
            },
            [],
            scope_files=("src/order.py",),
        )


def test_review_readiness_rejects_failed_check_without_listed_finding():
    from harness.diagnosability import validate_review_readiness

    finding = {
        "id": "FND-001",
        "category": "diagnosability",
        "location": {"file": "src/order.py"},
        "compliance": {"required_checks": ["business_keys"]},
    }
    with pytest.raises(ValueError, match="DIAG_FINDING_REQUIRED"):
        validate_review_readiness(
            {"required": True},
            {
                "contract_required": True,
                "checks": {"business_keys": "fail"},
                "finding_ids": [],
            },
            [finding],
            scope_files=("src/order.py",),
        )


def test_default_template_is_schema_valid_initial_contract():
    document = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "observability.yaml")
        .read_text()
    )

    validate_contract(document, task_type=None)
