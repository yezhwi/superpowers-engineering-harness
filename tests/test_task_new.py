"""TASK-008: archive completed task and create a new one."""

import subprocess, sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def cli(cwd, *a):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *a],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(p, state="DONE"):
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    cli(p, "init")
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=p, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=p, check=True)
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=p, check=True)
    h = p / ".harness"
    t = yaml.safe_load((h / "current-task.yaml").read_text())
    t["task"]["id"] = "TASK-001"
    t["task"]["title"] = "old"
    t["state"] = state
    (h / "current-task.yaml").write_text(yaml.safe_dump(t))
    return h


def test_task_new_archives_done_task(tmp_path):
    h = setup(tmp_path)
    r = cli(tmp_path, "task", "new", "TASK-002", "--title", "next")
    assert r.returncode == 0
    t = yaml.safe_load((h / "current-task.yaml").read_text())
    assert t["task"]["id"] == "TASK-002" and t["state"] == "CREATED"
    assert any((h / "history").iterdir())


def _write_v2_seal(harness, mode, *, task_id="TASK-001"):
    record = {
        "version": 2,
        "task_id": task_id,
        "contract_hash": "sha256:" + "0" * 64,
        "architecture_mode": mode,
        "architecture_fingerprint": "sha256:" + "1" * 64 if mode == "required" else None,
        "declared_modules": ["app"] if mode == "required" else [],
        "decision_selections": {},
        "boundary_refs": {"interface": [], "permission": [], "persistence": []},
        "frozen_at": "2026-10-01T00:00:00Z",
    }
    (harness / "alignment-freeze.yaml").write_text(yaml.safe_dump(record, sort_keys=False))


def _set_gate_mode(harness, mode):
    path = harness / "gate.yaml"
    gate = yaml.safe_load(path.read_text())
    gate["gate"]["architecture"]["mode"] = mode
    path.write_text(yaml.safe_dump(gate, sort_keys=False))


def test_task_new_archives_stale_alignment_freeze(tmp_path):
    h = setup(tmp_path)
    (h / "alignment.yaml").write_text("version: 1\ntask_id: TASK-001\n")
    (h / "alignment-freeze.yaml").write_text(
        "version: 1\ntask_id: TASK-001\ncontract_hash: sha256:" + "0" * 64
        + "\ndecision_selections: {}\nboundary_refs: {interface: [], permission: [], persistence: []}\nfrozen_at: now\n"
    )

    result = cli(tmp_path, "task", "new", "TASK-002")

    assert result.returncode == 0
    assert not (h / "alignment.yaml").exists()
    assert not (h / "alignment-freeze.yaml").exists()
    archive = next((h / "history").iterdir())
    assert (archive / "alignment.yaml").exists()
    assert (archive / "alignment-freeze.yaml").exists()


def test_task_new_restores_required_mode_from_same_task_v2_seal(tmp_path):
    h = setup(tmp_path)
    _set_gate_mode(h, "off")
    _write_v2_seal(h, "required")
    (h / "architecture.yaml").write_text("version: 1\n")
    architecture_before = (h / "architecture.yaml").read_bytes()

    result = cli(tmp_path, "task", "new", "TASK-002")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((h / "gate.yaml").read_text())["gate"]["architecture"]["mode"] == "required"
    assert (h / "architecture.yaml").read_bytes() == architecture_before
    archive = next((h / "history").iterdir())
    assert yaml.safe_load((archive / "alignment-freeze.yaml").read_text())["architecture_mode"] == "required"


def test_task_new_v2_off_overrides_current_required_mode(tmp_path):
    h = setup(tmp_path)
    _set_gate_mode(h, "required")
    _write_v2_seal(h, "off")

    result = cli(tmp_path, "task", "new", "TASK-002")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((h / "gate.yaml").read_text())["gate"]["architecture"]["mode"] == "off"


def test_task_new_without_v2_uses_validated_current_gate_mode(tmp_path):
    h = setup(tmp_path)
    _set_gate_mode(h, "required")

    result = cli(tmp_path, "task", "new", "TASK-002")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((h / "gate.yaml").read_text())["gate"]["architecture"]["mode"] == "required"


@pytest.mark.parametrize("malformed", ["gate", "seal", "identity"])
def test_task_new_invalid_architecture_authority_is_atomic(tmp_path, malformed):
    h = setup(tmp_path)
    if malformed == "gate":
        (h / "gate.yaml").write_text("gate: {architecture: {mode: invalid}}\n")
    elif malformed == "seal":
        (h / "alignment-freeze.yaml").write_text("version: 2\n")
    else:
        _write_v2_seal(h, "required", task_id="TASK-999")
    before = {path.relative_to(h).as_posix(): path.read_bytes() for path in h.rglob("*") if path.is_file()}

    result = cli(tmp_path, "task", "new", "TASK-002")

    assert result.returncode == 2
    assert "TASK_REPLACEMENT_FAILED" in result.stderr
    assert {path.relative_to(h).as_posix(): path.read_bytes() for path in h.rglob("*") if path.is_file()} == before


def test_task_new_resets_observability_contract(tmp_path):
    h = setup(tmp_path)
    (h / "observability.yaml").write_text(
        "version: 1\nrequired: true\napplicability: {reasons: [old], inspected_paths: [old.py]}\nbusiness_keys: [old_id]\nfailure_boundaries: [old_boundary]\ncritical_events: [old_event]\n"
    )
    r = cli(tmp_path, "task", "new", "TASK-002")
    assert r.returncode == 0
    assert yaml.safe_load((h / "observability.yaml").read_text())["required"] is False


def test_task_new_archives_and_resets_impact(tmp_path):
    h = setup(tmp_path)
    (h / "impact.yaml").write_text(
        "impact:\n  changed: [src/old.py]\n  direct_dependents: []\n  contracts: []\n  risks: []\n  required_tests: [tests/test_old.py]\n  full_suite: {recommended: false, reason: null}\n"
    )
    r = cli(tmp_path, "task", "new", "TASK-002")
    assert r.returncode == 0
    archive = next((h / "history").iterdir())
    assert yaml.safe_load((archive / "impact.yaml").read_text())["impact"][
        "required_tests"
    ] == ["tests/test_old.py"]
    assert (
        yaml.safe_load((h / "impact.yaml").read_text())["impact"]["required_tests"]
        == []
    )


def test_task_new_defaults_type_to_feature(tmp_path):
    h = setup(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["task"]["type"] == "feature"


def test_task_new_writes_explicit_off_policy_and_empty_module_scope(tmp_path):
    h = setup(tmp_path)

    result = cli(tmp_path, "task", "new", "TASK-002")

    assert result.returncode == 0, result.stderr
    gate = yaml.safe_load((h / "gate.yaml").read_text())
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert gate["gate"]["architecture"] == {"mode": "off"}
    assert task["scope"]["modules"] == []


def test_classify_freezes_complete_git_identity(tmp_path):
    h = setup(tmp_path, state="CREATED")
    flags = [
        item
        for name, value in {
            "scope": "low", "contract": "low", "data": "none",
            "authorization": "none", "security": "none", "concurrency": "none",
            "deployment": "none",
        }.items()
        for item in (f"--{name}", value)
    ]

    result = cli(tmp_path, "task", "classify", "--level", "Q2", *flags)

    assert result.returncode == 0, result.stderr
    git = yaml.safe_load((h / "current-task.yaml").read_text())["git"]
    assert git["base_ref"]
    assert git["base_commit"] == git["head_at_start"] == git["head"]


def test_task_new_refuses_active_task(tmp_path):
    setup(tmp_path, "IMPLEMENTING")
    assert cli(tmp_path, "task", "new", "TASK-002").returncode == 1


def test_task_new_rejects_invalid_id(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, "task", "new", "next-task").returncode == 2
