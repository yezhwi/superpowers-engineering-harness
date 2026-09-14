"""Control Core projects recorded facts, never status fallbacks or summaries."""

import copy
import hashlib
import json
import random
import subprocess

import pytest
import yaml
from test_decision import proposal
from test_interface_contract import contract

from harness import decision, interface_contract, quality_gate, workspace
from harness.init import init_harness


def write_yaml(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))


def set_profile(root, level):
    path = root / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["risk"]["level"] = level
    task["risk"]["profile"] = {"Q1": "FAST", "Q2": "STANDARD", "Q3": "STRICT"}[level]
    write_yaml(path, task)
    return task


@pytest.fixture
def harness(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "base",
        ],
        check=True,
    )
    init_harness(tmp_path)
    root = tmp_path / ".harness"
    task = yaml.safe_load((root / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-028"
    task["state"] = "CLASSIFIED"
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": {
            "scope": "low",
            "contract": "none",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        },
        "escalation_history": [],
        "user_changes": {
            "paths": [],
            "fingerprint": workspace.protected_paths_fingerprint((), tmp_path),
        },
    }
    task["git"]["base_commit"] = workspace.git_head(tmp_path)
    task["scope"] = {
        "owned_paths": ["src/local.py"],
        "protected_user_paths": ["notes/user.md"],
    }
    # Persisted PASS is intentionally false: builder must use live preflight.
    task["gate"] = {"status": "PASS", "blocked_by": []}
    write_yaml(root / "current-task.yaml", task)
    write_yaml(root / "requirements.yaml", {"requirements": []})
    write_yaml(root / "invariants.yaml", {"invariants": []})
    monkeypatch.chdir(tmp_path)
    return root


def load_and_build(root):
    from harness.context.builder import build_control_core
    from harness.context.source import FileContextSource

    source = FileContextSource(root).load()
    return source, build_control_core(source)


def test_core_keeps_must_statement_invariant_scope_and_authorizations(harness):
    must = {
        "id": "REQ-001",
        "statement": "必须保留：跨模块权限不可绕过。",
        "priority": "must",
        "status": "pending",
    }
    should = {
        "id": "REQ-002",
        "statement": "Optional UI",
        "priority": "should",
        "status": "pending",
    }
    invariant = {
        "id": "INV-001",
        "statement": "Other module must remain idempotent",
        "category": "idempotency",
        "severity": "minor",
        "status": "violated",
    }
    write_yaml(harness / "requirements.yaml", {"requirements": [should, must]})
    write_yaml(harness / "invariants.yaml", {"invariants": [invariant]})
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    source, core = load_and_build(harness)
    assert core["requirements"] == [must]
    assert core["invariants"] == [invariant]
    assert source.requirements == [should, must]  # working candidates not discarded
    assert core["task"] == {
        "id": "TASK-028",
        "state": "CLASSIFIED",
        "risk": task["risk"],
    }
    assert core["scope"] == task["scope"]
    assert core["authorizations"] == task["authorizations"]
    assert core["constraints"] == task["risk"]["dimensions"]


def test_core_includes_complete_accepted_decisions_and_open_findings(harness):
    accepted = decision.propose(harness, proposal())
    accepted = decision.accept(
        harness, accepted["id"], "redis", "accepted_recommendation"
    )
    decision.propose(harness, proposal(topic="deferred"))
    records = []
    for i, status in enumerate(
        ("PROPOSED", "REPRODUCING", "CONFIRMED", "FIXING", "FIXED"), 1
    ):
        record = {
            "id": f"FND-{i:03}",
            "category": "adversarial",
            "kind": "invariant_violation",
            "target": "INV-001",
            "scenario": "Hidden dependency outside local scope",
            "severity": "minor",
            "status": status,
            "regression_test": {
                "path": "tests/other.py::test_hidden",
                "red_evidence": "red.json",
                "green_evidence": "green.json",
            },
            "test": "tests/other.py::test_hidden",
            "fix": "fix description",
            "confirmed_at": "2026-01-01T00:00:00+00:00",
        }
        records.append(record)
        write_yaml(harness / "findings" / f"{record['id']}.yaml", record)
    rejected = {
        **records[0],
        "id": "FND-006",
        "status": "REJECTED",
        "attempts": ["checked guard"],
        "rejection_reason": "guard prevents scenario",
    }
    write_yaml(harness / "findings/FND-006.yaml", rejected)
    source, core = load_and_build(harness)
    assert core["decisions"] == [accepted]
    assert core["findings"] == records
    assert source.findings[-1] == rejected
    assert len(source.decisions) == 2
    assert all("affected_requirements" not in finding for finding in core["findings"])


def test_live_blocked_gate_is_projected_without_mutation(harness):
    before = {str(p): p.read_bytes() for p in harness.rglob("*") if p.is_file()}
    source, core = load_and_build(harness)
    assert core["gate"]["status"] == "BLOCKED"
    assert core["blockers"] == core["gate"]["blocked_by"]
    assert any(
        b["code"] == "FAST_REGRESSION_EVIDENCE_MISSING" for b in core["blockers"]
    )
    assert source.gate.status == "BLOCKED"
    after = {str(p): p.read_bytes() for p in harness.rglob("*") if p.is_file()}
    assert after == before


def test_contracts_and_observability_use_hashed_source_refs(harness):
    declared = interface_contract.declare(harness, contract())
    write_yaml(
        harness / "impact.yaml", {"impact": {"contracts": ["docs/future-api.yaml"]}}
    )
    _, core = load_and_build(harness)
    ref = core["contracts"]["interfaces"][0]
    assert ref["id"] == declared["id"]
    assert ref["ref"] == ".harness/interface-contracts/INT-001.yaml"
    assert (
        ref["sha256"]
        == "sha256:"
        + hashlib.sha256(
            (harness / "interface-contracts/INT-001.yaml").read_bytes()
        ).hexdigest()
    )
    assert "inputs" not in ref  # no duplicated contract body in Layer 0
    assert core["contracts"]["impact"][0]["path"] == "docs/future-api.yaml"
    assert core["contracts"]["impact"][0]["ref"] == ".harness/impact.yaml"
    assert core["observability"]["required"] is False
    assert (
        core["observability"]["applicability"]["ref"] == ".harness/observability.yaml"
    )


def test_evidence_summary_keeps_failure_and_staleness_without_raw_output(harness):
    current = workspace.snapshot()
    base = {
        "type": "build",
        "timestamp": "2026-01-01T00:00:00Z",
        "command": "false",
        "exit_code": 1,
        "commit": current.head,
        "workspace_fingerprint": current.fingerprint,
        "workspace_fingerprint_after": current.fingerprint,
        "stdout": "RAW_OUTPUT_MUST_NOT_INLINE",
    }
    for name, record in (
        ("failed.json", base),
        ("stale.json", {**base, "commit": "0" * 40}),
    ):
        (harness / "evidence" / name).write_text(json.dumps(record))
    _, core = load_and_build(harness)
    rows = {row["ref"]: row for row in core["evidence"]}
    assert rows[".harness/evidence/failed.json"]["status"] == "FAILED"
    assert rows[".harness/evidence/failed.json"]["code"] == "EVIDENCE_RESULT_MISMATCH"
    assert rows[".harness/evidence/stale.json"]["status"] == "STALE"
    assert rows[".harness/evidence/stale.json"]["code"] == "EVIDENCE_HEAD_MISMATCH"
    assert "RAW_OUTPUT_MUST_NOT_INLINE" not in json.dumps(core)


@pytest.mark.parametrize("level", ["Q1", "Q2", "Q3"])
def test_classified_old_task_loads_without_new_budget_fields(harness, level):
    task = set_profile(harness, level)
    _, core = load_and_build(harness)
    assert core["task"]["risk"] == task["risk"]


@pytest.mark.parametrize("name", ["requirements.yaml", "invariants.yaml"])
def test_fast_missing_contract_is_empty_but_not_created(harness, name):
    (harness / name).unlink()
    source, core = load_and_build(harness)
    assert core[name.removesuffix(".yaml")] == []
    assert source.references[name] is None
    assert not (harness / name).exists()


@pytest.mark.parametrize("level", ["Q2", "Q3"])
@pytest.mark.parametrize("name", ["requirements.yaml", "invariants.yaml"])
def test_non_fast_missing_contract_fails_closed(harness, level, name):
    from harness.context.model import ContextBuildError

    set_profile(harness, level)
    (harness / name).unlink()
    with pytest.raises(ContextBuildError, match="INVALID_HARNESS_STATE"):
        load_and_build(harness)


@pytest.mark.parametrize(
    "document", [{"requirements": "bad"}, {"requirements": [{"id": "REQ-001"}]}]
)
def test_existing_invalid_fast_contract_is_not_treated_as_empty(harness, document):
    from harness.context.model import ContextBuildError

    write_yaml(harness / "requirements.yaml", document)
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        load_and_build(harness)


@pytest.mark.parametrize("risk", [None, "absent"])
def test_unclassified_task_fails_without_fabricating_risk(harness, risk):
    from harness.context.model import ContextBuildError

    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    if risk == "absent":
        task.pop("risk")
    else:
        task["risk"] = risk
    write_yaml(path, task)
    with pytest.raises(ContextBuildError, match="INVALID_HARNESS_STATE"):
        load_and_build(harness)


def test_gate_failure_never_falls_back_to_persisted_pass(harness, monkeypatch):
    from harness.context.model import ContextBuildError

    def unavailable(*args, **kwargs):
        raise quality_gate.InvalidHarnessState("cannot assess current evidence")

    monkeypatch.setattr(quality_gate, "assess_gate", unavailable)
    with pytest.raises(ContextBuildError, match="INVALID_HARNESS_STATE"):
        load_and_build(harness)


def test_projection_is_deterministic_and_does_not_alias_authoritative_records(harness):
    from harness.context.builder import build_control_core

    source, core = load_and_build(harness)
    original = copy.deepcopy(source.task)
    assert build_control_core(source) == core
    core["task"]["risk"]["dimensions"]["security"] = "high"
    core["scope"]["protected_user_paths"].clear()
    assert source.task == original


@pytest.mark.parametrize("name", ["current-task.yaml", "gate.yaml"])
def test_missing_required_control_source_fails_closed(harness, name):
    from harness.context.model import ContextBuildError

    (harness / name).unlink()
    with pytest.raises(ContextBuildError, match="INVALID_HARNESS_STATE"):
        load_and_build(harness)


@pytest.mark.parametrize(
    "name,document",
    [
        ("impact.yaml", {"impact": {"contracts": "not-a-list"}}),
        ("observability.yaml", {"required": "false"}),
        ("findings/FND-001.yaml", {"id": "FND-001", "status": "OPEN"}),
        ("decisions/DEC-001.yaml", {"id": "DEC-001", "status": "ACCEPTED"}),
        ("interface-contracts/INT-001.yaml", {"id": "INT-001"}),
    ],
)
def test_malformed_control_artifact_is_never_silently_ignored(harness, name, document):
    from harness.context.model import ContextBuildError

    write_yaml(harness / name, document)
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        load_and_build(harness)


def test_invalid_evidence_rejects_core_instead_of_reporting_fresh(harness):
    from harness.context.model import ContextBuildError

    (harness / "evidence/broken.json").write_text("not json")
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        load_and_build(harness)


def test_duplicate_requirement_ids_are_rejected(harness):
    from harness.context.model import ContextBuildError

    record = {
        "id": "REQ-001",
        "statement": "One fact",
        "priority": "must",
        "status": "pending",
    }
    write_yaml(harness / "requirements.yaml", {"requirements": [record, record]})
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        load_and_build(harness)


def test_missing_optional_sources_do_not_fabricate_control_facts(harness):
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task.pop("scope")
    task.pop("authorizations")
    write_yaml(task_path, task)
    (harness / "impact.yaml").unlink()
    (harness / "observability.yaml").unlink()
    _, core = load_and_build(harness)
    assert core["scope"] is None
    assert core["authorizations"] is None
    assert core["contracts"] == {"interfaces": [], "impact": []}
    assert core["observability"] is None


def test_record_filename_cannot_point_at_another_contract_id(harness):
    from harness.context.model import ContextBuildError

    interface_contract.declare(harness, contract(name="first"))
    interface_contract.declare(harness, contract(name="second"))
    one = harness / "interface-contracts/INT-001.yaml"
    two = harness / "interface-contracts/INT-002.yaml"
    first, second = one.read_bytes(), two.read_bytes()
    one.write_bytes(second)
    two.write_bytes(first)
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        load_and_build(harness)


@pytest.mark.parametrize(
    "directory", ["decisions", "findings", "interface-contracts", "evidence"]
)
def test_control_directory_cannot_be_replaced_with_regular_file(harness, directory):
    from harness.context.model import ContextBuildError

    path = harness / directory
    path.rmdir()
    path.write_text("not a directory")
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        load_and_build(harness)


@pytest.mark.parametrize(
    "directory", ["decisions", "findings", "interface-contracts", "evidence"]
)
def test_external_source_symlink_is_rejected_even_when_directory_is_empty(
    harness, tmp_path_factory, directory
):
    from harness.context.model import ContextBuildError

    outside = tmp_path_factory.mktemp("outside-context")
    path = harness / directory
    path.rmdir()
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        load_and_build(harness)


def test_broken_control_directory_symlink_is_rejected(harness):
    from harness.context.model import ContextBuildError

    path = harness / "decisions"
    path.rmdir()
    path.symlink_to(harness.parent / "missing-decisions", target_is_directory=True)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        load_and_build(harness)


def test_absent_record_directories_are_empty_without_being_created(harness):
    for directory in ("decisions", "findings", "interface-contracts", "evidence"):
        (harness / directory).rmdir()
    _, core = load_and_build(harness)
    assert core["decisions"] == []
    assert core["findings"] == []
    assert core["evidence"] == []
    assert core["contracts"]["interfaces"] == []
    assert not (harness / "decisions").exists()


def test_source_ref_cannot_follow_file_symlink_outside_repository(
    harness, tmp_path_factory
):
    from harness.context.model import ContextBuildError

    outside = tmp_path_factory.mktemp("outside-context") / "requirements.yaml"
    write_yaml(outside, {"requirements": []})
    path = harness / "requirements.yaml"
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        load_and_build(harness)


def test_loader_rejects_mismatched_workspace_without_changing_cwd(harness, monkeypatch):
    from pathlib import Path

    from harness.context.model import ContextBuildError

    subdirectory = harness.parent / "subdirectory"
    subdirectory.mkdir()
    monkeypatch.chdir(subdirectory)
    with pytest.raises(ContextBuildError, match="INVALID_HARNESS_STATE"):
        load_and_build(harness)
    assert Path.cwd() == subdirectory


def test_seeded_requirement_subsets_always_preserve_all_must_records(harness):
    from harness.context.builder import build_control_core

    source, _ = load_and_build(harness)
    rng = random.Random(28)
    for _ in range(20):
        records = [
            {
                "id": f"REQ-{i:03}",
                "priority": rng.choice(["must", "should", "could"]),
                "statement": f"Constraint {i}",
                "status": "pending",
            }
            for i in range(15)
        ]
        source.requirements[:] = records
        core = build_control_core(source)
        assert core["requirements"] == [r for r in records if r["priority"] == "must"]
