"""Regression probe: owned file capture lets approved Git run under the guard.

PYTHONPATH=src:tests python -m pytest -q docs/audits/git_source_scope_probe.py
Synthetic repository only; no production guard relaxation in this probe.
"""

import test_context_builder

from harness.source_access import source_scope
from harness.workspace import protected_paths_fingerprint

harness = test_context_builder.harness


def test_protected_fingerprint_runs_real_git_under_source_scope(harness):
    root = harness.parent
    path = root / "protected.txt"
    path.write_text("fixture")
    with source_scope(root, allowed=[path]):
        assert protected_paths_fingerprint((path.name,), root).startswith("sha256:")
