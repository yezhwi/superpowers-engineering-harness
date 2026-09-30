"""Architecture Gate assessment tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from harness.blockers import RECOVERY_POLICY, GateBlocker, is_user_authority_blocker, select_recovery


REPAIRABLE = {
    "ARCHITECTURE_REQUIRED",
    "ARCHITECTURE_SCOPE_INVALID",
    "ARCHITECTURE_EVIDENCE_INVALID",
    "ARCHITECTURE_OWNERSHIP_EMPTY",
    "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
    "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
    "ARCHITECTURE_SCOPE_DRIFT",
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def document(*, shared: bool = False) -> dict:
    modules = [
        {"id": "app", "name": "App", "responsibility": "Run app.", "depends_on": [], "evidence": [{"type": "source", "path": "src/app.py"}]}
    ]
    owners = ["app"]
    kind = "production"
    if shared:
        modules.append({"id": "other", "name": "Other", "responsibility": "Share app.", "depends_on": [], "evidence": [{"type": "source", "path": "src/app.py"}]})
        owners.append("other")
        kind = "shared"
    return {
        "version": 1,
        "modules": modules,
        "ownership": [{"id": "OWN-001", "pattern": "src/**", "kind": kind, "modules": owners}],
    }


def fixture(tmp_path: Path, *, declared=("app",), shared=False):
    from harness.architecture import architecture_fingerprint, load_architecture_document

    root = tmp_path / "repo"
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("value = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    base = git(root, "rev-parse", "HEAD")
    harness = root / ".harness"
    harness.mkdir()
    architecture = document(shared=shared)
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture, sort_keys=False))
    fingerprint = architecture_fingerprint(load_architecture_document(architecture))
    task = {
        "task": {"id": "TASK-001"},
        "state": "GATING",
        "risk": {"level": "Q2", "profile": "STANDARD", "user_changes": {"paths": []}},
        "scope": {"owned_paths": [], "protected_user_paths": [], "modules": list(declared)},
        "git": {"base_commit": base},
    }
    seal = {
        "version": 2,
        "task_id": "TASK-001",
        "contract_hash": "sha256:" + "0" * 64,
        "architecture_mode": "required",
        "architecture_fingerprint": fingerprint,
        "declared_modules": list(declared),
        "decision_selections": {},
        "boundary_refs": {"interface": [], "permission": [], "persistence": []},
        "frozen_at": "now",
    }
    (harness / "alignment-freeze.yaml").write_text(yaml.safe_dump(seal, sort_keys=False))
    return root, harness, task, {"architecture": {"mode": "required"}}


def test_fast_and_off_short_circuit_before_architecture_sources_or_git(tmp_path, monkeypatch):
    from harness import architecture_gate

    def forbidden(*args, **kwargs):
        raise AssertionError("Architecture source/Git touched")

    monkeypatch.setattr(architecture_gate, "load_architecture", forbidden)
    monkeypatch.setattr(architecture_gate.workspace, "architecture_changes", forbidden)
    monkeypatch.setattr(architecture_gate.workspace, "architecture_path_index", forbidden)
    task = {"risk": {"level": "Q1", "profile": "FAST"}}
    assert architecture_gate.assess_architecture(tmp_path, task, {"architecture": {"mode": "required"}}, allow_preflight=True).blockers == ()
    task = {"risk": {"level": "Q3", "profile": "STRICT"}}
    assert architecture_gate.assess_architecture(tmp_path, task, {"architecture": {"mode": "off"}}, allow_preflight=True).blockers == ()
    assert architecture_gate.assess_architecture(tmp_path, task, {}, allow_preflight=True).blockers == ()


def test_required_scalar_nested_task_state_is_stable_invalid_state(tmp_path):
    from harness import architecture_gate

    _root, harness, task, gate = fixture(tmp_path)
    task["risk"]["user_changes"] = 42

    with pytest.raises(architecture_gate.ArchitectureGateError, match="ARCHITECTURE_TASK_INVALID"):
        architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)


def test_required_missing_artifact_is_repairable_blocker(tmp_path):
    from harness import architecture_gate

    _root, harness, task, gate = fixture(tmp_path)
    (harness / "architecture.yaml").unlink()

    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)

    assert [(b.code, b.category, b.source) for b in assessment.blockers] == [
        ("ARCHITECTURE_REQUIRED", "implementation", "artifact:.harness/architecture.yaml")
    ]


def test_off_downgrade_from_required_seal_is_contract_change_before_artifact(tmp_path, monkeypatch):
    from harness import architecture_gate

    _root, harness, task, _gate = fixture(tmp_path)
    (harness / "architecture.yaml").write_text("malformed: [")

    def forbidden(*args, **kwargs):
        raise AssertionError("Architecture artifact loaded before mode drift")

    monkeypatch.setattr(architecture_gate, "load_architecture", forbidden)
    assessment = architecture_gate.assess_architecture(
        harness, task, {"architecture": {"mode": "off"}}, allow_preflight=True
    )

    assert assessment.blockers[0].code == "CONTRACT_CHANGED"
    assert assessment.blockers[0].source == "artifact:.harness/alignment-freeze.yaml"


def test_required_seal_mismatch_is_terminal_contract_change_before_artifact(tmp_path):
    from harness import architecture_gate

    _root, harness, task, gate = fixture(tmp_path)
    seal_path = harness / "alignment-freeze.yaml"
    seal = yaml.safe_load(seal_path.read_text())
    seal["architecture_mode"] = "off"
    seal["architecture_fingerprint"] = None
    seal["declared_modules"] = []
    seal_path.write_text(yaml.safe_dump(seal))
    (harness / "architecture.yaml").write_text("malformed: [")

    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)

    assert assessment.blockers[0].code == "CONTRACT_CHANGED"
    assert assessment.blockers[0].source == "artifact:.harness/alignment-freeze.yaml"


def test_scope_invalid_evidence_invalid_unresolved_and_ambiguous_blockers(tmp_path):
    from harness import architecture_gate

    root, harness, task, gate = fixture(tmp_path)
    task["scope"]["modules"] = ["missing"]
    seal = yaml.safe_load((harness / "alignment-freeze.yaml").read_text())
    seal["declared_modules"] = ["missing"]
    (harness / "alignment-freeze.yaml").write_text(yaml.safe_dump(seal))
    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)
    assert any(b.code == "ARCHITECTURE_SCOPE_INVALID" and b.source == "module:missing" for b in assessment.blockers)

    root, harness, task, gate = fixture(tmp_path / "evidence")
    (root / "src/app.py").unlink()
    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)
    assert any(b.code == "ARCHITECTURE_EVIDENCE_INVALID" and b.source == "path:src/app.py" for b in assessment.blockers)
    assert any(b.code == "ARCHITECTURE_OWNERSHIP_EMPTY" and b.source == "ownership:OWN-001" for b in assessment.blockers)

    root, harness, task, gate = fixture(tmp_path / "unresolved")
    (root / "docs").mkdir()
    (root / "docs/new.md").write_text("new")
    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)
    assert any(b.code == "ARCHITECTURE_OWNERSHIP_UNRESOLVED" and b.source == "path:docs/new.md" for b in assessment.blockers)

    root, harness, task, gate = fixture(tmp_path / "ambiguous", shared=True)
    architecture = yaml.safe_load((harness / "architecture.yaml").read_text())
    architecture["ownership"].append({"id": "OWN-002", "pattern": "src/**", "kind": "production", "modules": ["app"]})
    from harness.architecture import architecture_fingerprint, load_architecture_document
    model = load_architecture_document(architecture)
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture))
    seal = yaml.safe_load((harness / "alignment-freeze.yaml").read_text())
    seal["architecture_fingerprint"] = architecture_fingerprint(model)
    (harness / "alignment-freeze.yaml").write_text(yaml.safe_dump(seal))
    (root / "src/app.py").write_text("changed\n")
    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)
    assert any(b.code == "ARCHITECTURE_OWNERSHIP_AMBIGUOUS" and b.source == "path:src/app.py" for b in assessment.blockers)


def test_gate_validates_evidence_only_for_frozen_declared_modules(tmp_path):
    from harness import architecture_gate
    from harness.architecture import architecture_fingerprint, load_architecture_document

    _root, harness, task, gate = fixture(tmp_path)
    architecture = yaml.safe_load((harness / "architecture.yaml").read_text())
    architecture["modules"].append(
        {"id": "other", "name": "Other", "responsibility": "Other.", "depends_on": [], "evidence": [{"type": "source", "path": "src/missing.py"}]}
    )
    model = load_architecture_document(architecture)
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture))
    seal_path = harness / "alignment-freeze.yaml"
    seal = yaml.safe_load(seal_path.read_text())
    seal["architecture_fingerprint"] = architecture_fingerprint(model)
    seal_path.write_text(yaml.safe_dump(seal))

    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)

    assert not any(b.code == "ARCHITECTURE_EVIDENCE_INVALID" for b in assessment.blockers)


def test_evidence_symlink_swap_during_metadata_check_fails_closed(tmp_path, monkeypatch):
    from harness import architecture_gate

    root, harness, task, gate = fixture(tmp_path)
    evidence = root / "src/app.py"
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')")
    original_is_symlink = architecture_gate.source_access.is_symlink

    def swap_after_check(path):
        result = original_is_symlink(path)
        if Path(path) == evidence:
            evidence.unlink()
            evidence.symlink_to(outside)
        return result

    monkeypatch.setattr(architecture_gate.source_access, "is_symlink", swap_after_check)

    assessment = architecture_gate.assess_architecture(
        harness, task, gate, allow_preflight=True
    )

    assert any(b.code == "ARCHITECTURE_EVIDENCE_INVALID" for b in assessment.blockers)


def test_symlinked_declared_module_evidence_is_invalid_state(tmp_path):
    from harness import architecture_gate

    root, harness, task, gate = fixture(tmp_path)
    evidence = root / "src/app.py"
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')")
    evidence.unlink()
    evidence.symlink_to(outside)

    with pytest.raises(architecture_gate.ArchitectureGateError, match="ARCHITECTURE_EVIDENCE_INVALID"):
        architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)


def test_dangling_canonical_architecture_symlink_is_invalid_state(tmp_path):
    from harness import architecture_gate

    _root, harness, task, gate = fixture(tmp_path)
    artifact = harness / "architecture.yaml"
    artifact.unlink()
    artifact.symlink_to(tmp_path / "missing.yaml")

    with pytest.raises(architecture_gate.ArchitectureGateError, match="ARCHITECTURE_SCHEMA_INVALID"):
        architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)


def test_symlinked_canonical_architecture_is_invalid_state(tmp_path):
    from harness import architecture_gate

    _root, harness, task, gate = fixture(tmp_path)
    artifact = harness / "architecture.yaml"
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(outside)

    with pytest.raises(architecture_gate.ArchitectureGateError, match="ARCHITECTURE_SCHEMA_INVALID"):
        architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)


def test_shared_path_emits_one_scope_drift_per_undeclared_owner(tmp_path):
    from harness import architecture_gate

    root, harness, task, gate = fixture(tmp_path, declared=(), shared=True)
    (root / "src/app.py").write_text("changed\n")

    assessment = architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True)

    drift = [b for b in assessment.blockers if b.code == "ARCHITECTURE_SCOPE_DRIFT"]
    assert [(b.source, b.category) for b in drift] == [
        ("path:src/app.py|module:app", "implementation"),
        ("path:src/app.py|module:other", "implementation"),
    ]


def test_preexisting_unowned_excluded_adopted_included_and_support_adds_no_module(tmp_path):
    from harness import architecture_gate

    root, harness, task, gate = fixture(tmp_path, declared=())
    (root / "src/app.py").write_text("changed\n")
    task["risk"]["user_changes"]["paths"] = ["src/app.py"]
    assert not architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True).blockers
    task["scope"]["owned_paths"] = ["src/app.py"]
    assert any(b.code == "ARCHITECTURE_SCOPE_DRIFT" for b in architecture_gate.assess_architecture(harness, task, gate, allow_preflight=True).blockers)


def test_support_change_remains_attributable_without_declared_module(tmp_path):
    from harness import architecture_gate
    from harness.architecture import architecture_fingerprint, load_architecture_document

    root, harness, task, gate = fixture(tmp_path, declared=())
    architecture = yaml.safe_load((harness / "architecture.yaml").read_text())
    architecture["ownership"].append(
        {"id": "OWN-002", "pattern": "docs/**", "kind": "support", "modules": []}
    )
    model = load_architecture_document(architecture)
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture))
    seal_path = harness / "alignment-freeze.yaml"
    seal = yaml.safe_load(seal_path.read_text())
    seal["architecture_fingerprint"] = architecture_fingerprint(model)
    seal_path.write_text(yaml.safe_dump(seal))
    (root / "docs").mkdir()
    (root / "docs/note.md").write_text("support")

    assessment = architecture_gate.assess_architecture(
        harness, task, gate, allow_preflight=True
    )

    assert assessment.blockers == ()
    assert assessment.relevant_modules == ()


def test_gate_merges_architecture_with_independent_requirement_blockers_once(
    tmp_path, monkeypatch
):
    from harness import architecture_gate, quality_gate
    from test_quality_gate import SAFE_DIMENSIONS, make_harness

    harness = make_harness(tmp_path)
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q2",
        "profile": "STANDARD",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    task_path.write_text(yaml.safe_dump(task))
    requirements_path = harness / "requirements.yaml"
    requirements = yaml.safe_load(requirements_path.read_text())
    requirements["requirements"][0]["status"] = "pending"
    requirements_path.write_text(yaml.safe_dump(requirements))
    calls = []

    def assess(*args, **kwargs):
        calls.append((args, kwargs))
        return architecture_gate.ArchitectureAssessment(
            (
                GateBlocker(
                    "ARCHITECTURE_REQUIRED",
                    "implementation",
                    "missing",
                    source="artifact:.harness/architecture.yaml",
                ),
            ),
            None,
            (),
            (),
        )

    monkeypatch.setattr(architecture_gate, "assess_architecture", assess)
    monkeypatch.setattr(quality_gate, "_append_live_alignment_drift", lambda *args: None)

    result = quality_gate.assess_gate(harness, allow_preflight=True)

    assert len(calls) == 1
    assert {blocker.code for blocker in result.blockers} >= {
        "ARCHITECTURE_REQUIRED",
        "REQUIREMENT_UNVERIFIED",
    }


@pytest.mark.parametrize(
    ("state", "authority", "fragment"),
    [
        ("PLANNED", False, "harness transition IMPLEMENTING"),
        ("PLANNED", True, "harness task recover"),
        ("GATING", False, "harness gate, then harness resume"),
        ("GATING", True, "harness gate, then after ESCALATED use harness task new"),
        ("BLOCKED", False, "harness resume"),
        ("REPRODUCING", True, "complete Finding lifecycle"),
        ("FIXING", True, "harness transition VERIFYING"),
        ("CONVERGED", False, "harness transition DONE"),
        ("CONVERGED", True, "harness task recover"),
        ("DONE", False, "harness task new"),
        ("ESCALATED", True, "harness task new"),
    ],
)
def test_architecture_preflight_guidance_is_state_and_authority_aware(
    state, authority, fragment
):
    from harness.controlplane import _architecture_preflight_guidance

    assert fragment in _architecture_preflight_guidance(state, authority=authority)


def test_architecture_preflight_uses_blocked_not_missing_evidence(monkeypatch, capsys):
    from harness import controlplane

    monkeypatch.setattr(controlplane, "load_task", lambda _path: {"state": "PLANNED"})
    controlplane._print_preflight_failure(
        [
            GateBlocker(
                "ARCHITECTURE_REQUIRED",
                "implementation",
                "missing",
                source="artifact:.harness/architecture.yaml",
            )
        ]
    )

    stderr = capsys.readouterr().err
    assert "GATE_PREFLIGHT_BLOCKED" in stderr
    assert "GATE_PREFLIGHT_MISSING_EVIDENCE" not in stderr
    assert "harness transition IMPLEMENTING" in stderr


def test_repairable_policy_and_contract_authority_are_distinct():
    from harness.review_outcome import is_allowed

    assert is_allowed("VERIFICATION_GAP", "ARCHITECTURE_SCOPE_INCOMPLETE")
    assert all(RECOVERY_POLICY[code] == "IMPLEMENTING" for code in REPAIRABLE)
    assert RECOVERY_POLICY["CONTRACT_CHANGED"] == "ESCALATED"
    assert is_user_authority_blocker("CONTRACT_CHANGED")
    blocker = GateBlocker("CONTRACT_CHANGED", "implementation", "changed", source="artifact:.harness/alignment-freeze.yaml")
    assert select_recovery([blocker]) is None
