"""Freeze read authority for Context/Gate evaluation, not the whole repository."""

from contextlib import contextmanager
from pathlib import Path

from harness.source_access import source_scope


@contextmanager
def context_read_scope(harness_dir: Path, versions: dict):
    # Load implementation before freezing canonical data authority. Self-hosted
    # Python imports must not become undeclared control-source reads.
    from harness import _scope_replay  # noqa: F401

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
            (".candidate-operations", "*.json"),
            *((f"evidence/candidate-{kind}", "*.json")
              for kind in ("prepared", "proof", "review", "acceptance", "trace")),
        )
    ]
    with source_scope(
        root,
        allowed=allowed,
        member_rules=rules,
        resource_versions=versions["schema_resources"],
        absolute_only=True,
    ) as observed:
        yield observed
