"""Milestone 2: Evidence collection tests.

Covers:
- collect_evidence.py runs a real command, records exit_code, commit, tails
- evidence written even when command fails
- evidence filename mapping (unit_test -> unit-test.json)
- invalid git repo -> exit 2
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO,
    ).stdout.strip()


def __collect(
    harness_dir: Path,
    etype="unit_test",
    cmd="true",
    *,
    covered_test="tests/test_x.py::test_x",
    reuse_if_valid=False,
    phase=None,
):
    args = [
        sys.executable,
        str(REPO / "scripts" / "collect_evidence.py"),
        "--type",
        etype,
        "--command",
        cmd,
        "--harness-dir",
        str(harness_dir),
    ]
    if etype == "unit_test":
        args.extend(["--scope", "related", "--covered-test", covered_test])
    if reuse_if_valid:
        args.append("--reuse-if-valid")
    if phase is not None:
        args.extend(["--phase", phase])
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_evidence_filename_separates_finding_phases():
    from harness.collect_evidence import evidence_filename

    assert evidence_filename("unit_test") == "unit-test.json"
    assert (
        evidence_filename("unit_test", finding_id="FND-001", phase="red")
        == "FND-001-red-unit-test.json"
    )
    assert (
        evidence_filename("unit_test", finding_id="FND-001", phase="green")
        == "FND-001-green-unit-test.json"
    )
    assert evidence_filename("unit_test", phase="red") == "fast-red-unit-test.json"


def test_reuse_hit_does_not_execute_or_rewrite_evidence(tmp_path):
    marker = tmp_path / "ran"
    command = f"sh -c 'echo ran > {marker}'"
    assert __collect(tmp_path, "build", command).returncode == 0
    marker.unlink()
    path = tmp_path / "evidence/build.json"
    before = path.read_bytes()

    result = __collect(tmp_path, "build", command, reuse_if_valid=True)

    assert result.returncode == 0
    assert "EVIDENCE_REUSED: build.json" in result.stdout
    assert not marker.exists()
    assert path.read_bytes() == before


def test_related_test_evidence_is_append_only_per_coverage(tmp_path):
    assert __collect(tmp_path, "unit_test", "true", covered_test="tests/test_a.py").returncode == 0
    assert __collect(tmp_path, "unit_test", "true", covered_test="tests/test_b.py").returncode == 0

    records = sorted((tmp_path / "evidence").glob("unit-test-*.json"))
    assert len(records) == 2
    assert {json.loads(path.read_text())["covered_tests"][0] for path in records} == {
        "tests/test_a.py",
        "tests/test_b.py",
    }


def test_repeated_related_evidence_identity_creates_immutable_receipts(tmp_path):
    assert __collect(tmp_path, "unit_test", "true", covered_test="tests/test_a.py").returncode == 0
    original = next((tmp_path / "evidence").glob("unit-test-*.json"))
    before = original.read_bytes()

    assert __collect(tmp_path, "unit_test", "true", covered_test="tests/test_a.py").returncode == 0

    records = sorted((tmp_path / "evidence").glob("unit-test-*.json"))
    assert len(records) == 2
    assert original.read_bytes() == before
    assert any(path.stem.endswith("-2") for path in records)


@pytest.mark.parametrize("phase", [None, "green"])
def test_reuse_miss_allocates_immutable_suffix(tmp_path, phase):
    evidence_type = "build" if phase is None else "unit_test"
    assert __collect(tmp_path, evidence_type, "true", phase=phase).returncode == 0
    [original] = (tmp_path / "evidence").glob("*.json")
    before = original.read_bytes()

    result = __collect(
        tmp_path, evidence_type, "echo new receipt", reuse_if_valid=True, phase=phase
    )

    assert result.returncode == 0, result.stderr
    assert "EVIDENCE_REUSED" not in result.stdout
    assert original.read_bytes() == before
    newer = original.with_name(f"{original.stem}-2.json")
    assert json.loads(newer.read_text())["command"] == "echo new receipt"


def test_reuse_selects_latest_matching_immutable_receipt(tmp_path):
    assert __collect(tmp_path, "unit_test", "true", covered_test="tests/test_a.py").returncode == 0
    assert __collect(tmp_path, "unit_test", "true", covered_test="tests/test_a.py").returncode == 0

    result = __collect(
        tmp_path, "unit_test", "true", covered_test="tests/test_a.py", reuse_if_valid=True
    )

    assert result.returncode == 0
    assert "EVIDENCE_REUSED: unit-test-9196f11cb5cc-2.json" in result.stdout


def test_green_phase_reuses_latest_receipt(tmp_path):
    marker = tmp_path / "ran"
    command = f"sh -c 'echo ran >> {marker}'"
    assert __collect(tmp_path, "unit_test", command, phase="green").returncode == 0
    assert __collect(tmp_path, "unit_test", command, phase="green").returncode == 0
    marker.unlink()
    before = {p.name: p.read_bytes() for p in (tmp_path / "evidence").glob("*.json")}

    result = __collect(tmp_path, "unit_test", command, phase="green", reuse_if_valid=True)

    assert result.returncode == 0, result.stderr
    assert "EVIDENCE_REUSED: fast-green-unit-test-2.json" in result.stdout
    assert not marker.exists()
    assert {p.name: p.read_bytes() for p in (tmp_path / "evidence").glob("*.json")} == before


@pytest.mark.parametrize("exit_code", [0, 1])
def test_red_phase_never_reuses(tmp_path, exit_code):
    marker = tmp_path / "ran"
    command = f"sh -c 'echo ran >> {marker}; exit {exit_code}'"
    assert __collect(tmp_path, "unit_test", command, phase="red").returncode == 0
    first = (tmp_path / "evidence/fast-red-unit-test.json").read_bytes()
    marker.unlink()

    result = __collect(tmp_path, "unit_test", command, phase="red", reuse_if_valid=True)

    assert "EVIDENCE_REUSED" not in result.stdout
    assert marker.exists()
    assert (tmp_path / "evidence/fast-red-unit-test.json").read_bytes() == first
    assert (tmp_path / "evidence/fast-red-unit-test-2.json").exists()


def test_collect_success_evidence(tmp_path):
    result = __collect(tmp_path, "unit_test", "echo hello")
    assert result.returncode == 0, result.stderr

    [path] = (tmp_path / "evidence").glob("unit-test-*.json")
    ev = json.loads(path.read_text())

    required = {"type", "timestamp", "command", "exit_code", "commit"}
    assert required <= set(ev)
    assert ev["type"] == "unit_test"
    assert ev["exit_code"] == 0
    assert ev["commit"] == _head()
    assert "hello" in ev["stdout_tail"]
    assert ev["timestamp"]  # iso timestamp present


def test_collect_success_evidence_records_exact_runtime(tmp_path):
    result = __collect(tmp_path, "build", "true")
    assert result.returncode == 0
    runtime = json.loads((tmp_path / "evidence/build.json").read_text())["runtime"]
    assert set(runtime) == {"implementation", "version", "executable", "platform"}
    assert all(isinstance(value, str) and value for value in runtime.values())


def test_collect_structured_finding_test_evidence(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "custom",
            "--command",
            "false",
            "--finding",
            "FND-001",
            "--phase",
            "red",
            "--test",
            "tests/test_x.py::test_x",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(
        (tmp_path / "evidence" / "FND-001-red-custom.json").read_text()
    )
    assert evidence["subject"] == {"kind": "finding", "id": "FND-001"}
    assert evidence["test"] == {"node_id": "tests/test_x.py::test_x"}


def test_collect_finding_phase_writes_separate_file(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "unit_test",
            "--finding",
            "FND-001",
            "--phase",
            "red",
            "--test",
            "tests/test_x.py::test_x",
            "--scope",
            "related",
            "--covered-test",
            "tests/test_x.py::test_x",
            "--command",
            "false",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "evidence" / "FND-001-red-unit-test.json").is_file()


def test_collect_related_scope_records_covered_tests(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "unit_test",
            "--scope",
            "related",
            "--covered-test",
            "tests/test_x.py::test_x",
            "--command",
            "true",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    [path] = (tmp_path / "evidence").glob("unit-test-*.json")
    evidence = json.loads(path.read_text())
    assert evidence["scope"] == "related"
    assert evidence["covered_tests"] == ["tests/test_x.py::test_x"]


def test_collect_rejects_invalid_covered_test_case_before_execution(tmp_path):
    marker = tmp_path / "ran"
    result = subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
            "--type", "unit_test", "--scope", "related",
            "--covered-test", "tests/test_x.py::test_x",
            "--covered-test-case", "REQ-004/TC-004",
            "--command", f"pytest tests/test_x.py::test_x; touch {marker}", "--harness-dir", str(tmp_path),
        ], capture_output=True, text=True, cwd=REPO,
    )

    assert result.returncode == 2
    assert "COVERED_TEST_CASE_INVALID" in result.stderr
    assert not marker.exists()
    assert not (tmp_path / "evidence").exists()


def test_collect_non_test_evidence_rejects_covered_test(tmp_path):
    result = subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "collect_evidence.py"),
            "--type", "build", "--covered-test", "tests/test_x.py::test_x",
            "--command", "true", "--harness-dir", str(tmp_path),
        ], capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 2
    assert "COVERED_TEST_TYPE_INVALID" in result.stderr


@pytest.mark.parametrize("entrypoint", ["script", "cli"])
def test_collect_related_scope_requires_covered_test(tmp_path, entrypoint):
    marker = tmp_path / "MUST_NOT_EXECUTE"
    cwd = REPO
    harness_dir = tmp_path
    if entrypoint == "cli":
        cwd = tmp_path
        harness_dir = tmp_path / ".harness"
        subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
             "commit", "--allow-empty", "-qm", "fixture"],
            cwd=cwd,
            check=True,
        )
    command = (
        [sys.executable, str(REPO / "scripts" / "collect_evidence.py")]
        if entrypoint == "script"
        else [sys.executable, "-m", "harness.cli", "evidence", "run"]
    )
    result = subprocess.run(
        command + [
            "--type",
            "unit_test",
            "--scope",
            "related",
            "--command",
            f"touch {shlex.quote(str(marker))}",
        ] + (["--harness-dir", str(harness_dir)] if entrypoint == "script" else []),
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )
    assert result.returncode == 2
    assert "RELATED_COVERED_TEST_REQUIRED" in result.stderr
    assert (
        "Next: Run: harness evidence run --type unit_test --scope related "
        "--covered-test path/to/test.py::test_name --command '<test command>'"
    ) in result.stderr
    assert "--help" not in result.stderr
    assert not marker.exists()
    assert not (harness_dir / "evidence").exists()


def test_collect_integration_evidence_records_covered_tests(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "integration_test",
            "--covered-test",
            "tests/test_api.py::test_create",
            "--command",
            "true",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    [path] = (tmp_path / "evidence").glob("integration-test-*.json")
    evidence = json.loads(path.read_text())
    assert evidence["covered_tests"] == ["tests/test_api.py::test_create"]
    assert evidence["scope"] == "related"


def test_collect_integration_related_scope_records_scope(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "integration_test",
            "--finding",
            "FND-001",
            "--test",
            "tests/test_api.py::test_create",
            "--phase",
            "full",
            "--scope",
            "related",
            "--covered-test",
            "tests/test_api.py::test_create",
            "--command",
            "true",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((tmp_path / "evidence" / "FND-001-full-integration-test.json").read_text())
    assert evidence["scope"] == "related"


def test_collect_timeout_records_deterministic_failed_evidence():
    from harness.collect_evidence import _TrustedLocalCommand, _collect

    evidence = _collect(
        "build",
        _TrustedLocalCommand("python -c 'import time; time.sleep(1)'"),
        timeout_seconds=0.01,
    )

    assert evidence["exit_code"] != 0
    assert evidence["error"] == "EVIDENCE_COMMAND_TIMEOUT"


def test_collect_timeout_normalizes_byte_output_and_records_detail(monkeypatch):
    from harness.collect_evidence import _TrustedLocalCommand, _collect

    original_run = subprocess.run

    def timeout(command, *args, **kwargs):
        if command == "ignored":
            raise subprocess.TimeoutExpired(
                "command", 2, output=b"bad\xff", stderr=b"err\xff"
            )
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr("harness.collect_evidence.subprocess.run", timeout)
    evidence = _collect("build", _TrustedLocalCommand("ignored"), timeout_seconds=2)

    assert evidence["stdout_tail"] == "bad�"
    assert evidence["stderr_tail"] == "err�"
    assert evidence["error"] == "EVIDENCE_COMMAND_TIMEOUT"
    assert evidence["error_detail"] == {
        "code": "EVIDENCE_COMMAND_TIMEOUT",
        "kind": "timeout",
        "timeout_seconds": 2,
    }


@pytest.mark.parametrize("detail, valid", [
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": 2}, True),
    ({"code": "OTHER_TIMEOUT", "kind": "timeout", "timeout_seconds": .5}, True),
    ({"code": "EVIDENCE_COMMAND_CANCELLED", "kind": "cancelled"}, True),
    ({}, False),
    (None, False),
    ({"kind": "cancelled"}, False),
    ({"code": "EVIDENCE_COMMAND_CANCELLED"}, False),
    ({"code": "OTHER", "kind": "cancelled"}, False),
    ({"code": "", "kind": "cancelled"}, False),
    ({"code": "EVIDENCE_COMMAND_CANCELLED", "kind": "cancelled", "timeout_seconds": 2}, False),
    ({"code": "EVIDENCE_COMMAND_CANCELLED", "kind": "cancelled", "extra": "unexpected"}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout"}, False),
    ({"kind": "timeout", "timeout_seconds": 2}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "timeout_seconds": 2}, False),
    ({"code": "", "kind": "timeout", "timeout_seconds": 2}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": 0}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": -1}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": "2"}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": True}, False),
    ({"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": 2, "extra": 1}, False),
    ({"code": "OTHER", "kind": "unknown", "timeout_seconds": 2}, False),
])
def test_evidence_error_detail_validation_preserves_failure_contract(detail, valid):
    """Break caught: cancellation is unreadable, or timeout validation is relaxed."""
    from harness.evidence_validator import EvidenceValidationError, validate_evidence

    fingerprint = "sha256:" + "b" * 64
    record = {
        "type": "custom", "timestamp": "2026-01-01T00:00:00+00:00",
        "command": "measured command", "exit_code": 130, "commit": "a" * 40,
        "workspace_fingerprint": fingerprint, "workspace_fingerprint_after": fingerprint,
        "error_detail": detail,
    }
    kwargs = {"current_head": "a" * 40, "current_workspace": fingerprint, "expected_success": False}
    if valid:
        validate_evidence(record, **kwargs)
    else:
        with pytest.raises(EvidenceValidationError, match="EVIDENCE_SCHEMA_INVALID"):
            validate_evidence(record, **kwargs)


@pytest.mark.parametrize("exit_code", [0, 7, 124])
def test_cancelled_detail_cannot_be_relabelled_as_another_result(exit_code):
    """Break caught: new cancelled schema branch lets a cancellation claim success."""
    from harness.evidence_validator import EvidenceValidationError, validate_evidence

    fingerprint = "sha256:" + "b" * 64
    record = {
        "type": "custom", "timestamp": "2026-01-01T00:00:00+00:00",
        "command": "measured command", "exit_code": exit_code, "commit": "a" * 40,
        "workspace_fingerprint": fingerprint, "workspace_fingerprint_after": fingerprint,
        "error_detail": {"code": "EVIDENCE_COMMAND_CANCELLED", "kind": "cancelled"},
    }
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_SCHEMA_INVALID"):
        validate_evidence(record, current_head="a" * 40, current_workspace=fingerprint)


def test_collect_failure_still_writes_evidence(tmp_path):
    result = __collect(tmp_path, "build", "false")
    assert result.returncode == 0, result.stderr

    ev = json.loads((tmp_path / "evidence" / "build.json").read_text())
    assert ev["exit_code"] != 0
    assert ev["commit"] == _head()


def test_collect_filename_mapping(tmp_path):
    for etype in ("integration_test", "typecheck", "contract_test"):
        assert __collect(tmp_path, etype, "true").returncode == 0
    assert list((tmp_path / "evidence").glob("integration-test-*.json"))
    assert (tmp_path / "evidence" / "typecheck.json").exists()
    assert list((tmp_path / "evidence").glob("contract-test-*.json"))


def test_collect_stderr_tail(tmp_path):
    __collect(tmp_path, "lint", "echo oops >&2")
    ev = json.loads((tmp_path / "evidence" / "lint.json").read_text())
    assert "oops" in ev["stderr_tail"]


def test_collect_invalid_type_rejected(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "nonsense",
            "--command",
            "true",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode != 0


def test_collect_outside_git_repo_invalid_state(tmp_path, monkeypatch):
    # empty non-git dir as cwd
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "collect_evidence.py"),
            "--type",
            "build",
            "--command",
            "true",
            "--harness-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr
