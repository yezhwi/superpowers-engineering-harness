"""Tampering and freshness checks at the full Context boundary."""

import copy
import json

import pytest
import test_context_builder
from test_context_builder import write_yaml

from harness.context.model import ContextBuildError

harness = test_context_builder.harness


def build(root):
    from harness.context.integrity import build_context

    return build_context(root)


def validate(root, document):
    from harness.context.integrity import validate_context

    return validate_context(root, document)


def add_core_records(root):
    from test_decision import proposal

    from harness import decision

    write_yaml(
        root / "requirements.yaml",
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "statement": "Mandatory global fact",
                    "priority": "must",
                    "status": "pending",
                },
                {
                    "id": "REQ-002",
                    "statement": "Working candidate",
                    "priority": "should",
                    "status": "pending",
                },
            ]
        },
    )
    write_yaml(
        root / "invariants.yaml",
        {
            "invariants": [
                {
                    "id": "INV-001",
                    "statement": "Hidden global invariant",
                    "category": "security",
                    "severity": "minor",
                    "status": "pending",
                },
            ]
        },
    )
    write_yaml(
        root / "findings/FND-001.yaml",
        {
            "id": "FND-001",
            "category": "adversarial",
            "kind": "invariant_violation",
            "target": "INV-001",
            "scenario": "Out-of-scope failure",
            "severity": "minor",
            "status": "PROPOSED",
        },
    )
    record = decision.propose(root, proposal())
    decision.accept(root, record["id"], "redis", "accepted_recommendation")


def test_generated_full_context_validates_without_writes(harness):
    add_core_records(harness)
    before = {str(p): p.read_bytes() for p in harness.rglob("*") if p.is_file()}
    document = build(harness)
    assert validate(harness, document) == {
        "completeness": True,
        "accuracy": True,
        "freshness": True,
        "traceability": True,
    }
    assert document["control"]["gate"]["status"] == "BLOCKED"
    assert document["policy"] == "LOCAL"
    assert document["working"]["requirements"][0]["id"] == "REQ-002"
    assert {str(p): p.read_bytes() for p in harness.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize(
    "field", ["requirements", "invariants", "findings", "decisions"]
)
def test_ci01_to_04_missing_global_records_fail(harness, field):
    add_core_records(harness)
    document = build(harness)
    document["control"][field] = []
    with pytest.raises(ContextBuildError, match="CONTEXT_INCOMPLETE"):
        validate(harness, document)


@pytest.mark.parametrize("field", ["scope", "blockers", "gate", "constraints"])
def test_ci05_to_07_corrupted_control_facts_fail(harness, field):
    document = build(harness)
    document["control"][field] = [] if field == "blockers" else {}
    with pytest.raises(ContextBuildError, match="CONTEXT_INACCURATE"):
        validate(harness, document)


def test_ci07_changed_statement_is_rejected_even_with_same_ids(harness):
    add_core_records(harness)
    document = build(harness)
    document["control"]["requirements"][0]["statement"] = "Weakened constraint"
    with pytest.raises(ContextBuildError, match="CONTEXT_INACCURATE"):
        validate(harness, document)


def test_generated_from_exposes_named_source_hashes_and_manifest_presence(harness):
    document = build(harness)
    generated = document["generated_from"]
    for name in (
        "task_hash",
        "requirements_hash",
        "invariants_hash",
        "findings_hash",
        "decisions_hash",
        "evidence_hash",
        "impact_hash",
    ):
        assert generated[name].startswith("sha256:")
    assert document["manifest"]["sources"]["requirements"]["loaded"] is True
    (harness / "requirements.yaml").unlink()
    missing = build(harness)
    assert missing["manifest"]["sources"]["requirements"]["loaded"] is False
    assert (
        missing["generated_from"]["requirements_hash"] != generated["requirements_hash"]
    )


def test_ci08_bad_reference_is_rejected(harness):
    document = build(harness)
    document["references"]["gate.yaml"]["ref"] = ".harness/missing.yaml"
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        validate(harness, document)


@pytest.mark.parametrize(
    "name",
    [
        "requirements.yaml",
        "gate.yaml",
        "risk-boundaries.yaml",
        "observability.yaml",
        "impact.yaml",
        "current-task.yaml",
    ],
)
def test_ci09_any_control_source_edit_stales_old_context(harness, name):
    document = build(harness)
    with (harness / name).open("a") as stream:
        stream.write("\n# source changed\n")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, document)


def test_ci09_product_change_stales_old_context(harness):
    document = build(harness)
    (harness.parent / "new_product.py").write_text("changed = True\n")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, document)


def test_ci10_omission_requires_reason_and_ref(harness):
    document = build(harness)
    document["omitted"] = [{"id": "REQ-099", "reason": ""}]
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        validate(harness, document)


def test_ci11_schema_rejects_missing_top_level_field(harness):
    document = build(harness)
    del document["control"]
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        validate(harness, document)


@pytest.mark.parametrize("change", ["risk", "policy"])
def test_ci12_risk_and_policy_must_match_authoritative_task(harness, change):
    document = build(harness)
    if change == "risk":
        document["control"]["task"]["risk"]["profile"] = "STRICT"
    else:
        document["policy"] = "EXPANDED"
    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        validate(harness, document)


def test_derived_context_and_telemetry_do_not_self_stale(harness):
    document = build(harness)
    write_yaml(harness / "context/current.yaml", document)
    write_yaml(harness / "context/manifest.yaml", {"generated": True})
    write_yaml(harness / "context/evidence.yaml", {"generated": True})
    (harness / "telemetry.json").write_text(json.dumps({"usage": {"total_tokens": 12}}))
    write_yaml(harness / ".staging/pending.yaml", {"pending": True})
    write_yaml(harness / "history/old.yaml", {"history": True})
    assert validate(harness, document)["freshness"]
    assert build(harness)["context_hash"] == document["context_hash"]


def test_temporary_artifact_write_does_not_stale_context(harness):
    document = build(harness)
    write_yaml(harness / "evidence/.review.yaml.tmp", {"temporary": True})
    assert validate(harness, document)["freshness"]


def test_directory_membership_and_optional_presence_are_freshness_inputs(harness):
    document = build(harness)
    write_yaml(harness / "evidence/extra.yaml", {"metadata": "new"})
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, document)


def test_expansion_source_change_is_not_excluded_as_derived_output(harness):
    document = build(harness)
    write_yaml(
        harness / "context/expansions.yaml", {"task_id": "TASK-028", "expansions": []}
    )
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, document)


def test_build_rejects_source_mutation_during_gate_assessment(harness, monkeypatch):
    from harness import quality_gate

    original = quality_gate.assess_gate

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        with (harness / "requirements.yaml").open("a") as stream:
            stream.write("\n# changed during build\n")
        return result

    monkeypatch.setattr(quality_gate, "assess_gate", mutate)
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        build(harness)


def test_context_hash_detects_unchecked_tampering(harness):
    document = build(harness)
    document["context_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ContextBuildError, match="CONTEXT_INACCURATE"):
        validate(harness, document)


@pytest.mark.parametrize(
    "fragment,records,expected",
    [
        ("REQ-001", [{"id": "REQ-001"}], None),
        ("REQ-002", [{"id": "REQ-001"}], "CONTEXT_REFERENCE_BROKEN"),
        ("REQ-001", [{"id": "REQ-001"}, {"id": "REQ-001"}], "CONTEXT_REFERENCE_BROKEN"),
        ("", [{"id": "REQ-001"}], "CONTEXT_REFERENCE_BROKEN"),
    ],
)
def test_fragment_resolution_requires_exactly_one_record(
    harness, fragment, records, expected
):
    from harness.context.freshness import file_version
    from harness.context.integrity import resolve_reference

    path = harness / "fragments.yaml"
    write_yaml(path, {"records": records})
    reference = {
        "ref": f".harness/fragments.yaml#{fragment}",
        "sha256": file_version(path),
    }
    if expected:
        with pytest.raises(ContextBuildError, match=expected):
            resolve_reference(harness.parent, reference)
    else:
        resolve_reference(harness.parent, reference)


@pytest.mark.parametrize(
    "ref", ["../escape", "/tmp/outside", ".harness/does-not-exist"]
)
def test_invalid_reference_path_is_rejected(harness, ref):
    from harness.context.integrity import resolve_reference

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        resolve_reference(harness.parent, {"ref": ref, "sha256": "sha256:" + "0" * 64})


def test_valid_reference_with_wrong_content_hash_is_stale(harness):
    from harness.context.integrity import resolve_reference

    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        resolve_reference(
            harness.parent,
            {"ref": ".harness/gate.yaml", "sha256": "sha256:" + "0" * 64},
        )


def test_omission_cannot_be_deleted_or_invented_with_valid_ref(harness):
    document = build(harness)
    assert document["omitted"]
    document["omitted"] = []
    with pytest.raises(ContextBuildError, match="CONTEXT_INACCURATE"):
        validate(harness, document)


def test_full_projection_refuses_malformed_expansion_envelope(harness):
    write_yaml(
        harness / "context/expansions.yaml", {"task_id": "TASK-028", "expansions": []}
    )
    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        build(harness)


@pytest.mark.parametrize("declaration", ["owned", "requirement", "finding", "decision"])
def test_explicitly_referenced_ignored_file_changes_stale_context(harness, declaration):
    import yaml
    from test_decision import proposal

    from harness import decision

    path = harness.parent / "private/test_hidden.py"
    path.parent.mkdir()
    path.write_text("# original")
    (harness.parent / ".gitignore").write_text("private/\n")
    if declaration == "owned":
        task = yaml.safe_load((harness / "current-task.yaml").read_text())
        task["scope"]["owned_paths"] = ["private/test_hidden.py"]
        write_yaml(harness / "current-task.yaml", task)
    elif declaration == "requirement":
        write_yaml(
            harness / "requirements.yaml",
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "statement": "Hidden test",
                        "priority": "must",
                        "status": "pending",
                        "test_plan": {
                            "strategies": ["unit"],
                            "cases": [
                                {
                                    "id": "TC-001",
                                    "type": "happy_path",
                                    "strategy": "unit",
                                    "description": "hidden",
                                    "tests": ["private/test_hidden.py::test_case"],
                                }
                            ],
                        },
                    }
                ]
            },
        )
    elif declaration == "finding":
        write_yaml(
            harness / "findings/FND-001.yaml",
            {
                "id": "FND-001",
                "category": "adversarial",
                "kind": "invariant_violation",
                "target": "INV-001",
                "scenario": "hidden",
                "status": "PROPOSED",
                "severity": "minor",
                "regression_test": {"path": "private/test_hidden.py::test_case"},
            },
        )
    else:
        record = decision.propose(
            harness, {**proposal(), "scope": ["private/test_hidden.py"]}
        )
        decision.accept(harness, record["id"], "redis", "accepted_recommendation")
    document = build(harness)
    path.write_text("# changed")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, document)


def test_malformed_record_id_cannot_crash_integrity(harness):
    add_core_records(harness)
    document = build(harness)
    document["control"]["requirements"][0]["id"] = []
    with pytest.raises(ContextBuildError):
        validate(harness, document)


def test_validation_does_not_mutate_supplied_document(harness):
    document = build(harness)
    original = copy.deepcopy(document)
    validate(harness, document)
    assert document == original
