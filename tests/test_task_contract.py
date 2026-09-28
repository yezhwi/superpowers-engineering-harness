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
    schema = _load(
        resources.files("harness").joinpath("schemas", "requirement.schema.json")
    )
    jsonschema.validate(REQUIREMENTS_EXAMPLE, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_requirement_schema_rejects_bad_priority():
    schema = _load(
        resources.files("harness").joinpath("schemas", "requirement.schema.json")
    )
    bad = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "x",
                "priority": "someday",
                "status": "pending",
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_requirement_schema_accepts_optional_test_plan_and_old_record():
    schema = _load(
        resources.files("harness").joinpath("schemas", "requirement.schema.json")
    )
    old = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "old",
                "priority": "must",
                "status": "pending",
            }
        ]
    }
    planned = {
        "requirements": [
            {
                "id": "REQ-002",
                "statement": "new",
                "priority": "must",
                "status": "pending",
                "type": "feature",
                "test_plan": {
                    "strategies": ["unit"],
                    "cases": [
                        {
                            "id": "TC-001",
                            "type": "happy_path",
                            "strategy": "unit",
                            "description": "works",
                        }
                    ],
                },
            }
        ]
    }
    jsonschema.validate(old, schema)
    jsonschema.validate(planned, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_invariant_schema_validates_doc_example():
    schema = _load(
        resources.files("harness").joinpath("schemas", "invariant.schema.json")
    )
    jsonschema.validate(INVARIANTS_EXAMPLE, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_invariant_schema_rejects_bad_category():
    schema = _load(
        resources.files("harness").joinpath("schemas", "invariant.schema.json")
    )
    bad = {
        "invariants": [
            {
                "id": "INV-001",
                "statement": "x",
                "category": "vibes",
                "severity": "major",
                "status": "pending",
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_invariant_schema_keeps_evidence_verification_separate_from_test_plan():
    schema = _load(
        resources.files("harness").joinpath("schemas", "invariant.schema.json")
    )
    planned = {
        "invariants": [
            {
                "id": "INV-001",
                "statement": "safe",
                "category": "correctness",
                "severity": "critical",
                "status": "pending",
                "verification": [],
                "test_plan": {
                    "strategies": ["integration"],
                    "cases": [
                        {
                            "id": "TC-002",
                            "type": "invariant",
                            "strategy": "integration",
                            "description": "holds",
                        }
                    ],
                },
            }
        ]
    }
    jsonschema.validate(planned, schema)


def test_templates_exist_and_parse():
    reqs = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "requirements.yaml")
        .read_text()
    )
    invs = yaml.safe_load(
        resources.files("harness").joinpath("templates", "invariants.yaml").read_text()
    )
    assert isinstance(reqs.get("requirements"), list)
    assert isinstance(invs.get("invariants"), list)


def test_templates_document_test_plan_without_creating_gate_blocking_work():
    requirements_template = (
        resources.files("harness")
        .joinpath("templates", "requirements.yaml")
        .read_text()
    )
    invariants_template = (
        resources.files("harness").joinpath("templates", "invariants.yaml").read_text()
    )
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
    req_schema = _load(
        resources.files("harness").joinpath("schemas", "requirement.schema.json")
    )
    inv_schema = _load(
        resources.files("harness").joinpath("schemas", "invariant.schema.json")
    )
    reqs = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "requirements.yaml")
        .read_text()
    )
    invs = yaml.safe_load(
        resources.files("harness").joinpath("templates", "invariants.yaml").read_text()
    )
    jsonschema.validate(reqs, req_schema)
    jsonschema.validate(invs, inv_schema)


def test_plan_fingerprint_normalizes_omitted_optional_lists():
    from harness.plan_reconciliation import plan_fingerprint

    omitted = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    explicit = {
        "version": 1,
        "items": [
            {
                "id": "P-001",
                "intent": "work",
                "requirement_refs": [],
                "test_case_refs": [],
                "invariant_refs": [],
                "surfaces": [],
            }
        ],
    }

    assert plan_fingerprint(omitted) == plan_fingerprint(explicit)


def test_plan_initialization_accepts_matching_fingerprint_and_short_circuits_stale(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_initialization

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    assert validate_plan_initialization(harness_dir) == []

    execution["plan"]["fingerprint"] = "sha256:" + "0" * 64
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    assert [issue.code for issue in validate_plan_initialization(harness_dir)] == [
        "PLAN_STALE"
    ]


def test_plan_initialization_rejects_execution_item_not_in_plan(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_initialization

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-999": {"status": "PENDING"}},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    assert [issue.code for issue in validate_plan_initialization(harness_dir)] == [
        "PLAN_DISPOSITION_INVALID"
    ]


def test_final_plan_reconciliation_reports_only_unreconciled_nonterminal_item(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "PENDING"}},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    blockers = validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")

    assert [(blocker.code, blocker.source, blocker.recover_to) for blocker in blockers] == [
        ("PLAN_ITEM_UNRECONCILED", "P-001", "IMPLEMENTING")
    ]


def test_final_plan_reconciliation_rejects_supersession_cycle(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "old"},
            {"id": "P-002", "intent": "replacement"},
        ],
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {
            "P-001": {
                "status": "SUPERSEDED",
                "reason": "replaced",
                "superseded_by": ["P-002"],
            },
            "P-002": {
                "status": "SUPERSEDED",
                "reason": "replaced",
                "superseded_by": ["P-001"],
            },
        },
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")] == [
        "PLAN_DISPOSITION_INVALID"
    ]


def test_final_plan_reconciliation_rejects_missing_qualified_parent_case(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {
        "version": 1,
        "items": [{"id": "P-001", "intent": "test", "test_case_refs": ["REQ-001/TC-999"]}],
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "COMPLETE", "evidence_refs": ["unit-test"]}},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump({"requirements": [{"id": "REQ-001", "test_plan": {"cases": []}}]})
    )
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")] == [
        "PLAN_DISPOSITION_INVALID"
    ]


def test_final_plan_reconciliation_requires_item_owned_evidence(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {
        "version": 1,
        "items": [{"id": "P-001", "intent": "test", "test_case_refs": ["REQ-001/TC-001"]}],
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "COMPLETE"}},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump(
            {"requirements": [{"id": "REQ-001", "test_plan": {"cases": [{"id": "TC-001"}]}}]}
        )
    )
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")] == [
        "PLAN_PROOF_MISSING"
    ]


def test_final_plan_reconciliation_rejects_missing_item_evidence_record(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "test", "test_case_refs": ["REQ-001/TC-001"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "evidence_refs": ["missing"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump({"requirements": [{"id": "REQ-001", "test_plan": {"cases": [{"id": "TC-001"}]}}]}))
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")] == ["PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_requires_item_evidence_to_cover_manual_case(tmp_path):
    import json

    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "manual", "test_case_refs": ["REQ-001/TC-001"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    fingerprint = "sha256:" + "0" * 64
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "evidence_refs": ["manual"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump({"requirements": [{"id": "REQ-001", "test_plan": {"cases": [{"id": "TC-001", "strategy": "manual", "tests": []}]}}]}))
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))
    evidence = harness_dir / "evidence"
    evidence.mkdir()
    (evidence / "manual.json").write_text(json.dumps({"type": "unit_test", "timestamp": "2026-01-01T00:00:00+00:00", "command": "true", "exit_code": 0, "commit": "head", "workspace_fingerprint": fingerprint, "workspace_fingerprint_after": fingerprint}))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace=fingerprint)] == ["PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_requires_surface_refs_for_surface_item(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "surface", "surfaces": ["src/example.py"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE"}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")] == ["PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_requires_item_evidence_to_cover_automated_node(tmp_path):
    import json

    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    node = "tests/test_task_contract.py::test_plan_fingerprint_normalizes_omitted_optional_lists"
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "auto", "test_case_refs": ["REQ-001/TC-001"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    fingerprint = "sha256:" + "0" * 64
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "evidence_refs": ["unit"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump({"requirements": [{"id": "REQ-001", "test_plan": {"cases": [{"id": "TC-001", "strategy": "unit", "tests": [node]}]}}]}))
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))
    evidence = harness_dir / "evidence"
    evidence.mkdir()
    (evidence / "unit.json").write_text(json.dumps({"type": "unit_test", "timestamp": "2026-01-01T00:00:00+00:00", "command": "pytest", "exit_code": 0, "commit": "head", "workspace_fingerprint": fingerprint, "workspace_fingerprint_after": fingerprint, "covered_tests": []}))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace=fingerprint)] == ["PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_requires_declared_changed_surface(tmp_path, monkeypatch):
    from harness import plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "surface", "surfaces": ["src/example.py"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_reconciliation.plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "surface_refs": ["src/example.py"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    monkeypatch.setattr(plan_reconciliation, "changed_paths_since", lambda base: ())

    blockers = plan_reconciliation.validate_plan_reconciliation(harness_dir, {"git": {"base_commit": "base"}}, head="head", workspace="ws")

    assert [blocker.code for blocker in blockers] == ["PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_blocks_changed_protected_surface(tmp_path, monkeypatch):
    from harness import plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "surface", "surfaces": ["docs/user.md"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_reconciliation.plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "surface_refs": ["docs/user.md"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    monkeypatch.setattr(plan_reconciliation, "changed_paths_since", lambda base: ("docs/user.md",))
    monkeypatch.setattr(plan_reconciliation, "protected_paths_fingerprint", lambda paths: "changed")
    task = {"git": {"base_commit": "base"}, "risk": {"user_changes": {"paths": ["docs/user.md"], "fingerprint": "stored"}}}

    assert [blocker.code for blocker in plan_reconciliation.validate_plan_reconciliation(harness_dir, task, head="head", workspace="ws")] == ["PLAN_PROTECTED_PATHS_MODIFIED"]


def test_final_plan_reconciliation_keeps_evidence_blocker_with_protected_surface(tmp_path, monkeypatch):
    from harness import plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "mixed", "test_case_refs": ["REQ-001/TC-001"], "surfaces": ["docs/user.md"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_reconciliation.plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "surface_refs": ["docs/user.md"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump({"requirements": [{"id": "REQ-001", "test_plan": {"cases": [{"id": "TC-001", "strategy": "manual", "tests": []}]}}]}))
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))
    monkeypatch.setattr(plan_reconciliation, "changed_paths_since", lambda base: ("docs/user.md",))
    monkeypatch.setattr(plan_reconciliation, "protected_paths_fingerprint", lambda paths: "changed")
    task = {"git": {"base_commit": "base"}, "risk": {"user_changes": {"paths": ["docs/user.md"], "fingerprint": "stored"}}}

    codes = [blocker.code for blocker in plan_reconciliation.validate_plan_reconciliation(harness_dir, task, head="head", workspace="ws")]

    assert codes == ["PLAN_PROTECTED_PATHS_MODIFIED", "PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_excludes_unchanged_protected_surface_from_proof(tmp_path, monkeypatch):
    from harness import plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "surface", "surfaces": ["docs/user.md"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_reconciliation.plan_fingerprint(plan)}, "items": {"P-001": {"status": "COMPLETE", "surface_refs": ["docs/user.md"]}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    monkeypatch.setattr(plan_reconciliation, "changed_paths_since", lambda base: ("docs/user.md",))
    monkeypatch.setattr(plan_reconciliation, "protected_paths_fingerprint", lambda paths: "stored")
    task = {"git": {"base_commit": "base"}, "risk": {"user_changes": {"paths": ["docs/user.md"], "fingerprint": "stored"}}}

    assert [blocker.code for blocker in plan_reconciliation.validate_plan_reconciliation(harness_dir, task, head="head", workspace="ws")] == ["PLAN_PROOF_MISSING"]


def test_final_plan_reconciliation_rejects_missing_requirement_reference(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "skip", "requirement_refs": ["REQ-999"]}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "SKIPPED", "reason": "not needed"}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump({"requirements": []}))
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))

    assert [blocker.code for blocker in validate_plan_reconciliation(harness_dir, {}, head="head", workspace="ws")] == ["PLAN_DISPOSITION_INVALID"]


def test_final_plan_reconciliation_rejects_unaccepted_decision_reference(tmp_path):
    from harness.plan_reconciliation import plan_fingerprint, validate_plan_reconciliation

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "skip"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "SKIPPED", "reason": "decision", "decision_id": "DEC-999"}}}
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    blockers = validate_plan_reconciliation(harness_dir, {"task": {"id": "TASK-058"}}, head="head", workspace="ws")

    assert [blocker.code for blocker in blockers] == ["PLAN_DISPOSITION_INVALID"]


def test_plan_initialization_rejects_duplicate_item_ids(tmp_path):
    from harness.plan_reconciliation import (
        PlanArtifactError,
        plan_fingerprint,
        validate_plan_initialization,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "first"},
            {"id": "P-001", "intent": "different"},
        ],
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(execution))

    with pytest.raises(PlanArtifactError, match="PLAN_ITEM_ID_DUPLICATE"):
        validate_plan_initialization(harness_dir)


@pytest.mark.parametrize("surface", ["", "/tmp/escape", "docs/../secret"])
def test_plan_schema_rejects_non_repository_relative_surface(surface):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    schema = _load(resources.files("harness").joinpath("schemas", "plan.schema.json"))
    document = {"version": 1, "items": [{"id": "P-001", "intent": "work", "surfaces": [surface]}]}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)


def test_load_plan_artifacts_optional_preserves_per_file_absence(tmp_path):
    from harness.plan_reconciliation import load_plan_artifacts

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()

    assert load_plan_artifacts(harness_dir, optional=True) == (None, None)


def test_load_plan_artifacts_optional_rejects_malformed_present_file(tmp_path):
    from harness.plan_reconciliation import PlanArtifactError, load_plan_artifacts

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "plan.yaml").write_text("items: [")

    with pytest.raises(PlanArtifactError, match="PLAN_SCHEMA_INVALID"):
        load_plan_artifacts(harness_dir, optional=True)


@pytest.mark.parametrize(
    "risk,configuration,expected",
    [
        (
            {"level": "Q1", "profile": "FAST"},
            {"enabled": True, "mode": "final"},
            {"enabled": False},
        ),
        (
            {"level": "Q2", "profile": "STANDARD"},
            {"enabled": True, "mode": "final"},
            {"enabled": True, "mode": "final"},
        ),
        (
            {"level": "Q3", "profile": "STRICT"},
            {"enabled": True, "mode": "task_and_final"},
            {"enabled": True, "mode": "task_and_final"},
        ),
        (
            {"level": "Q2", "profile": "STANDARD"},
            None,
            {"enabled": False},
        ),
    ],
)
def test_effective_plan_reconciliation_respects_profile_boundary(
    risk, configuration, expected
):
    from harness.plan_reconciliation import effective_plan_reconciliation

    task = {"risk": risk}
    if configuration is not None:
        task["plan_reconciliation"] = configuration

    assert effective_plan_reconciliation(task) == expected


def test_plan_context_summary_projects_disabled_shape_only():
    from harness.plan_reconciliation import plan_context_summary

    task = {
        "risk": {"profile": "FAST"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }

    assert plan_context_summary(task, None, None, []) == {"enabled": False}


def test_plan_context_summary_uses_first_canonical_nonterminal_item():
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_context_summary, plan_fingerprint

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "done"},
            {"id": "P-002", "intent": "missing"},
            {"id": "P-003", "intent": "pending"},
        ],
    }
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {
            "P-001": {"status": "SKIPPED", "reason": "done"},
            "P-003": {"status": "PENDING"},
        },
    }
    blockers = [
        GateBlocker("PLAN_ITEM_UNRECONCILED", "implementation", "pending")
    ]

    assert plan_context_summary(task, plan, execution, blockers) == {
        "enabled": True,
        "mode": "final",
        "next_plan_item": "P-002",
        "final_status": "blocked",
    }


@pytest.mark.parametrize(
    "plan,execution,blockers,expected_status",
    [
        (None, None, ["PLAN_REQUIRED"], "blocked"),
        (
            {"version": 1, "items": [{"id": "P-001", "intent": "work"}]},
            {
                "version": 1,
                "plan": {
                    "path": ".harness/plan.yaml",
                    "fingerprint": "sha256:" + "0" * 64,
                },
                "items": {"P-001": {"status": "PENDING"}},
            },
            ["PLAN_STALE"],
            "blocked",
        ),
    ],
)
def test_plan_context_summary_does_not_select_item_when_artifacts_untrustworthy(
    plan, execution, blockers, expected_status
):
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_context_summary

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    typed = [GateBlocker(code, "implementation", code) for code in blockers]

    summary = plan_context_summary(task, plan, execution, typed)

    assert summary["next_plan_item"] is None
    assert summary["final_status"] == expected_status


def test_plan_context_summary_ignores_non_plan_blockers_and_keeps_terminal_item_null():
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_context_summary, plan_fingerprint

    task = {
        "risk": {"profile": "STRICT"},
        "plan_reconciliation": {"enabled": True, "mode": "task_and_final"},
    }
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "done"}]}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "SKIPPED", "reason": "done"}},
    }
    blockers = [GateBlocker("EVIDENCE_MISSING", "verification", "missing")]

    assert plan_context_summary(task, plan, execution, blockers) == {
        "enabled": True,
        "mode": "task_and_final",
        "next_plan_item": None,
        "final_status": "pass",
    }


def test_plan_context_summary_keeps_terminal_proof_failure_without_next_item():
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_context_summary, plan_fingerprint

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "done"}]}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "COMPLETE"}},
    }
    blockers = [GateBlocker("PLAN_PROOF_MISSING", "verification", "missing")]

    summary = plan_context_summary(task, plan, execution, blockers)

    assert summary["next_plan_item"] is None
    assert summary["final_status"] == "blocked"


def _load(path):
    import json

    return json.loads(path.read_text())
