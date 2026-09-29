"""P2 bounded automatic Plan proof tests."""

import json
from pathlib import Path

import pytest
import yaml

from harness.evidence_validator import EvidenceValidationError
from harness.plan_automation import (
    EvidenceCandidate,
    MechanicalSurfaceFacts,
    PlanAutomationError,
    derive_auto_proof,
    mechanical_surface_facts,
    select_unique_minimum_cover,
)


def candidate(ref: str, *bits: int) -> EvidenceCandidate:
    coverage = 0
    for bit in bits:
        coverage |= 1 << bit
    return EvidenceCandidate(ref, coverage)


def test_select_unique_minimum_cover_returns_canonical_single_candidate():
    selected = select_unique_minimum_cover(
        0b111,
        (
            candidate("z", 0),
            candidate("complete", 0, 1, 2),
            candidate("a", 1, 2),
        ),
    )

    assert selected == ("complete",)


def test_select_unique_minimum_cover_returns_sorted_multi_candidate_cover():
    selected = select_unique_minimum_cover(
        0b111,
        (
            candidate("z-last", 2),
            candidate("a-first", 0),
            candidate("m-middle", 1),
            candidate("redundant"),
        ),
    )

    assert selected == ("a-first", "m-middle", "z-last")


def test_select_unique_minimum_cover_rejects_equal_minimum_tie():
    with pytest.raises(PlanAutomationError) as error:
        select_unique_minimum_cover(
            0b11,
            (candidate("a", 0, 1), candidate("b", 0, 1)),
        )

    assert error.value.code == "PLAN_AUTO_PROOF_AMBIGUOUS"


def test_select_unique_minimum_cover_rejects_duplicate_coverage_tie():
    with pytest.raises(PlanAutomationError) as error:
        select_unique_minimum_cover(
            0b11,
            (candidate("a", 0), candidate("b", 0), candidate("c", 1)),
        )

    assert error.value.code == "PLAN_AUTO_PROOF_AMBIGUOUS"


def test_select_unique_minimum_cover_rejects_no_cover_and_zero_atoms():
    with pytest.raises(PlanAutomationError) as no_cover:
        select_unique_minimum_cover(0b11, (candidate("a", 0),))
    with pytest.raises(PlanAutomationError) as zero_atoms:
        select_unique_minimum_cover(0, (candidate("a", 0),))

    assert no_cover.value.code == "PLAN_PROOF_MISSING"
    assert zero_atoms.value.code == "PLAN_PROOF_MISSING"


def test_select_unique_minimum_cover_enforces_closed_limits():
    sixteen_candidates = tuple(candidate(f"e-{index:02d}", index) for index in range(16))
    assert select_unique_minimum_cover((1 << 16) - 1, sixteen_candidates) == tuple(
        f"e-{index:02d}" for index in range(16)
    )

    with pytest.raises(PlanAutomationError) as candidates_error:
        select_unique_minimum_cover(
            1,
            tuple(candidate(f"e-{index:02d}", 0) for index in range(17)),
        )
    with pytest.raises(PlanAutomationError) as atoms_error:
        select_unique_minimum_cover(
            (1 << 17) - 1,
            tuple(candidate(f"e-{index:02d}", index) for index in range(16)),
        )

    assert candidates_error.value.code == "PLAN_AUTO_LIMIT_EXCEEDED"
    assert atoms_error.value.code == "PLAN_AUTO_LIMIT_EXCEEDED"


def test_select_unique_minimum_cover_is_deterministic_for_input_order():
    forward = (candidate("z", 2), candidate("a", 0), candidate("m", 1))

    assert select_unique_minimum_cover(0b111, forward) == select_unique_minimum_cover(
        0b111, tuple(reversed(forward))
    )


def automation_harness(tmp_path: Path, *, strategy: str, tests=None) -> Path:
    harness_dir = tmp_path / ".harness"
    evidence_dir = harness_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    requirement = {
        "id": "REQ-001",
        "statement": "proof",
        "source": "spec",
        "type": "feature",
        "priority": "must",
        "status": "pending",
        "evidence": [],
        "test_plan": {
            "strategies": [strategy],
            "cases": [
                {
                    "id": "TC-001",
                    "type": "happy_path",
                    "strategy": strategy,
                    "description": "proof case",
                    "tests": tests or [],
                }
            ],
        },
    }
    (harness_dir / "requirements.yaml").write_text(
        yaml.safe_dump({"requirements": [requirement]}, sort_keys=False)
    )
    (harness_dir / "invariants.yaml").write_text("invariants: []\n")
    return harness_dir


def evidence_record(
    *,
    head: str,
    workspace: str,
    command: str = "true",
    exit_code: int = 0,
    covered_tests=(),
    covered_test_cases=(),
) -> dict:
    return {
        "type": "unit_test",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "command": command,
        "exit_code": exit_code,
        "commit": head,
        "workspace_fingerprint": workspace,
        "workspace_fingerprint_after": workspace,
        "covered_tests": list(covered_tests),
        "covered_test_cases": list(covered_test_cases),
    }


def write_record(harness_dir: Path, name: str, record: dict) -> None:
    (harness_dir / "evidence" / f"{name}.json").write_text(json.dumps(record))


def test_derive_auto_proof_uses_fresh_manual_bare_case_candidates(tmp_path):
    head = "a" * 40
    workspace = "sha256:" + "b" * 64
    harness_dir = automation_harness(tmp_path, strategy="manual")
    write_record(
        harness_dir,
        "selected",
        evidence_record(
            head=head, workspace=workspace, covered_test_cases=("TC-001",)
        ),
    )
    write_record(
        harness_dir,
        "stale",
        evidence_record(
            head="c" * 40,
            workspace=workspace,
            covered_test_cases=("TC-001",),
        ),
    )
    write_record(
        harness_dir,
        "failed",
        evidence_record(
            head=head,
            workspace=workspace,
            exit_code=1,
            covered_test_cases=("TC-001",),
        ),
    )
    write_record(
        harness_dir,
        "wrong-workspace",
        evidence_record(
            head=head,
            workspace="sha256:" + "d" * 64,
            covered_test_cases=("TC-001",),
        ),
    )
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(evidence_record(head=head, workspace=workspace)))
    item = {"id": "P-001", "test_case_refs": ["REQ-001/TC-001"]}

    result = derive_auto_proof(
        harness_dir,
        {},
        {"version": 1, "items": [item]},
        item,
        head=head,
        workspace=workspace,
    )

    assert result.evidence_refs == ("selected",)
    assert result.surface_refs == ()
    assert "outside" not in result.evidence_refs


def test_derive_auto_proof_requires_record_and_command_automated_coverage(tmp_path):
    head = "a" * 40
    workspace = "sha256:" + "b" * 64
    node = "tests/test_feature.py::test_case"
    harness_dir = automation_harness(tmp_path, strategy="unit", tests=[node])
    write_record(
        harness_dir,
        "selected",
        evidence_record(
            head=head,
            workspace=workspace,
            command=f"pytest {node}",
            covered_tests=(node,),
        ),
    )
    write_record(
        harness_dir,
        "claim-only",
        evidence_record(
            head=head,
            workspace=workspace,
            command="true",
            covered_tests=(node,),
        ),
    )
    item = {"id": "P-001", "test_case_refs": ["REQ-001/TC-001"]}

    result = derive_auto_proof(
        harness_dir,
        {},
        {"version": 1, "items": [item]},
        item,
        head=head,
        workspace=workspace,
    )

    assert result.evidence_refs == ("selected",)


def test_derive_auto_proof_fails_closed_on_malformed_present_evidence(tmp_path):
    harness_dir = automation_harness(tmp_path, strategy="manual")
    (harness_dir / "evidence" / "malformed.json").write_text("not json")
    item = {"id": "P-001", "test_case_refs": ["REQ-001/TC-001"]}

    with pytest.raises(EvidenceValidationError):
        derive_auto_proof(
            harness_dir,
            {},
            {"version": 1, "items": [item]},
            item,
            head="a" * 40,
            workspace="sha256:" + "b" * 64,
        )


def test_derive_auto_proof_rejects_nonempty_refs_with_zero_atoms(tmp_path):
    harness_dir = automation_harness(tmp_path, strategy="unit", tests=[])
    item = {"id": "P-001", "test_case_refs": ["REQ-001/TC-001"]}

    with pytest.raises(PlanAutomationError) as error:
        derive_auto_proof(
            harness_dir,
            {},
            {"version": 1, "items": [item]},
            item,
            head="a" * 40,
            workspace="sha256:" + "b" * 64,
        )

    assert error.value.code == "PLAN_PROOF_MISSING"


def test_mechanical_surface_facts_filters_unchanged_protected_paths(monkeypatch):
    from harness import plan_automation

    monkeypatch.setattr(
        plan_automation,
        "changed_paths_since",
        lambda *_args, **_kwargs: ("docs/guide.md", "tests/test_x.py", "user.py"),
    )
    monkeypatch.setattr(
        plan_automation,
        "protected_paths_fingerprint",
        lambda *_args, **_kwargs: "sha256:same",
    )
    task = {
        "git": {"base_commit": "base"},
        "risk": {
            "user_changes": {
                "paths": ["user.py"],
                "fingerprint": "sha256:same",
            }
        },
    }
    plan = {"items": [{"surfaces": ["docs/guide.md"]}]}

    facts = mechanical_surface_facts(task, plan)

    assert facts.changed == frozenset(
        {"docs/guide.md", "tests/test_x.py", "user.py"}
    )
    assert facts.usable == frozenset({"docs/guide.md", "tests/test_x.py"})
    assert facts.protected == frozenset({"user.py"})
    assert not facts.protected_fingerprint_changed


def test_mechanical_surface_facts_retains_protected_paths_after_divergence(monkeypatch):
    from harness import plan_automation

    monkeypatch.setattr(
        plan_automation,
        "changed_paths_since",
        lambda *_args, **_kwargs: ("user.py",),
    )
    monkeypatch.setattr(
        plan_automation,
        "protected_paths_fingerprint",
        lambda *_args, **_kwargs: "sha256:changed",
    )
    task = {
        "git": {"base_commit": "base"},
        "risk": {
            "user_changes": {
                "paths": ["user.py"],
                "fingerprint": "sha256:stored",
            }
        },
    }

    facts = mechanical_surface_facts(task, {"items": [{"surfaces": ["user.py"]}]})

    assert facts.usable == frozenset({"user.py"})
    assert facts.protected_fingerprint_changed


def test_derive_auto_proof_selects_sorted_usable_surfaces(tmp_path, monkeypatch):
    from harness import plan_automation

    harness_dir = automation_harness(tmp_path, strategy="manual")
    item = {"id": "P-001", "surfaces": ["z.py", "a.py", "protected.py"]}
    monkeypatch.setattr(
        plan_automation,
        "mechanical_surface_facts",
        lambda *_args, **_kwargs: MechanicalSurfaceFacts(
            frozenset({"z.py", "a.py"}),
            frozenset({"z.py", "a.py"}),
            frozenset({"protected.py"}),
            False,
        ),
    )

    result = derive_auto_proof(
        harness_dir,
        {},
        {"version": 1, "items": [item]},
        item,
        head="a" * 40,
        workspace="sha256:" + "b" * 64,
    )

    assert result.surface_refs == ("a.py", "z.py")


def test_derive_auto_proof_combines_test_and_surface_branches(tmp_path, monkeypatch):
    from harness import plan_automation

    head = "a" * 40
    workspace = "sha256:" + "b" * 64
    harness_dir = automation_harness(tmp_path, strategy="manual")
    write_record(
        harness_dir,
        "manual-proof",
        evidence_record(
            head=head, workspace=workspace, covered_test_cases=("TC-001",)
        ),
    )
    item = {
        "id": "P-001",
        "test_case_refs": ["REQ-001/TC-001"],
        "surfaces": ["src/changed.py"],
    }
    monkeypatch.setattr(
        plan_automation,
        "mechanical_surface_facts",
        lambda *_args, **_kwargs: MechanicalSurfaceFacts(
            frozenset({"src/changed.py"}),
            frozenset({"src/changed.py"}),
            frozenset(),
            False,
        ),
    )

    result = derive_auto_proof(
        harness_dir,
        {},
        {"version": 1, "items": [item]},
        item,
        head=head,
        workspace=workspace,
    )

    assert result.evidence_refs == ("manual-proof",)
    assert result.surface_refs == ("src/changed.py",)


def test_derive_auto_proof_rejects_surface_branch_without_usable_path(
    tmp_path, monkeypatch
):
    from harness import plan_automation

    harness_dir = automation_harness(tmp_path, strategy="manual")
    item = {"id": "P-001", "surfaces": ["missing.py"]}
    monkeypatch.setattr(
        plan_automation,
        "mechanical_surface_facts",
        lambda *_args, **_kwargs: MechanicalSurfaceFacts(
            frozenset(), frozenset(), frozenset(), False
        ),
    )

    with pytest.raises(PlanAutomationError) as error:
        derive_auto_proof(
            harness_dir,
            {},
            {"version": 1, "items": [item]},
            item,
            head="a" * 40,
            workspace="sha256:" + "b" * 64,
        )

    assert error.value.code == "PLAN_PROOF_MISSING"
