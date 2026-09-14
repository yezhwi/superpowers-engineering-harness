"""Real Git output capture must work without weakening scoped fd rejection."""

# Keep subprocess-domain errors separate from scope-exit checks.
# ruff: noqa: SIM117

import pytest
import test_context_builder

from harness import workspace
from harness.context.model import ContextBuildError
from harness.source_access import source_scope

harness = test_context_builder.harness


def test_real_protected_fingerprint_runs_under_guard(harness):
    root = harness.parent
    path = root / "protected.txt"
    path.write_text("fixture")
    expected = workspace.protected_paths_fingerprint((path.name,), root)
    with source_scope(root, allowed=[path]) as observed:
        assert workspace.protected_paths_fingerprint((path.name,), root) == expected
    assert "bytes" in observed.snapshot()[path.name]


def test_failed_git_query_preserves_workspace_error(harness):
    with source_scope(harness.parent, allowed=[]):
        with pytest.raises(workspace.WorkspaceError):
            workspace._run(harness.parent, "merge-base", "nonexistent-ref", "HEAD")
    assert workspace.git_head(harness.parent)


def test_arbitrary_fd_is_still_denied_after_git_query(harness):
    file = harness.parent / "private.txt"
    file.write_text("private")
    queried = False
    with file.open("rb") as opened:
        with (
            pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"),
            source_scope(harness.parent, allowed=[]),
        ):
            assert workspace.git_head(harness.parent)
            queried = True
            with open(opened.fileno(), closefd=False) as stream:
                stream.read()
    assert queried


def test_capture_handles_large_stdout_and_stderr(harness, monkeypatch):
    import sys

    from harness import git_query

    original = git_query.subprocess.run

    def emit(_command, **kwargs):
        return original(
            [
                sys.executable,
                "-c",
                "import os; os.write(1, b'x' * 2000000); os.write(2, b'y' * 2000000)",
            ],
            **kwargs,
        )

    monkeypatch.setattr(git_query.subprocess, "run", emit)
    with source_scope(harness.parent, allowed=[]):
        result = git_query.run_git_query(harness.parent, ("rev-parse", "HEAD"))
    assert result.returncode == 0
    assert result.stdout == b"x" * 2000000
    assert result.stderr == b"y" * 2000000


def test_launch_failure_closes_both_capture_files(harness, monkeypatch):
    from harness import git_query

    original = git_query.TemporaryFile
    opened = []

    def capture():
        file = original()
        opened.append(file)
        return file

    def fail(*args, **kwargs):
        raise OSError("injected launch failure")

    monkeypatch.setattr(git_query, "TemporaryFile", capture)
    monkeypatch.setattr(git_query.subprocess, "run", fail)
    with pytest.raises(OSError, match="injected launch failure"):
        git_query.run_git_query(harness.parent, ("rev-parse", "HEAD"))
    assert len(opened) == 2
    assert all(file.closed for file in opened)


@pytest.mark.parametrize(
    "command", [("push",), ("reset", "--hard"), ("diff", "--output=out.txt", "HEAD")]
)
def test_adapter_rejects_nonquery_commands(harness, command):
    from harness.git_query import run_git_query

    with pytest.raises(ValueError, match="GIT_QUERY_INVALID"):
        run_git_query(harness.parent, command)
