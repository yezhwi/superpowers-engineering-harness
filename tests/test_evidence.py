"""Milestone 2: Evidence collection tests.

Covers:
- collect_evidence.py runs a real command, records exit_code, commit, tails
- evidence written even when command fails
- evidence filename mapping (unit_test -> unit-test.json)
- invalid git repo -> exit 2
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=REPO,
    ).stdout.strip()


def _collect(harness_dir: Path, etype="unit_test", cmd="true"):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", etype, "--command", cmd,
         "--harness-dir", str(harness_dir)],
        capture_output=True, text=True, cwd=REPO,
    )


def test_collect_success_evidence(tmp_path):
    result = _collect(tmp_path, "unit_test", "echo hello")
    assert result.returncode == 0, result.stderr

    path = tmp_path / "evidence" / "unit-test.json"
    assert path.exists()
    ev = json.loads(path.read_text())

    required = {"type", "timestamp", "command", "exit_code", "commit"}
    assert required <= set(ev)
    assert ev["type"] == "unit_test"
    assert ev["exit_code"] == 0
    assert ev["commit"] == _head()
    assert "hello" in ev["stdout_tail"]
    assert ev["timestamp"]  # iso timestamp present


def test_collect_failure_still_writes_evidence(tmp_path):
    result = _collect(tmp_path, "build", "false")
    assert result.returncode == 0, result.stderr

    ev = json.loads((tmp_path / "evidence" / "build.json").read_text())
    assert ev["exit_code"] != 0
    assert ev["commit"] == _head()


def test_collect_filename_mapping(tmp_path):
    for etype in ("integration_test", "typecheck", "contract_test"):
        assert _collect(tmp_path, etype, "true").returncode == 0
    assert (tmp_path / "evidence" / "integration-test.json").exists()
    assert (tmp_path / "evidence" / "typecheck.json").exists()
    assert (tmp_path / "evidence" / "contract-test.json").exists()


def test_collect_stderr_tail(tmp_path):
    _collect(tmp_path, "lint", "echo oops >&2")
    ev = json.loads((tmp_path / "evidence" / "lint.json").read_text())
    assert "oops" in ev["stderr_tail"]


def test_collect_invalid_type_rejected(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "nonsense", "--command", "true",
         "--harness-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode != 0


def test_collect_outside_git_repo_invalid_state(tmp_path, monkeypatch):
    # empty non-git dir as cwd
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "build", "--command", "true",
         "--harness-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin",
             "HOME": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr
