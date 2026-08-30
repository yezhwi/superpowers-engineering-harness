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


def _collect(harness_dir: Path, etype="unit_test", cmd="true", *, reuse_if_valid=False):
    args = [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
            "--type", etype, "--command", cmd, "--harness-dir", str(harness_dir)]
    if etype == "unit_test":
        args.extend(["--scope", "full_suite"])
    if reuse_if_valid:
        args.append("--reuse-if-valid")
    return subprocess.run(
        args,
        capture_output=True, text=True, cwd=REPO,
    )


def test_evidence_filename_separates_finding_phases():
    from harness.collect_evidence import evidence_filename

    assert evidence_filename("unit_test") == "unit-test.json"
    assert evidence_filename("unit_test", finding_id="FND-001", phase="red") == "FND-001-red-unit-test.json"
    assert evidence_filename("unit_test", finding_id="FND-001", phase="green") == "FND-001-green-unit-test.json"
    assert evidence_filename("unit_test", phase="red") == "fast-red-unit-test.json"


def test_reuse_hit_does_not_execute_or_rewrite_evidence(tmp_path):
    marker = tmp_path / "ran"
    command = f"sh -c 'echo ran > {marker}'"
    assert _collect(tmp_path, "build", command).returncode == 0
    marker.unlink()
    path = tmp_path / "evidence/build.json"
    before = path.read_bytes()

    result = _collect(tmp_path, "build", command, reuse_if_valid=True)

    assert result.returncode == 0
    assert "EVIDENCE_REUSED: build.json" in result.stdout
    assert not marker.exists()
    assert path.read_bytes() == before


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


def test_collect_success_evidence_records_exact_runtime(tmp_path):
    result = _collect(tmp_path, "build", "true")
    assert result.returncode == 0
    runtime = json.loads((tmp_path / "evidence/build.json").read_text())["runtime"]
    assert set(runtime) == {"implementation", "version", "executable", "platform"}
    assert all(isinstance(value, str) and value for value in runtime.values())


def test_collect_structured_finding_test_evidence(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "custom", "--command", "false", "--finding", "FND-001",
         "--phase", "red", "--test", "tests/test_x.py::test_x", "--harness-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((tmp_path / "evidence" / "FND-001-red-custom.json").read_text())
    assert evidence["subject"] == {"kind": "finding", "id": "FND-001"}
    assert evidence["test"] == {"node_id": "tests/test_x.py::test_x"}


def test_collect_finding_phase_writes_separate_file(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "unit_test", "--finding", "FND-001", "--phase", "red",
         "--test", "tests/test_x.py::test_x", "--scope", "related", "--covered-test",
         "tests/test_x.py::test_x", "--command", "false", "--harness-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "evidence" / "FND-001-red-unit-test.json").is_file()


def test_collect_related_scope_records_covered_tests(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "unit_test", "--scope", "related", "--covered-test",
         "tests/test_x.py::test_x", "--command", "true", "--harness-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((tmp_path / "evidence" / "unit-test.json").read_text())
    assert evidence["scope"] == "related"
    assert evidence["covered_tests"] == ["tests/test_x.py::test_x"]


def test_collect_related_scope_requires_covered_test(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "unit_test", "--scope", "related", "--command", "true",
         "--harness-dir", str(tmp_path)], capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 2
    assert "RELATED_COVERED_TEST_REQUIRED" in result.stderr


def test_collect_integration_evidence_records_covered_tests(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
         "--type", "integration_test", "--covered-test", "tests/test_api.py::test_create",
         "--command", "true", "--harness-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((tmp_path / "evidence" / "integration-test.json").read_text())
    assert evidence["covered_tests"] == ["tests/test_api.py::test_create"]


def test_collect_timeout_records_deterministic_failed_evidence():
    from harness.collect_evidence import collect

    evidence = collect("build", "python -c 'import time; time.sleep(1)'", timeout_seconds=0.01)

    assert evidence["exit_code"] != 0
    assert evidence["error"] == "EVIDENCE_COMMAND_TIMEOUT"


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
