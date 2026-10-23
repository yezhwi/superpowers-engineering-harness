"""Atomic replacement-task workspace publication."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Literal
from uuid import uuid4

import yaml

from harness import source_access, transaction


def trusted_architecture_mode(
    harness_dir: Path, old_task: dict
) -> Literal["off", "required"]:
    """Resolve replacement policy from validated gate and same-task v2 seal."""
    from harness.quality_gate import validate_schema

    gate_path = harness_dir / "gate.yaml"
    try:
        gate = yaml.safe_load(source_access.read_text(gate_path))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("ARCHITECTURE_GATE_INVALID") from exc
    validate_schema(gate, "gate.schema.json", gate_path)
    mode = gate["gate"].get("architecture", {}).get("mode", "off")

    seal_path = harness_dir / "alignment-freeze.yaml"
    if not source_access.is_file(seal_path):
        return mode
    try:
        seal = yaml.safe_load(source_access.read_text(seal_path))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("ALIGNMENT_FREEZE_INVALID") from exc
    validate_schema(seal, "alignment-freeze.schema.json", seal_path)
    if seal["task_id"] != old_task.get("task", {}).get("id"):
        raise ValueError("ALIGNMENT_FREEZE_TASK_MISMATCH")
    return seal["architecture_mode"] if seal["version"] in {2, 3} else mode


def restore_architecture_mode(
    staged_harness_dir: Path, mode: Literal["off", "required"]
) -> None:
    """Restore trusted mode after replacement templates have been copied."""
    from harness.quality_gate import validate_schema

    gate_path = staged_harness_dir / "gate.yaml"
    gate = yaml.safe_load(source_access.read_text(gate_path))
    validate_schema(gate, "gate.schema.json", gate_path)
    gate["gate"]["architecture"] = {"mode": mode}
    transaction.atomic_write(
        gate_path, yaml.safe_dump(gate, sort_keys=False).encode("utf-8")
    )


def replacement_workspace(harness_dir: Path) -> Path:
    """Copy task facts; opaque probes stay in the original tree for retention."""
    ignore_storage = shutil.ignore_patterns(".staging", ".publication-retained")

    def ignore(directory, names):
        ignored = ignore_storage(directory, names)
        if Path(directory) == harness_dir:
            # Never traverse probes, including FIFO/symlink fixtures. Publication
            # retains their original inodes with the whole old Harness root.
            ignored.add("acceptance-probes")
        return ignored

    parent = harness_dir.parent
    staged = Path(
        tempfile.mkdtemp(prefix=f".{harness_dir.name}.replacement-", dir=parent)
    )
    try:
        shutil.rmtree(staged)
        shutil.copytree(harness_dir, staged, ignore=ignore)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def install_replacement_scope(staged: Path, archive: Path) -> None:
    """Archive old origin and seal actual template set before directory swap."""
    from ._scope_replay import SCOPE_FILES, new_scope_artifacts
    from .telemetry_lock import telemetry_lock

    # These task-owned records must follow their original evidence into history.
    # Move only the disposable replacement copy, never the live source tree.
    for name in ('.candidate-operations', '.candidate-operation-inputs', '.candidate-active.json'):
        source = staged / name
        if source.is_symlink():
            raise OSError('TRANSACTION_RECOVERY_BLOCKED: candidate storage invalid')
        if source.exists():
            source.rename(archive / name)
    for name in SCOPE_FILES:
        source = staged / name
        if source.is_symlink():
            raise OSError('TEST_SCOPE_AUDIT_INVALID')
        if source.exists():
            shutil.copy2(source, archive / name)
            source.unlink()
    artifacts = new_scope_artifacts(staged)
    with telemetry_lock(staged):
        transaction.publish(staged, transaction.stage(staged, artifacts),
                            replace_paths=frozenset(item.relative_path for item in artifacts), durable=True)


def publish_replacement(harness_dir: Path, staged: Path) -> None:
    """Swap complete Harness directory, restoring original if publish fails."""
    from .telemetry import preserve_usage_for_replacement
    from .telemetry_lock import telemetry_lock

    with telemetry_lock(harness_dir):
        preserve_usage_for_replacement(harness_dir, staged)
        _publish_replacement(harness_dir, staged)


def _retain_replaced_harness(harness_dir: Path, backup: Path) -> None:
    """Move old tree intact into private retention; never copy/unlink originals."""
    from . import publication_fs as fs
    from .publication_journal import _open_child

    fds = []
    failed = False
    try:
        parent = fs.open_directory(harness_dir.parent)
        fds.append(parent)
        root = _open_child(parent, harness_dir.name)
        fds.append(root)
        retained = _open_child(root, '.publication-retained', create=True)
        fds.append(retained)
        identifier = f'task-replacement-{uuid4().hex}'
        os.mkdir(identifier, mode=0o700, dir_fd=retained)
        fs.sync_directory(retained)
        slot = _open_child(retained, identifier)
        fds.append(slot)
        fs.move_noreplace(parent, backup.name, slot, 'previous')
        fs.sync_directory(slot)
        fs.sync_directory(parent)
        # Reporting retained objects is subordinate to the completed move.
        with suppress(BaseException):
            print(
                f'TASK_REPLACEMENT_RETAINED: .publication-retained/{identifier}/previous',
                file=sys.stderr,
            )
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_error = None
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None and not failed:
            raise cleanup_error


def _publish_replacement(harness_dir: Path, staged: Path) -> None:
    backup = harness_dir.with_name(f".{harness_dir.name}.backup")
    if backup.exists() or backup.is_symlink():
        raise FileExistsError(f"replacement backup exists: {backup}")
    harness_dir.replace(backup)
    try:
        staged.replace(harness_dir)
    except BaseException:
        try:
            backup.replace(harness_dir)
        except OSError:
            pass  # Original remains at backup; preserve primary swap failure.
        raise
    _retain_replaced_harness(harness_dir, backup)
