"""Freeze read authority for Context/Gate evaluation, not the whole repository."""

from contextlib import contextmanager
from pathlib import Path

from harness.source_access import source_scope


@contextmanager
def context_read_scope(harness_dir: Path, versions: dict):
    root = harness_dir.absolute().parent
    allowed = {harness_dir / name for name in versions["files"]}
    allowed.update(
        {harness_dir / name for name in ("alignment.yaml", "alignment-freeze.yaml")}
    )
    allowed.update(root / name for name in versions["declared_files"])
    rules = [
        (harness_dir / directory, pattern)
        for directory, pattern in (
            ("evidence", "*.json"),
            ("findings", "*.yaml"),
            ("decisions", "DEC-*.yaml"),
            ("interface-contracts", "INT-*.yaml"),
        )
    ]
    with source_scope(root, allowed=allowed, member_rules=rules) as observed:
        yield observed
