"""Risk-aware Working Set selection must never trim the global control core."""

import copy

import pytest
import test_context_builder
import yaml
from test_context_builder import set_profile, write_yaml
from test_context_integrity import add_core_records

from harness.context.model import ContextBuildError

harness = test_context_builder.harness


def requirement(identifier, test=None, priority="should"):
    record = {
        "id": identifier,
        "statement": f"Constraint {identifier}",
        "priority": priority,
        "status": "pending",
    }
    if test:
        record["test_plan"] = {
            "strategies": ["unit"],
            "cases": [
                {
                    "id": "TC-001",
                    "type": "happy_path",
                    "strategy": "unit",
                    "description": "bound test",
                    "tests": [test],
                }
            ],
        }
    return record


def select(root, mode="compact"):
    from harness.context.policy import policy_for_risk
    from harness.context.selector import DeterministicSelector
    from harness.context.source import FileContextSource

    source = FileContextSource(root).load()
    return source, DeterministicSelector().select(
        source, policy_for_risk(source.task["risk"]), mode=mode
    )


@pytest.mark.parametrize(
    "level,profile,want",
    [
        ("Q1", "FAST", "LOCAL"),
        ("Q2", "STANDARD", "BOUNDED"),
        ("Q3", "STRICT", "EXPANDED"),
    ],
)
def test_risk_policy_mapping(level, profile, want):
    from harness.context.policy import policy_for_risk

    assert policy_for_risk({"level": level, "profile": profile}) == want


@pytest.mark.parametrize(
    "risk",
    [
        None,
        {},
        {"level": "Q0", "profile": "FAST"},
        {"level": "Q1", "profile": "STRICT"},
    ],
)
def test_invalid_risk_cannot_select_context_policy(risk):
    from harness.context.policy import policy_for_risk

    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        policy_for_risk(risk)


def test_optional_requirements_need_path_or_open_finding_binding(harness):
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["scope"]["owned_paths"] = ["tests/foo"]
    write_yaml(harness / "current-task.yaml", task)
    records = [
        requirement("REQ-001", "tests/foo/test_x.py::test_case"),
        requirement("REQ-002", "tests/foobar/test_x.py"),
        requirement("REQ-003"),
        requirement("REQ-004"),
        requirement("REQ-005", priority="must"),
    ]
    write_yaml(harness / "requirements.yaml", {"requirements": records})
    write_yaml(
        harness / "findings/FND-001.yaml",
        {
            "id": "FND-001",
            "category": "adversarial",
            "kind": "requirement_violation",
            "target": "REQ-003",
            "scenario": "requires context",
            "severity": "minor",
            "status": "PROPOSED",
        },
    )
    _, selected = select(harness)
    assert [r["id"] for r in selected.working["requirements"]] == ["REQ-001", "REQ-003"]
    omitted = {r["id"]: r for r in selected.omitted}
    assert {"REQ-002", "REQ-004"} <= omitted.keys()
    assert omitted["REQ-002"]["ref"] == ".harness/requirements.yaml#REQ-002"
    assert omitted["REQ-002"]["reason"] == "unrelated_to_scope"
    assert "REQ-005" not in omitted


@pytest.mark.parametrize(
    "owner,path,want",
    [
        ("src/foo", "src/foo/a.py", True),
        ("src/foo", "src/foobar/a.py", False),
        ("./src/foo/", "src/foo/a.py::test_case", True),
        ("src/foo.py", "src/foo.py::test_case", True),
        ("src/foo/**", "src/foo/a.py", True),
    ],
)
def test_path_binding_uses_segments_not_raw_string_prefix(owner, path, want):
    from harness.context.selector import path_is_owned

    assert path_is_owned(path, [owner]) is want


def test_closed_finding_and_nonaccepted_decision_are_omitted(harness):
    from test_decision import proposal

    from harness import decision

    record = decision.propose(harness, proposal())
    write_yaml(
        harness / "findings/FND-001.yaml",
        {
            "id": "FND-001",
            "category": "adversarial",
            "kind": "requirement_violation",
            "target": "REQ-001",
            "scenario": "disproved",
            "severity": "minor",
            "status": "REJECTED",
            "attempts": ["checked guard"],
            "rejection_reason": "guard present",
        },
    )
    _, selected = select(harness)
    assert selected.working["decisions"] == []
    assert selected.working["findings"] == []
    assert {row["id"] for row in selected.omitted} >= {record["id"], "FND-001"}
    _, full = select(harness, "full")
    assert len(full.working["decisions"]) == len(full.working["findings"]) == 1


@pytest.mark.parametrize("level,expected", [("Q1", False), ("Q2", True), ("Q3", True)])
def test_dependencies_and_declared_contracts_require_bounded_policy(
    harness, level, expected
):
    set_profile(harness, level)
    write_yaml(
        harness / "impact.yaml",
        {
            "impact": {
                "changed": ["src/local.py"],
                "direct_dependents": ["src/dependency.py"],
                "contracts": ["docs/api.yaml"],
                "required_tests": ["tests/local.py::test_case"],
            }
        },
    )
    _, selected = select(harness)
    assert "src/local.py" in selected.working["files"]
    assert "tests/local.py::test_case" in selected.working["tests"]
    assert ("src/dependency.py" in selected.working["files"]) is expected
    assert ("docs/api.yaml" in selected.working["files"]) is expected
    if not expected:
        assert {row["id"] for row in selected.omitted} >= {
            "file:src/dependency.py",
            "file:docs/api.yaml",
        }


def test_local_does_not_list_broad_repo_docs_or_test_scope(harness):
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["scope"]["owned_paths"] = [".", "docs", "tests/**", "src/local.py"]
    write_yaml(harness / "current-task.yaml", task)
    write_yaml(
        harness / "impact.yaml",
        {"impact": {"required_tests": ["tests"], "changed": ["docs"]}},
    )
    _, selected = select(harness)
    assert selected.working["files"] == ["src/local.py"]
    assert selected.working["tests"] == []
    assert any(
        r["reason"] == "broad_context_requires_expansion" for r in selected.omitted
    )
    assert not (harness / "context").exists()


@pytest.mark.parametrize(
    "state,profile,action",
    [
        ("CLASSIFIED", "FAST", "implement"),
        ("CLASSIFIED", "STANDARD", "specify_contract"),
        ("IMPLEMENTING", "FAST", "implement_and_record_impact"),
        ("VERIFYING", "STANDARD", "collect_verification"),
        ("REVIEWING", "STRICT", "review_and_record_outcome"),
        ("GATING", "STANDARD", "run_gate"),
        ("BLOCKED", "FAST", "resume_from_blocker"),
        ("CONVERGED", "STANDARD", "transition_done"),
        ("DONE", "STANDARD", "none"),
        ("CREATED", "STANDARD", "classify_task"),
        ("SPECIFYING", "STANDARD", "specify_contract"),
        ("PLANNED", "STANDARD", "record_minimal_implementation"),
        ("REPRODUCING", "STRICT", "reproduce_finding"),
        ("FIXING", "STRICT", "fix_confirmed_finding"),
        ("ESCALATED", "STRICT", "await_human"),
    ],
)
def test_next_action_comes_from_state_and_profile(state, profile, action):
    from harness.context.policy import next_action

    assert next_action(state, profile) == action


def test_selector_cannot_mutate_source_or_inject_policy(harness):
    from harness.context.selector import DeterministicSelector

    add_core_records(harness)
    source, selected = select(harness)
    before = copy.deepcopy(source.task)
    selected.working["files"].append("injected.py")
    assert source.task == before
    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        DeterministicSelector().select(source, "EXPANDED")


def test_compact_validates_and_keeps_control_identical_to_full(harness):
    from harness.context.integrity import build_context, validate_context

    add_core_records(harness)
    full = build_context(harness)
    compact = build_context(harness, mode="compact")
    assert compact["mode"] == "compact"
    assert compact["control"] == full["control"]
    assert compact["working"]["requirements"] == []
    assert compact["manifest"]["sources"]["requirements"]["included"] == 1
    assert compact["manifest"]["sources"]["requirements"]["total"] == 2
    assert any(r["id"] == "REQ-002" for r in compact["omitted"])
    assert validate_context(harness, compact)["completeness"]
    compact["working"]["files"].append("docs")
    with pytest.raises(ContextBuildError, match="CONTEXT_INACCURATE"):
        validate_context(harness, compact)


def test_injected_selector_cannot_mutate_authoritative_core(harness):
    from harness.context.integrity import build_context
    from harness.context.selector import DeterministicSelector

    add_core_records(harness)

    class MutatingSelector:
        def select(self, source, policy, *, mode="compact"):
            source.requirements[0]["statement"] = "Weakened MUST"
            return DeterministicSelector().select(source, policy, mode=mode)

    document = build_context(harness, mode="compact", selector=MutatingSelector())
    assert (
        document["control"]["requirements"][0]["statement"] == "Mandatory global fact"
    )


def test_injected_selector_cannot_silently_drop_omissions(harness):
    from harness.context.integrity import build_context
    from harness.context.selector import ContextSelection, DeterministicSelector

    add_core_records(harness)

    class IncompleteSelector:
        def select(self, source, policy, *, mode="compact"):
            selected = DeterministicSelector().select(source, policy, mode=mode)
            return ContextSelection(selected.working, [])

    with pytest.raises(ContextBuildError, match="CONTEXT_INACCURATE"):
        build_context(harness, mode="compact", selector=IncompleteSelector())


@pytest.mark.parametrize(
    "path",
    [
        "../tests/test_x.py",
        "/tests/test_x.py",
        "C:/tests/test_x.py",
        "tests\\\\test_x.py",
    ],
)
def test_noncanonical_test_path_cannot_bind_to_owned_scope(path):
    from harness.context.selector import path_is_owned

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        path_is_owned(path, ["tests"])


def test_unsupported_owner_glob_does_not_guess_requirement_relevance():
    from harness.context.selector import path_is_owned

    assert not path_is_owned("tests/foo/test_x.py", ["tests/*/test_x.py"])


@pytest.mark.parametrize("state,profile", [("UNKNOWN", "FAST"), ("GATING", "UNSAFE")])
def test_unknown_dispatch_fails_closed(state, profile):
    from harness.context.policy import next_action

    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        next_action(state, profile)


def test_protected_only_file_is_not_selected_as_owned(harness):
    _, selected = select(harness)
    assert "notes/user.md" not in selected.working["files"]
    assert any(r["id"] == "file:notes/user.md" for r in selected.omitted)
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["scope"]["owned_paths"].append("notes/user.md")
    write_yaml(harness / "current-task.yaml", task)
    _, selected = select(harness)
    assert "notes/user.md" in selected.working["files"]
    assert not any(r["id"] == "file:notes/user.md" for r in selected.omitted)


@pytest.mark.parametrize("field", ["changed", "required_tests", "direct_dependents"])
def test_invalid_impact_path_list_is_rejected(harness, field):
    write_yaml(harness / "impact.yaml", {"impact": {field: "not-a-list"}})
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        select(harness)


def test_unknown_selection_mode_is_rejected(harness):
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        select(harness, mode="unchecked")


def test_declared_but_unselected_test_and_file_paths_are_accounted(harness):
    from test_decision import proposal

    from harness import decision

    write_yaml(
        harness / "requirements.yaml",
        {"requirements": [requirement("REQ-001", "tests/other.py::test_case")]},
    )
    decision.propose(harness, {**proposal(), "scope": ["src/proposed.py"]})
    write_yaml(
        harness / "findings/FND-001.yaml",
        {
            "id": "FND-001",
            "category": "adversarial",
            "kind": "requirement_violation",
            "target": "REQ-001",
            "scenario": "disproved",
            "severity": "minor",
            "status": "REJECTED",
            "attempts": ["checked guard"],
            "rejection_reason": "guard present",
            "regression_test": {"path": "tests/rejected.py"},
            "location": {"file": "src/rejected.py"},
        },
    )
    _, selected = select(harness)
    omitted = {row["id"] for row in selected.omitted}
    assert omitted >= {
        "test:tests/other.py::test_case",
        "file:src/proposed.py",
        "test:tests/rejected.py",
        "file:src/rejected.py",
    }
    assert "src/proposed.py" not in selected.working["files"]
    assert "tests/other.py::test_case" not in selected.working["tests"]


def test_duplicate_dependency_does_not_override_local_changed_file(harness):
    write_yaml(
        harness / "impact.yaml",
        {
            "impact": {
                "changed": ["src/local.py"],
                "direct_dependents": ["src/local.py"],
            }
        },
    )
    _, selected = select(harness)
    assert selected.working["files"].count("src/local.py") == 1
    assert not any(r["id"] == "file:src/local.py" for r in selected.omitted)


def test_compact_omitted_mandatory_record_cannot_pass_even_with_ref(harness):
    from harness.context.integrity import build_context, validate_context

    add_core_records(harness)
    compact = build_context(harness, mode="compact")
    compact["control"]["requirements"] = []
    compact["omitted"].append(
        {
            "id": "REQ-001",
            "reason": "wrongly_filtered",
            **compact["references"]["requirements.yaml"],
        }
    )
    with pytest.raises(ContextBuildError, match="CONTEXT_INCOMPLETE"):
        validate_context(harness, compact)
