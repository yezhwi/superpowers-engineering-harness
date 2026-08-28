"""Milestone 4: Task Contract skill tests.

Covers:
- schemas/requirement.schema.json validates doc §8 examples
- schemas/invariant.schema.json validates doc §9 examples
- templates/requirements.yaml and templates/invariants.yaml exist and parse
- skills/task-contract/SKILL.md exists with required sections
- CREATED -> SPECIFYING -> PLANNED transitions are legal
"""

from importlib import resources
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


REQUIREMENTS_EXAMPLE = {
    "requirements": [
        {
            "id": "REQ-001",
            "statement": "interrupted execution can resume",
            "source": "user",
            "priority": "must",
            "status": "pending",
            "evidence": [],
        },
        {
            "id": "REQ-002",
            "statement": "duplicated recovery must not duplicate side effects",
            "source": "spec",
            "priority": "should",
            "status": "pending",
            "evidence": [],
        },
    ]
}

INVARIANTS_EXAMPLE = {
    "invariants": [
        {
            "id": "INV-001",
            "statement": "one action_id can produce at most one side effect",
            "category": "idempotency",
            "severity": "critical",
            "status": "pending",
            "verification": ["build.json"],
        },
    ]
}


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_requirement_schema_validates_doc_example():
    schema = _load(resources.files("harness").joinpath("schemas", "requirement.schema.json"))
    jsonschema.validate(REQUIREMENTS_EXAMPLE, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_requirement_schema_rejects_bad_priority():
    schema = _load(resources.files("harness").joinpath("schemas", "requirement.schema.json"))
    bad = {"requirements": [{"id": "REQ-001", "statement": "x",
                             "priority": "someday", "status": "pending"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_requirement_schema_accepts_optional_test_plan_and_old_record():
    schema = _load(resources.files("harness").joinpath("schemas", "requirement.schema.json"))
    old = {"requirements": [{"id": "REQ-001", "statement": "old", "priority": "must", "status": "pending"}]}
    planned = {"requirements": [{
        "id": "REQ-002", "statement": "new", "priority": "must", "status": "pending",
        "type": "feature", "test_plan": {"strategies": ["unit"], "cases": [{
            "id": "TC-001", "type": "happy_path", "strategy": "unit", "description": "works",
        }]},
    }]}
    jsonschema.validate(old, schema)
    jsonschema.validate(planned, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_invariant_schema_validates_doc_example():
    schema = _load(resources.files("harness").joinpath("schemas", "invariant.schema.json"))
    jsonschema.validate(INVARIANTS_EXAMPLE, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_invariant_schema_rejects_bad_category():
    schema = _load(resources.files("harness").joinpath("schemas", "invariant.schema.json"))
    bad = {"invariants": [{"id": "INV-001", "statement": "x",
                           "category": "vibes", "severity": "major",
                           "status": "pending"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_invariant_schema_keeps_evidence_verification_separate_from_test_plan():
    schema = _load(resources.files("harness").joinpath("schemas", "invariant.schema.json"))
    planned = {"invariants": [{
        "id": "INV-001", "statement": "safe", "category": "correctness",
        "severity": "critical", "status": "pending", "verification": [],
        "test_plan": {"strategies": ["integration"], "cases": [{
            "id": "TC-002", "type": "invariant", "strategy": "integration", "description": "holds",
        }]},
    }]}
    jsonschema.validate(planned, schema)


def test_templates_exist_and_parse():
    reqs = yaml.safe_load(resources.files("harness").joinpath("templates", "requirements.yaml").read_text())
    invs = yaml.safe_load(resources.files("harness").joinpath("templates", "invariants.yaml").read_text())
    assert isinstance(reqs.get("requirements"), list)
    assert isinstance(invs.get("invariants"), list)


def test_templates_document_test_plan_without_creating_gate_blocking_work():
    requirements_template = resources.files("harness").joinpath("templates", "requirements.yaml").read_text()
    invariants_template = resources.files("harness").joinpath("templates", "invariants.yaml").read_text()
    assert yaml.safe_load(requirements_template) == {"requirements": []}
    assert yaml.safe_load(invariants_template) == {"invariants": []}
    assert "test_plan:" in requirements_template
    assert "strategy: unit" in requirements_template
    assert "test_plan:" in invariants_template
    assert "strategy: integration" in invariants_template


def test_skill_md_exists_with_required_sections():
    text = (REPO / "skills" / "task-contract" / "SKILL.md").read_text()
    for token in (
        "task-contract",
        "Acceptance Criteria",
        "Invariants",
        "Risks",
        "Verification Plan",
        ".harness/requirements.yaml",
        ".harness/invariants.yaml",
        "SPECIFYING",
        "PLANNED",
    ):
        assert token in text, f"missing section/token: {token}"


def test_skill_forbids_implementation():
    text = (REPO / "skills" / "task-contract" / "SKILL.md").read_text().lower()
    assert "must not" in text or "不得" in text


def test_task_contract_state_path_is_legal():
    from harness.state_machine import require_legal

    require_legal("CREATED", "SPECIFYING")
    require_legal("SPECIFYING", "PLANNED")


def test_templates_validate_against_schemas():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    req_schema = _load(resources.files("harness").joinpath("schemas", "requirement.schema.json"))
    inv_schema = _load(resources.files("harness").joinpath("schemas", "invariant.schema.json"))
    reqs = yaml.safe_load(resources.files("harness").joinpath("templates", "requirements.yaml").read_text())
    invs = yaml.safe_load(resources.files("harness").joinpath("templates", "invariants.yaml").read_text())
    jsonschema.validate(reqs, req_schema)
    jsonschema.validate(invs, inv_schema)


def _load(path):
    import json

    return json.loads(path.read_text())
