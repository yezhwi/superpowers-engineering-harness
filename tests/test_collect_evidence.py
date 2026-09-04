from pathlib import Path

import pytest

import harness.collect_evidence as evidence_module
from harness.collect_evidence import main


def test_public_module_has_no_shell_command_executor():
    """Break caught: external callers can invoke shell executor directly."""
    assert not hasattr(evidence_module, "collect")
    assert not hasattr(evidence_module, "TrustedLocalCommand")


def test_only_main_invokes_private_shell_executor():
    source = Path(evidence_module.__file__).read_text()
    assert source.count("_collect(") == 2  # definition plus main call


def test_readme_marks_shell_executor_as_unsupported_internal_api():
    readme = Path("README.md").read_text()
    assert "unsupported internal API" in readme


def test_main_marks_cli_command_as_trusted_local(tmp_path, monkeypatch):
    """Break caught: CLI passes raw command text past trust boundary."""
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.workspace_fingerprint", lambda: "workspace"
    )

    assert (
        main(
            [
                "--type",
                "custom",
                "--command",
                "printf ok",
                "--harness-dir",
                str(tmp_path / ".harness"),
            ]
        )
        == 0
    )
