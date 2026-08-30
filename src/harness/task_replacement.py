"""Atomic replacement-task workspace publication."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def replacement_workspace(harness_dir: Path) -> Path:
    """Return sibling copy of Harness state for all-or-nothing mutation."""
    parent = harness_dir.parent
    staged = Path(tempfile.mkdtemp(prefix=f".{harness_dir.name}.replacement-", dir=parent))
    try:
        shutil.rmtree(staged)
        shutil.copytree(harness_dir, staged, ignore=shutil.ignore_patterns(".staging"))
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def publish_replacement(harness_dir: Path, staged: Path) -> None:
    """Swap complete Harness directory, restoring original if publish fails."""
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
