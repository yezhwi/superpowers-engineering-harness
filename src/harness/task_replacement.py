"""Atomic replacement-task workspace publication."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

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
    return seal["architecture_mode"] if seal["version"] == 2 else mode


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
    """Return sibling copy of Harness state for all-or-nothing mutation."""
    parent = harness_dir.parent
    staged = Path(
        tempfile.mkdtemp(prefix=f".{harness_dir.name}.replacement-", dir=parent)
    )
    try:
        shutil.rmtree(staged)
        shutil.copytree(harness_dir, staged, ignore=shutil.ignore_patterns(".staging"))
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def publish_replacement(harness_dir: Path, staged: Path) -> None:
    """Swap complete Harness directory, restoring original if publish fails."""
    from .telemetry import preserve_usage_for_replacement
    from .telemetry_lock import telemetry_lock

    with telemetry_lock(harness_dir):
        preserve_usage_for_replacement(harness_dir, staged)
        _publish_replacement(harness_dir, staged)


def _publish_replacement(harness_dir: Path, staged: Path) -> None:
    backup = harness_dir.with_name(f".{harness_dir.name}.backup")
    if backup.exists():
        raise FileExistsError(f"replacement backup exists: {backup}")
    try:
        harness_dir.replace(backup)
        try:
            staged.replace(harness_dir)
        except Exception:
            backup.replace(harness_dir)
            raise
    finally:
        if harness_dir.exists() and backup.exists():
            shutil.rmtree(backup)
        elif staged.exists():
            shutil.rmtree(staged, ignore_errors=True)
