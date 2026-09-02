import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args], cwd=cwd,
        capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    assert cli(repo, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


def test_cli_rejects_covered_test_not_selected_by_pytest_command(tmp_path):
    setup(tmp_path)
    result = cli(
        tmp_path, "evidence", "--type", "unit_test", "--scope", "related",
        "--covered-test", "tests/test_claimed.py::test_claimed",
        "--command", "pytest tests/test_other.py",
    )

    assert result.returncode == 2
    assert "COVERED_TEST_NOT_EXECUTED" in result.stderr
    assert not (tmp_path / ".harness/evidence/unit-test.json").exists()


def test_evidence_run_is_explicit_execution_alias(tmp_path):
    setup(tmp_path)
    result = cli(tmp_path, "evidence", "run", "--type", "build", "--command", "true")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".harness/evidence/build.json").is_file()


def test_evidence_attach_imports_complete_record_without_execution(tmp_path):
    setup(tmp_path)
    from harness.workspace import snapshot
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "command": "false", "exit_code": 0, "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:01:00+00:00",
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip(),
        "workspace_fingerprint": snapshot(tmp_path).fingerprint, "stdout_digest": "ok", "stderr_digest": "",
    }))
    result = cli(tmp_path, "evidence", "attach", "--type", "build", "--command", "false", "--result-file", str(result_file))
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / ".harness/evidence/build.json").read_text())["command"] == "false"


def test_evidence_attach_rejects_incomplete_record_without_execution(tmp_path):
    setup(tmp_path)
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({"command": "false", "exit_code": 0}))
    result = cli(tmp_path, "evidence", "attach", "--type", "build", "--command", "false", "--result-file", str(result_file))
    assert result.returncode == 2
    assert "EVIDENCE_ATTACH_INCOMPLETE" in result.stderr
    assert not (tmp_path / ".harness/evidence/build.json").exists()


def test_cli_passes_reuse_flag_to_collector(tmp_path):
    setup(tmp_path)
    first = cli(tmp_path, "evidence", "--type", "build", "--command", "true")
    second = cli(tmp_path, "evidence", "--type", "build", "--command", "true", "--reuse-if-valid")
    assert first.returncode == second.returncode == 0
    assert "EVIDENCE_REUSED: build.json" in second.stdout
