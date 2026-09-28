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


def _requirements_with_cases(cases: list[dict]) -> dict:
    normalized = [
        {
            "id": case["id"],
            "type": "contract",
            "strategy": case.get("strategy", "unit"),
            "description": "plan reconciliation fixture",
            **({"tests": case["tests"]} if "tests" in case else {}),
        }
        for case in cases
    ]
    return {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "Plan item has qualified proof",
                "priority": "must",
                "status": "pending",
                "test_plan": {
                    "strategies": sorted(
                        {case["strategy"] for case in normalized} or {"unit"}
                    ),
                    "cases": normalized,
                },
            }
        ]
    }


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


@pytest.mark.parametrize("missing", ["both", "plan", "execution"])
def test_plan_reconciliation_documents_preserves_missing_short_circuit(
    tmp_path, missing
):
    from harness.plan_reconciliation import (
        plan_fingerprint,
        validate_plan_reconciliation_documents,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-999": {"status": "PENDING"}},
    }
    selected_plan = None if missing in {"both", "plan"} else plan
    selected_execution = None if missing in {"both", "execution"} else execution

    blockers = validate_plan_reconciliation_documents(
        harness_dir,
        {},
        selected_plan,
        selected_execution,
        head="head",
        workspace="ws",
    )

    assert [blocker.code for blocker in blockers] == ["PLAN_REQUIRED"]


def test_plan_reconciliation_documents_preserves_stale_before_unknown_item(tmp_path):
    from harness.plan_reconciliation import validate_plan_reconciliation_documents

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": "sha256:" + "0" * 64},
        "items": {"P-999": {"status": "PENDING"}},
    }

    blockers = validate_plan_reconciliation_documents(
        harness_dir, {}, plan, execution, head="head", workspace="ws"
    )

    assert [blocker.code for blocker in blockers] == ["PLAN_STALE"]


def test_plan_reconciliation_documents_preserves_unknown_item_short_circuit(tmp_path):
    from harness.plan_reconciliation import (
        plan_fingerprint,
        validate_plan_reconciliation_documents,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-999": {"status": "PENDING"}},
    }

    blockers = validate_plan_reconciliation_documents(
        harness_dir, {}, plan, execution, head="head", workspace="ws"
    )

    assert [blocker.code for blocker in blockers] == ["PLAN_DISPOSITION_INVALID"]


def test_plan_reconciliation_documents_preserves_supersession_short_circuit(tmp_path):
    from harness.plan_reconciliation import (
        plan_fingerprint,
        validate_plan_reconciliation_documents,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "old"},
            {"id": "P-002", "intent": "replacement"},
        ],
    }
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

    blockers = validate_plan_reconciliation_documents(
        harness_dir, {}, plan, execution, head="head", workspace="ws"
    )

    assert [(blocker.code, blocker.source) for blocker in blockers] == [
        ("PLAN_DISPOSITION_INVALID", "P-001")
    ]


def test_plan_reconciliation_documents_matches_pending_wrapper_shape(tmp_path):
    from harness.plan_reconciliation import (
        plan_fingerprint,
        validate_plan_reconciliation_documents,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "PENDING"}},
    }

    blockers = validate_plan_reconciliation_documents(
        harness_dir, {}, plan, execution, head="head", workspace="ws"
    )

    assert [(blocker.code, blocker.source, blocker.recover_to) for blocker in blockers] == [
        ("PLAN_ITEM_UNRECONCILED", "P-001", "IMPLEMENTING")
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
        yaml.safe_dump(_requirements_with_cases([]))
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
        yaml.safe_dump(_requirements_with_cases([{"id": "TC-001"}]))
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
    (harness_dir / "requirements.yaml").write_text(yaml.safe_dump(_requirements_with_cases([{"id": "TC-001"}])))
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
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump(
            _requirements_with_cases(
                [{"id": "TC-001", "strategy": "manual", "tests": []}]
            )
        )
    )
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
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump(
            _requirements_with_cases(
                [{"id": "TC-001", "strategy": "unit", "tests": [node]}]
            )
        )
    )
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
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump(
            _requirements_with_cases(
                [{"id": "TC-001", "strategy": "manual", "tests": []}]
            )
        )
    )
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


def test_plan_status_report_projects_disabled_shape_without_inspecting_documents():
    from harness.plan_reconciliation import plan_status_report

    task = {
        "risk": {"profile": "FAST"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }

    assert plan_status_report(task, {"invalid": object()}, {"invalid": object()}, []) == {
        "enabled": False
    }


def test_plan_status_report_projects_missing_artifacts_without_bodies():
    import json

    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_status_report

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    blocker = GateBlocker(
        "PLAN_REQUIRED",
        "implementation",
        "enabled task requires plan artifacts",
        recover_to="IMPLEMENTING",
    )

    report = plan_status_report(task, None, None, [blocker])

    assert report == {
        "enabled": True,
        "mode": "final",
        "plan": {
            "present": False,
            "execution_present": False,
            "fingerprint": None,
            "execution_fingerprint": None,
            "fingerprint_fresh": None,
        },
        "progress": None,
        "next_plan_item": None,
        "final_status": "blocked",
        "blockers": [
            {
                "code": "PLAN_REQUIRED",
                "source": None,
                "message": "enabled task requires plan artifacts",
            }
        ],
    }
    serialized = json.dumps(report)
    assert '"items"' not in serialized
    assert '"intent"' not in serialized
    assert '"surfaces"' not in serialized
    assert '"evidence_refs"' not in serialized


def test_plan_status_report_projects_stale_fingerprints_without_progress():
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_fingerprint, plan_status_report

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    stale = "sha256:" + "0" * 64
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": stale},
        "items": {"P-001": {"status": "COMPLETE"}},
    }
    blocker = GateBlocker(
        "PLAN_STALE",
        "implementation",
        "plan fingerprint does not match canonical plan",
        recover_to="IMPLEMENTING",
    )

    report = plan_status_report(task, plan, execution, [blocker])

    assert report["plan"] == {
        "present": True,
        "execution_present": True,
        "fingerprint": plan_fingerprint(plan),
        "execution_fingerprint": stale,
        "fingerprint_fresh": False,
    }
    assert report["progress"] is None
    assert report["next_plan_item"] is None
    assert report["final_status"] == "blocked"
    assert [row["code"] for row in report["blockers"]] == ["PLAN_STALE"]


def test_plan_status_report_counts_only_persisted_trustworthy_statuses():
    from harness.blockers import GateBlocker
    from harness.plan_reconciliation import plan_fingerprint, plan_status_report

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    plan = {
        "version": 1,
        "items": [
            {"id": f"P-{number:03}", "intent": "work"} for number in range(1, 8)
        ],
    }
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {
            "P-002": {"status": "PENDING"},
            "P-003": {"status": "IN_PROGRESS"},
            "P-004": {"status": "COMPLETE"},
            "P-005": {"status": "SKIPPED", "reason": "not needed"},
            "P-006": {
                "status": "SUPERSEDED",
                "reason": "replaced",
                "superseded_by": ["P-004"],
            },
            "P-007": {"status": "BLOCKED"},
        },
    }
    proof = GateBlocker(
        "PLAN_PROOF_MISSING",
        "verification",
        "complete test item lacks item-owned evidence",
        source="P-004",
        recover_to="VERIFYING",
    )

    report = plan_status_report(task, plan, execution, [proof])

    assert list(report["progress"]["statuses"]) == [
        "PENDING",
        "IN_PROGRESS",
        "COMPLETE",
        "SKIPPED",
        "SUPERSEDED",
        "BLOCKED",
    ]
    assert report["progress"] == {
        "total": 7,
        "reconciled": 3,
        "statuses": {
            "PENDING": 1,
            "IN_PROGRESS": 1,
            "COMPLETE": 1,
            "SKIPPED": 1,
            "SUPERSEDED": 1,
            "BLOCKED": 1,
        },
    }
    assert report["next_plan_item"] == "P-001"
    assert report["final_status"] == "blocked"


def test_plan_status_report_delegates_next_and_final_to_context_summary(monkeypatch):
    from harness import plan_reconciliation

    task = {
        "risk": {"profile": "STANDARD"},
        "plan_reconciliation": {"enabled": True, "mode": "final"},
    }
    plan = {"version": 1, "items": []}
    execution = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_reconciliation.plan_fingerprint(plan),
        },
        "items": {},
    }
    calls = []

    def summary(*args):
        calls.append(args)
        return {
            "enabled": True,
            "mode": "final",
            "next_plan_item": "P-999",
            "final_status": "blocked",
        }

    monkeypatch.setattr(plan_reconciliation, "plan_context_summary", summary)

    report = plan_reconciliation.plan_status_report(task, plan, execution, [])

    assert calls == [(task, plan, execution, ())]
    assert report["next_plan_item"] == "P-999"
    assert report["final_status"] == "blocked"


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


def _plan_assessment_task(profile: str, mode: str) -> dict:
    return {
        "task": {"id": "TASK-062"},
        "risk": {"profile": profile, "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64}},
        "git": {"base_commit": "HEAD"},
        "plan_reconciliation": {"enabled": True, "mode": mode},
    }


def _execution_v1(plan: dict, items: dict | None = None) -> dict:
    from harness.plan_reconciliation import plan_fingerprint

    return {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": items or {},
    }


def _execution_v2(
    plan: dict,
    *,
    sequence: int = 0,
    transitions: list[dict] | None = None,
    items: dict | None = None,
) -> dict:
    from harness.plan_reconciliation import plan_fingerprint

    return {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "sequence": sequence,
        "transitions": transitions or [],
        "items": items or {},
    }


@pytest.mark.parametrize(
    ("task", "plan", "execution", "expected", "final_expected"),
    [
        (
            _plan_assessment_task("STRICT", "task_and_final"),
            None,
            None,
            "PLAN_REQUIRED",
            "PLAN_REQUIRED",
        ),
        (
            _plan_assessment_task("STRICT", "task_and_final"),
            {"version": 1, "items": []},
            {
                "version": 2,
                "plan": {"path": ".harness/plan.yaml", "fingerprint": "sha256:" + "0" * 64},
                "sequence": 0,
                "transitions": [],
                "items": {},
            },
            "PLAN_STALE",
            "PLAN_STALE",
        ),
        (
            _plan_assessment_task("STANDARD", "final"),
            {"version": 1, "items": []},
            _execution_v2({"version": 1, "items": []}, sequence=1),
            "PLAN_DISPOSITION_INVALID",
            "PLAN_DISPOSITION_INVALID",
        ),
        (
            _plan_assessment_task("STRICT", "task_and_final"),
            {"version": 1, "items": []},
            _execution_v1({"version": 1, "items": []}),
            "PLAN_TASK_LEVEL_REQUIRED",
            None,
        ),
        (
            _plan_assessment_task("STRICT", "task_and_final"),
            {"version": 1, "items": []},
            _execution_v2({"version": 1, "items": []}, sequence=1),
            "PLAN_SEQUENCE_INVALID",
            None,
        ),
        (
            _plan_assessment_task("STRICT", "task_and_final"),
            {"version": 1, "items": [{"id": "P-001", "intent": "work"}]},
            _execution_v2({"version": 1, "items": [{"id": "P-001", "intent": "work"}]}),
            "PLAN_ITEM_UNRECONCILED",
            "PLAN_ITEM_UNRECONCILED",
        ),
    ],
)
def test_plan_assessment_preserves_task_level_early_return_precedence(
    tmp_path, task, plan, execution, expected, final_expected
):
    from harness.plan_reconciliation import assess_plan_reconciliation_documents

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    assessment = assess_plan_reconciliation_documents(
        harness_dir,
        task,
        plan,
        execution,
        head="head",
        workspace="sha256:" + "f" * 64,
    )

    assert [blocker.code for blocker in assessment.blockers] == [expected]
    assert [blocker.code for blocker in assessment.final_blockers] == (
        [] if final_expected is None else [final_expected]
    )
    if expected in {"PLAN_TASK_LEVEL_REQUIRED", "PLAN_SEQUENCE_INVALID"}:
        blocker = assessment.blockers[0]
        assert (blocker.category, blocker.source, blocker.recover_to) == (
            "implementation",
            None,
            "IMPLEMENTING",
        )
        assert assessment.projection is None


def test_plan_task_level_blockers_have_implementing_recovery_policy():
    from harness.blockers import RECOVERY_POLICY

    assert RECOVERY_POLICY["PLAN_TASK_LEVEL_REQUIRED"] == "IMPLEMENTING"
    assert RECOVERY_POLICY["PLAN_SEQUENCE_INVALID"] == "IMPLEMENTING"


def test_validate_plan_reconciliation_documents_delegates_public_assessment(tmp_path):
    from harness.plan_reconciliation import validate_plan_reconciliation_documents

    plan = {"version": 1, "items": []}
    blockers = validate_plan_reconciliation_documents(
        tmp_path,
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        _execution_v1(plan),
        head="head",
        workspace="sha256:" + "f" * 64,
    )

    assert [blocker.code for blocker in blockers] == ["PLAN_TASK_LEVEL_REQUIRED"]


def _q3_begin() -> dict:
    return {
        "sequence": 1,
        "item": "P-001",
        "from": "PENDING",
        "to": "IN_PROGRESS",
        "action": "BEGIN",
    }


def _q3_decision_receipt() -> dict:
    return {
        "decision_id": "DEC-031",
        "sha256": "sha256:" + "d" * 64,
        "task_id": "TASK-062",
        "status": "ACCEPTED",
    }


def _q3_proof_receipt(
    *, head: str, workspace: str, evidence: list[dict] | None = None
) -> dict:
    return {
        "head": head,
        "workspace": workspace,
        "evidence": evidence or [],
        "surface_refs": [],
    }


def test_q3_replay_valid_nonterminal_uses_existing_p0_blocker(tmp_path):
    from harness.plan_reconciliation import assess_plan_reconciliation_documents

    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    execution = _execution_v2(
        plan,
        sequence=1,
        transitions=[_q3_begin()],
        items={"P-001": {"status": "IN_PROGRESS"}},
    )

    assessment = assess_plan_reconciliation_documents(
        tmp_path,
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        execution,
        head="head",
        workspace="sha256:" + "f" * 64,
    )

    assert [blocker.code for blocker in assessment.blockers] == [
        "PLAN_ITEM_UNRECONCILED"
    ]
    assert assessment.projection == {"P-001": {"status": "IN_PROGRESS"}}


def test_q3_replay_valid_skip_requires_current_accepted_decision(tmp_path):
    from harness.plan_reconciliation import assess_plan_reconciliation_documents

    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    skip = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "SKIPPED",
        "action": "RECONCILE",
        "reason": "removed",
        "decision_id": "DEC-031",
        "decision_receipt": _q3_decision_receipt(),
    }
    items = {
        "P-001": {
            "status": "SKIPPED",
            "reason": "removed",
            "decision_id": "DEC-031",
        }
    }
    execution = _execution_v2(
        plan, sequence=2, transitions=[_q3_begin(), skip], items=items
    )

    assessment = assess_plan_reconciliation_documents(
        tmp_path,
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        execution,
        head="head",
        workspace="sha256:" + "f" * 64,
    )

    assert [blocker.code for blocker in assessment.blockers] == [
        "PLAN_DISPOSITION_INVALID"
    ]


def test_q3_replay_valid_complete_requires_latest_receipt_current_workspace(
    tmp_path, monkeypatch
):
    from harness import plan_reconciliation

    workspace = "sha256:" + "f" * 64
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "surface", "surfaces": ["src/example.py"]}
        ],
    }
    receipt = _q3_proof_receipt(head="old-head", workspace=workspace)
    receipt["surface_refs"] = ["src/example.py"]
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": [],
        "surface_refs": ["src/example.py"],
        "proof_receipt": receipt,
    }
    items = {
        "P-001": {"status": "COMPLETE", "surface_refs": ["src/example.py"]}
    }
    execution = _execution_v2(
        plan, sequence=2, transitions=[_q3_begin(), complete], items=items
    )
    monkeypatch.setattr(
        plan_reconciliation, "changed_paths_since", lambda base: ("src/example.py",)
    )

    assessment = plan_reconciliation.assess_plan_reconciliation_documents(
        tmp_path,
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        execution,
        head="current-head",
        workspace=workspace,
    )

    assert [blocker.code for blocker in assessment.blockers] == [
        "PLAN_PROOF_MISSING"
    ]


def test_q3_replay_valid_complete_requires_latest_receipt_evidence_bytes(tmp_path):
    import hashlib
    import json

    from harness.plan_reconciliation import assess_plan_reconciliation_documents

    harness_dir = tmp_path / ".harness"
    evidence_dir = harness_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    workspace = "sha256:" + "f" * 64
    evidence = {
        "type": "unit_test",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "command": "pytest tests/test_task_contract.py",
        "exit_code": 0,
        "commit": "head",
        "workspace_fingerprint": workspace,
        "workspace_fingerprint_after": workspace,
        "covered_test_cases": ["TC-001"],
    }
    evidence_bytes = json.dumps(evidence).encode()
    (evidence_dir / "unit.json").write_bytes(evidence_bytes)
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump(
            _requirements_with_cases(
                [{"id": "TC-001", "strategy": "manual", "tests": []}]
            )
        )
    )
    (harness_dir / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))
    plan = {
        "version": 1,
        "items": [
            {
                "id": "P-001",
                "intent": "test",
                "test_case_refs": ["REQ-001/TC-001"],
            }
        ],
    }
    receipt_entry = {
        "ref": "unit",
        "sha256": "sha256:" + hashlib.sha256(b"different").hexdigest(),
        "type": "unit_test",
        "exit_code": 0,
        "commit": "head",
        "workspace_fingerprint": workspace,
    }
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": ["unit"],
        "surface_refs": [],
        "proof_receipt": _q3_proof_receipt(
            head="head", workspace=workspace, evidence=[receipt_entry]
        ),
    }
    items = {
        "P-001": {"status": "COMPLETE", "evidence_refs": ["unit"]}
    }
    execution = _execution_v2(
        plan, sequence=2, transitions=[_q3_begin(), complete], items=items
    )

    assessment = assess_plan_reconciliation_documents(
        harness_dir,
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        execution,
        head="head",
        workspace=workspace,
    )

    assert [blocker.code for blocker in assessment.blockers] == [
        "PLAN_PROOF_MISSING"
    ]


def test_task_aware_plan_initialization_requires_empty_q3_v2(tmp_path):
    from harness.plan_reconciliation import (
        plan_fingerprint,
        validate_plan_initialization,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    (harness_dir / "plan-execution.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "plan": {
                    "path": ".harness/plan.yaml",
                    "fingerprint": plan_fingerprint(plan),
                },
                "items": {"P-001": {"status": "PENDING"}},
            }
        )
    )

    issues = validate_plan_initialization(
        harness_dir, _plan_assessment_task("STRICT", "task_and_final")
    )

    assert [issue.code for issue in issues] == ["PLAN_TASK_LEVEL_REQUIRED"]


def test_task_aware_plan_initialization_accepts_q2_v1_and_empty_q3_v2(tmp_path):
    from harness.plan_reconciliation import (
        plan_fingerprint,
        validate_plan_initialization,
    )

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    v1 = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {"P-001": {"status": "PENDING"}},
    }
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(v1))

    assert validate_plan_initialization(
        harness_dir, _plan_assessment_task("STANDARD", "final")
    ) == []

    empty = _execution_v2(plan)
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(empty))
    assert validate_plan_initialization(
        harness_dir, _plan_assessment_task("STRICT", "task_and_final")
    ) == []


def test_task_aware_plan_initialization_rejects_q2_v2_and_progressed_q3_v2(tmp_path):
    from harness.plan_reconciliation import validate_plan_initialization

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "work"}]}
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan))
    empty = _execution_v2(plan)
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(empty))

    assert [
        issue.code
        for issue in validate_plan_initialization(
            harness_dir, _plan_assessment_task("STANDARD", "final")
        )
    ] == ["PLAN_DISPOSITION_INVALID"]

    progressed = _execution_v2(
        plan,
        sequence=1,
        transitions=[_q3_begin()],
        items={"P-001": {"status": "IN_PROGRESS"}},
    )
    (harness_dir / "plan-execution.yaml").write_text(yaml.safe_dump(progressed))
    assert [
        issue.code
        for issue in validate_plan_initialization(
            harness_dir, _plan_assessment_task("STRICT", "task_and_final")
        )
    ] == ["PLAN_SEQUENCE_INVALID"]


def test_task_aware_plan_initialization_disabled_does_not_read_plan_files(tmp_path):
    from harness.plan_reconciliation import validate_plan_initialization

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "plan.yaml").write_text("[")
    (harness_dir / "plan-execution.yaml").write_text("[")
    task = _plan_assessment_task("FAST", "task_and_final")

    assert validate_plan_initialization(harness_dir, task) == []


def test_q3_replay_valid_current_surface_receipt_can_pass_p0(tmp_path, monkeypatch):
    from harness import plan_reconciliation

    workspace = "sha256:" + "f" * 64
    plan = {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "surface", "surfaces": ["src/example.py"]}
        ],
    }
    receipt = _q3_proof_receipt(head="head", workspace=workspace)
    receipt["surface_refs"] = ["src/example.py"]
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": [],
        "surface_refs": ["src/example.py"],
        "proof_receipt": receipt,
    }
    items = {
        "P-001": {"status": "COMPLETE", "surface_refs": ["src/example.py"]}
    }
    execution = _execution_v2(
        plan, sequence=2, transitions=[_q3_begin(), complete], items=items
    )
    monkeypatch.setattr(
        plan_reconciliation, "changed_paths_since", lambda base: ("src/example.py",)
    )

    assessment = plan_reconciliation.assess_plan_reconciliation_documents(
        tmp_path,
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        execution,
        head="head",
        workspace=workspace,
    )

    assert assessment.blockers == ()
    assert assessment.final_blockers == ()


def test_plan_status_task_level_blocker_hides_progress_but_keeps_independent_final_pass():
    from harness.plan_reconciliation import (
        assess_plan_reconciliation_documents,
        plan_fingerprint,
        plan_status_report,
    )

    plan = {"version": 1, "items": []}
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "items": {},
    }
    task = _plan_assessment_task("STRICT", "task_and_final")
    assessment = assess_plan_reconciliation_documents(
        Path(".harness"), task, plan, execution, head="head", workspace="workspace"
    )

    report = plan_status_report(task, plan, execution, assessment)

    assert [blocker["code"] for blocker in report["blockers"]] == [
        "PLAN_TASK_LEVEL_REQUIRED"
    ]
    assert report["progress"] is None
    assert report["next_plan_item"] is None
    assert report["final_status"] == "pass"


def test_plan_status_sequence_invalid_hides_persisted_projection():
    from harness.plan_reconciliation import (
        assess_plan_reconciliation_documents,
        plan_fingerprint,
        plan_status_report,
    )

    plan = {"version": 1, "items": []}
    execution = {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "sequence": 1,
        "transitions": [],
        "items": {},
    }
    task = _plan_assessment_task("STRICT", "task_and_final")
    assessment = assess_plan_reconciliation_documents(
        Path(".harness"), task, plan, execution, head="head", workspace="workspace"
    )

    report = plan_status_report(task, plan, execution, assessment)

    assert [blocker["code"] for blocker in report["blockers"]] == [
        "PLAN_SEQUENCE_INVALID"
    ]
    assert report["progress"] is None
    assert report["next_plan_item"] is None
    assert report["final_status"] == "pass"


def test_plan_status_uses_assessment_projection_and_omits_journal_bodies():
    import json

    from harness.plan_reconciliation import (
        PlanAssessment,
        plan_fingerprint,
        plan_status_report,
    )

    plan = {
        "version": 1,
        "items": [{"id": "P-001", "intent": "work", "surfaces": ["src/x.py"]}],
    }
    execution = {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)},
        "sequence": 0,
        "transitions": [],
        "items": {},
    }
    assessment = PlanAssessment(
        blockers=(),
        final_blockers=(),
        projection={"P-001": {"status": "IN_PROGRESS"}},
        replay=None,
    )

    report = plan_status_report(
        _plan_assessment_task("STRICT", "task_and_final"),
        plan,
        execution,
        assessment,
    )
    encoded = json.dumps(report)

    assert report["progress"]["statuses"]["IN_PROGRESS"] == 1
    assert report["next_plan_item"] == "P-001"
    for secret in ("transitions", "sequence", "proof_receipt", "decision_receipt"):
        assert secret not in encoded
