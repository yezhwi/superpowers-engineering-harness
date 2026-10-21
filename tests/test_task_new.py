"""TASK-008: archive completed task and create a new one."""

import builtins
import json
import hashlib
import os
import shutil
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


def _prune_api():
    try:
        from harness import task_prune
    except ImportError:
        pytest.fail("task prune capability is missing", pytrace=False)
    return task_prune


def _archive(harness, task_id, created, suffix, *, members=()):
    micros = int(hashlib.sha256(suffix.encode()).hexdigest()[:6], 16) % 1000000
    archive = harness / "history" / f"{task_id}-20261020T000000{micros:06d}Z"
    archive.mkdir(parents=True)
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["task"]["id"] = task_id
    task["timestamps"]["created_at"] = created
    (archive / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))
    for name in ("requirements.yaml", "invariants.yaml", "gate.yaml", "impact.yaml",
                 "observability.yaml", "test-scope-baseline.yaml", "test-scope-audit.yaml",
                 "test-scope-seal.yaml"):
        shutil.copy2(harness / name, archive / name)
    for name in ("findings", "evidence"):
        shutil.copytree(harness / name, archive / name)
    for name, content in members:
        path = archive / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return archive


def test_task_prune_rejects_forged_partial_archive_but_accepts_producer_archive(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    forged = h / "history/TASK-050-20261020T000000000000Z"
    forged.mkdir()
    (forged / "current-task.yaml").write_text("task: {id: TASK-050}\ntimestamps: {created_at: '2026-01-01T00:00:00Z'}\n")

    result = _prune_api().preview(h)

    assert groups[0].name in result["candidates"]
    assert forged.name not in result["candidates"]


def test_task_prune_accepts_archive_emitted_by_task_new(tmp_path):
    h = setup(tmp_path)
    completed_id = yaml.safe_load((h / "current-task.yaml").read_text())["task"]["id"]
    created = cli(tmp_path, "task", "new", "TASK-999")
    assert created.returncode == 0, created.stderr
    produced = next((h / "history").glob(f"{completed_id}-*"))
    for n in range(10):
        _archive(h, f"TASK-{100 + n}", f"2026-11-{n + 1:02d}T00:00:00Z", f"producer-peer-{n}")

    result = _prune_api().preview(h)

    assert result["counts"]["trusted_groups"] == 11
    assert result["counts"]["skipped_groups"] == 0


def test_task_prune_refuses_substituted_intermediate_ancestor_before_member_delete(tmp_path, monkeypatch):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}",
                       members=(("evidence/nested/proof.json", "{}"),)) for n in range(11)]
    api = _prune_api()
    preview = api.preview(h)
    nested = groups[0] / "evidence/nested"
    moved = nested.with_name("nested-moved")
    real_open = api.os.open
    swapped = False

    def substitute_then_open(name, *args, **kwargs):
        nonlocal swapped
        if name == "nested" and "dir_fd" in kwargs and not swapped:
            swapped = True
            nested.rename(moved)
            nested.mkdir()
            (nested / "unmanaged").write_text("keep")
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(api.os, "open", substitute_then_open)
    result = api.apply(h, preview["plan_id"])

    assert result["reason"] == "IDENTITY_CHANGED"
    assert (nested / "unmanaged").read_text() == "keep"
    assert (moved / "proof.json").is_file()


def test_task_prune_malformed_sibling_protects_every_version_and_orders_real_datetimes(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    sibling = h / "history/TASK-000-20261020T000001000000Z"
    shutil.copytree(groups[0], sibling)
    (sibling / "current-task.yaml").write_text("not: a-task\n")
    _archive(h, "TASK-001", "2026-10-02T00:00:00.900000Z", "microsecond")

    result = _prune_api().preview(h)

    assert groups[0].name not in result["candidates"]
    assert sibling.name not in result["candidates"]


def test_task_prune_refuses_same_inode_same_size_content_drift_before_unlink(tmp_path, monkeypatch):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    api = _prune_api()
    preview = api.preview(h)
    target = groups[0] / "current-task.yaml"
    original = target.read_bytes()
    replacement = bytes([original[0] ^ 1]) + original[1:]
    real_open = api.os.open
    changed = False

    def mutate_then_open(name, *args, **kwargs):
        nonlocal changed
        if name == "current-task.yaml" and "dir_fd" in kwargs and not changed:
            changed = True
            target.write_bytes(replacement)
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(api.os, "open", mutate_then_open)
    result = api.apply(h, preview["plan_id"])

    assert result["reason"] == "IDENTITY_CHANGED"
    assert target.read_bytes() == replacement
    assert result["mutation_started"] is True
    assert result["counts"]["removed_entries"] > 0


def test_task_prune_refuses_replacement_archive_root_before_final_rmdir(tmp_path, monkeypatch):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    api = _prune_api()
    preview = api.preview(h)
    target, moved = groups[0], groups[0].with_name(groups[0].name + "-moved")
    real = api._remove_entry

    def substitute_after_last_member(parent_fd, name, is_dir):
        value = real(parent_fd, name, is_dir)
        if not any(target.iterdir()):
            target.rename(moved)
            target.mkdir()
            (target / "unmanaged").write_text("keep")
        return value

    monkeypatch.setattr(api, "_remove_entry", substitute_after_last_member)
    result = api.apply(h, preview["plan_id"])

    assert result["reason"] == "IDENTITY_CHANGED"
    assert (target / "unmanaged").read_text() == "keep"


def test_task_prune_fails_closed_for_canonical_reference_symlink(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    (h / "requirements.yaml").unlink()
    (h / "requirements.yaml").symlink_to("invariants.yaml")

    with pytest.raises(_prune_api().PruneError, match="STRUCTURED_INPUT_UNSAFE"):
        _prune_api().preview(h)


def _set_current_identity(harness, task_id="TASK-999", created="2026-10-20T00:00:00+00:00"):
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["task"]["id"] = task_id
    task["timestamps"]["created_at"] = created
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))


def test_task_prune_preview_is_read_only_and_apply_requires_matching_plan(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    for number in range(11):
        _archive(h, f"TASK-{number:03d}", f"2026-10-{number + 1:02d}T00:00:00+00:00", f"v{number}")
    before = {p.relative_to(h).as_posix(): p.read_bytes() for p in h.rglob("*") if p.is_file()}
    api = _prune_api()

    preview = api.preview(h)
    refused = api.apply(h, "task-prune-plan/v1:" + "0" * 64)

    assert preview["phase"] == "preview" and preview["counts"]["candidate_groups"] == 2
    assert refused["reason"] == "PLAN_MISMATCH" and refused["mutation_started"] is False
    assert {p.relative_to(h).as_posix(): p.read_bytes() for p in h.rglob("*") if p.is_file()} == before


def test_task_prune_keeps_current_plus_nine_distinct_ids_and_all_versions(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h, "TASK-010")
    groups = []
    for number in range(11):
        groups.append(_archive(h, f"TASK-{number:03d}", f"2026-10-{number + 1:02d}T00:00:00+00:00", f"v{number}"))
    duplicate = _archive(h, "TASK-009", "2026-10-10T00:00:00+00:00", "second")

    result = _prune_api().preview(h)

    assert result["counts"]["distinct_ids"] == 11
    assert result["candidates"] == [groups[0].name]
    assert groups[1].name not in result["candidates"]
    assert duplicate.name not in result["candidates"]


def test_task_prune_skips_untrusted_or_unsafe_archive_groups(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    for number in range(11):
        _archive(h, f"TASK-{number:03d}", f"2026-10-{number + 1:02d}T00:00:00+00:00", f"v{number}")
    unsafe = next((h / "history").iterdir())
    (unsafe / "unknown.bin").write_bytes(b"user")

    result = _prune_api().preview(h)

    assert unsafe.name not in result["candidates"]
    assert result["counts"]["skipped_groups"] == 1


def test_task_prune_bounded_scalar_reference_scan_protects_live_archives(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    (h / "requirements.yaml").write_text(yaml.safe_dump({"provenance": {"reference": f"history/{groups[0].name}/current-task.yaml#sha256={'a' * 64}"}}))

    result = _prune_api().preview(h)

    assert result["reason"] == "LIVE_REFERENCE"
    assert groups[0].name in result["candidates"]
    assert result["blocked"] == [{"name": groups[0].name, "reason": "LIVE_REFERENCE"}]


def test_task_prune_ambiguous_history_reference_fails_closed(tmp_path):
    h = setup(tmp_path)
    _set_current_identity(h)
    groups = [_archive(h, f"TASK-{n:03d}", f"2026-10-{n + 1:02d}T00:00:00+00:00", f"v{n}") for n in range(11)]
    api = _prune_api()
    (h / "requirements.yaml").write_text(yaml.safe_dump({"description": "the history/ directory stores archived task packages"}))
    assert api.preview(h)["reason"] == "READY"
    (h / "requirements.yaml").write_text(yaml.safe_dump({"reference": f"copy history/{groups[0].name}/current-task.yaml later"}))

    result = api.preview(h)

    assert result["reason"] == "AMBIGUOUS_REFERENCE"
    assert result["candidates"] == []


def test_task_prune_partial_failure_reports_actual_removals_and_stops(tmp_path, monkeypatch):
    h = setup(tmp_path)
    _set_current_identity(h)
    for number in range(11):
        _archive(h, f"TASK-{number:03d}", f"2026-10-{number + 1:02d}T00:00:00+00:00", f"v{number}")
    api = _prune_api()
    preview = api.preview(h)
    real = api._remove_entry
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise OSError("fixture failure with /private/payload\n")
        return real(*args, **kwargs)

    monkeypatch.setattr(api, "_remove_entry", fail_second)
    result = api.apply(h, preview["plan_id"])

    assert result["reason"] == "DELETE_FAILED"
    assert result["mutation_started"] is True
    assert result["counts"]["removed_entries"] == 1
    assert len(calls) == 2


def test_task_prune_output_failure_preserves_actual_side_effect_accounting(
    tmp_path, monkeypatch, capsys
):
    from harness import controlplane

    def pruning_root(name):
        root = tmp_path / name
        root.mkdir()
        harness = setup(root)
        _set_current_identity(harness)
        groups = [
            _archive(
                harness,
                f"TASK-{number:03d}",
                f"2026-10-{number + 1:02d}T00:00:00+00:00",
                f"{name}-{number}",
            )
            for number in range(11)
        ]
        return root, harness, groups

    root, harness, groups = pruning_root("stdout-fails")
    plan = _prune_api().preview(harness)
    monkeypatch.chdir(root)

    def fail_stdout(*args, file=None, **kwargs):
        if file is None:
            raise BrokenPipeError("unobservable payload")
        return builtins.print(*args, file=file, **kwargs)

    monkeypatch.setattr(controlplane, "print", fail_stdout, raising=False)
    assert controlplane.cmd_task_prune(True, plan["plan_id"]) == 2
    emergency = json.loads(capsys.readouterr().err)
    assert emergency["reason"] == "RESULT_EMISSION_FAILED"
    assert emergency["phase"] == "complete"
    assert emergency["mutation_started"] is True
    assert emergency["counts"]["removed_entries"] > 0
    assert emergency["counts"]["logical_bytes"] > 0
    assert not groups[0].exists()

    dead_root, dead_harness, dead_groups = pruning_root("both-streams-fail")
    dead_plan = _prune_api().preview(dead_harness)
    monkeypatch.chdir(dead_root)

    def fail_both(*args, **kwargs):
        raise OSError("streams unavailable")

    monkeypatch.setattr(controlplane, "print", fail_both, raising=False)
    assert controlplane.cmd_task_prune(True, dead_plan["plan_id"]) == 2
    assert not dead_groups[0].exists()

    preview_root, preview_harness, _ = pruning_root("preview-stdout-fails")
    monkeypatch.chdir(preview_root)
    monkeypatch.setattr(controlplane, "print", fail_stdout, raising=False)
    assert controlplane.cmd_task_prune(False, None) == 2
    preview_emergency = json.loads(capsys.readouterr().err)
    assert preview_emergency["reason"] == "RESULT_EMISSION_FAILED"
    assert preview_emergency["phase"] == "preview"
    assert preview_emergency["mutation_started"] is False
    assert preview_emergency["counts"]["removed_entries"] == 0
