"""Regression for product-vs-control-plane freshness and cwd test-path binding."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from harness.collect_evidence import bind_covered_tests, command_covers_test, main
from harness.evidence_validator import EvidenceValidationError, validate_evidence
from harness.test_plan import validate_test_coverage
from harness.workspace import control_plane_fingerprint, snapshot

REPO = Path(__file__).resolve().parent.parent


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "tracked.py").write_text("value = 1\n")
    git(repo, "add", "tracked.py")
    git(repo, "commit", "-qm", "base")
    return repo


def cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def coverage_issues(node_id: str, command: str, covered_tests: list[str]):
    return validate_test_coverage(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "test_plan": {
                        "strategies": ["unit"],
                        "cases": [
                            {
                                "id": "TC-001",
                                "type": "happy_path",
                                "strategy": "unit",
                                "tests": [node_id],
                            }
                        ],
                    },
                }
            ]
        },
        {"invariants": []},
        [
            {
                "type": "unit_test",
                "command": command,
                "covered_tests": covered_tests,
                "exit_code": 0,
            }
        ],
        lambda record: True,
    )


def test_backend_cwd_selector_binds_repo_root_test_plan_path():
    """Break caught: pytest from backend/ cannot prove backend/tests/... plan path."""
    issues = coverage_issues(
        "backend/tests/foo.py",
        "sh -lc 'cd backend && pytest tests/foo.py'",
        ["tests/foo.py"],
    )
    assert issues == []


def test_frontend_cwd_vitest_selector_binds_repo_root_test_plan_path():
    """Break caught: Vitest from agents-frontend/ cannot prove repo-root spec path."""
    issues = coverage_issues(
        "agents-frontend/src/__tests__/foo.spec.ts",
        "sh -lc 'cd agents-frontend && npx vitest run src/__tests__/foo.spec.ts'",
        ["src/__tests__/foo.spec.ts"],
    )
    assert issues == []


def _frontend_vitest_package(root: Path, *, script: str = "vitest run") -> Path:
    frontend = root / "agents-frontend"
    spec = frontend / "src" / "__tests__" / "a.spec.ts"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("test('a', () => {})\n")
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"test:unit": script, "unrelated": "eslint ."}})
    )
    return spec


def test_npm_run_vitest_script_covers_repo_root_plan_path(tmp_path):
    """Break caught: npm run test:unit -- --run is ignored, forcing npx vitest."""
    _frontend_vitest_package(tmp_path)
    command = (
        "sh -lc 'cd agents-frontend && npm run test:unit -- "
        "--run src/__tests__/a.spec.ts'"
    )
    node_id = "agents-frontend/src/__tests__/a.spec.ts"
    assert command_covers_test(command, node_id, tmp_path)
    bound = bind_covered_tests((node_id,), command, tmp_path)
    assert bound == (node_id,)


def test_npm_run_unrelated_script_does_not_cover_test(tmp_path):
    """Break caught: extra --run args on a non-Vitest npm script count as coverage."""
    _frontend_vitest_package(tmp_path)
    command = (
        "sh -lc 'cd agents-frontend && npm run unrelated -- "
        "--run src/__tests__/a.spec.ts'"
    )
    assert not command_covers_test(
        command, "agents-frontend/src/__tests__/a.spec.ts", tmp_path
    )
    bound = bind_covered_tests(
        ("agents-frontend/src/__tests__/a.spec.ts",), command, tmp_path
    )
    assert isinstance(bound, str)
    assert bound.startswith("TEST_RUNNER_UNRESOLVED")
    assert "unrelated" in bound
    assert "agents-frontend/package.json" in bound


def test_npm_run_missing_package_json_is_unresolved(tmp_path):
    frontend = tmp_path / "agents-frontend"
    spec = frontend / "src" / "__tests__" / "a.spec.ts"
    spec.parent.mkdir(parents=True)
    spec.write_text("ok\n")
    command = (
        "sh -lc 'cd agents-frontend && npm run test:unit -- "
        "--run src/__tests__/a.spec.ts'"
    )
    bound = bind_covered_tests(
        ("agents-frontend/src/__tests__/a.spec.ts",), command, tmp_path
    )
    assert isinstance(bound, str)
    assert bound.startswith("TEST_RUNNER_UNRESOLVED")
    assert "test:unit" in bound
    assert "agents-frontend/package.json" in bound


def test_collect_npm_run_vitest_stores_canonical_path(tmp_path, monkeypatch):
    _frontend_vitest_package(tmp_path)
    code = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="src/__tests__/a.spec.ts",
        command=(
            "sh -lc 'cd agents-frontend && npm run test:unit -- "
            "--run src/__tests__/a.spec.ts'"
        ),
        create_files=("agents-frontend/src/__tests__/a.spec.ts",),
    )
    assert code == 0
    evidence = json.loads((tmp_path / ".harness/evidence/unit-test.json").read_text())
    assert evidence["covered_tests"] == ["agents-frontend/src/__tests__/a.spec.ts"]


def test_coverage_rejects_unexecuted_selector_even_when_path_suffix_matches():
    """Break caught: claiming a sibling file is treated as executed coverage."""
    issues = coverage_issues(
        "backend/tests/foo.py",
        "sh -lc 'cd backend && pytest tests/other.py'",
        ["tests/foo.py"],
    )
    assert {issue.code for issue in issues} == {"TEST_EVIDENCE_MISSING"}


def test_coverage_accepts_legacy_selector_or_canonical_covered_test():
    """Break caught: old cwd-relative covered_tests cannot migrate to canonical plans."""
    command = "sh -lc 'cd backend && pytest tests/foo.py'"
    assert coverage_issues("backend/tests/foo.py", command, ["tests/foo.py"]) == []
    assert coverage_issues("backend/tests/foo.py", command, ["backend/tests/foo.py"]) == []


def collect_related(
    tmp_path: Path,
    monkeypatch,
    *,
    covered_test: str,
    command: str,
    create_files: tuple[str, ...] = (),
):
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.workspace_fingerprint", lambda: "workspace"
    )
    monkeypatch.setattr(
        "harness.collect_evidence.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.chdir(tmp_path)
    for relative in create_files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n")
    return main(
        [
            "--type",
            "unit_test",
            "--scope",
            "related",
            "--covered-test",
            covered_test,
            "--command",
            command,
            "--harness-dir",
            str(tmp_path / ".harness"),
        ]
    )


def test_collect_stores_canonical_path_for_subdir_pytest(tmp_path, monkeypatch):
    """Break caught: evidence stores the runner selector instead of repo-root path."""
    code = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="backend/tests/foo.py",
        command="sh -lc 'cd backend && pytest tests/foo.py'",
        create_files=("backend/tests/foo.py",),
    )
    assert code == 0
    evidence = json.loads((tmp_path / ".harness/evidence/unit-test.json").read_text())
    assert evidence["covered_tests"] == ["backend/tests/foo.py"]


def test_collect_subdir_and_repo_root_commands_store_the_same_canonical_path(
    tmp_path, monkeypatch
):
    """Break caught: the same test gets two covered-test identities by cwd."""
    subdir = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="tests/foo.py",
        command="sh -lc 'cd backend && pytest tests/foo.py'",
        create_files=("backend/tests/foo.py",),
    )
    first = json.loads((tmp_path / ".harness/evidence/unit-test.json").read_text())
    root = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="backend/tests/foo.py",
        command="pytest backend/tests/foo.py",
        create_files=("backend/tests/foo.py",),
    )
    second = json.loads((tmp_path / ".harness/evidence/unit-test.json").read_text())
    assert subdir == root == 0
    assert first["covered_tests"] == second["covered_tests"] == ["backend/tests/foo.py"]


def test_collect_rejects_unexecuted_selector(tmp_path, monkeypatch):
    code = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="backend/tests/foo.py",
        command="sh -lc 'cd backend && pytest tests/other.py'",
        create_files=("backend/tests/foo.py", "backend/tests/other.py"),
    )
    assert code == 2


def test_collect_rejects_path_outside_repo(tmp_path, monkeypatch):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("ok\n")
    code = collect_related(
        tmp_path,
        monkeypatch,
        covered_test=str(outside),
        command=f"pytest {outside}",
    )
    assert code == 2


def test_collect_rejects_missing_canonical_path(tmp_path, monkeypatch):
    code = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="backend/tests/missing.py",
        command="sh -lc 'cd backend && pytest tests/missing.py'",
    )
    assert code == 2


def test_collect_rejects_invalid_relative_cwd(tmp_path, monkeypatch):
    code = collect_related(
        tmp_path,
        monkeypatch,
        covered_test="backend/tests/foo.py",
        command="sh -lc 'cd missing && pytest tests/foo.py'",
        create_files=("backend/tests/foo.py",),
    )
    assert code == 2


def test_requirement_verify_does_not_stale_product_evidence(tmp_path):
    """Break caught: attaching requirement evidence invalidates the proof it attached."""
    repo = committed_repo(tmp_path)
    assert cli(repo, "init").returncode == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init harness")
    harness = repo / ".harness"
    (harness / "requirements.yaml").write_text(
        yaml.safe_dump(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "statement": "works",
                        "priority": "must",
                        "status": "pending",
                        "evidence": [],
                    }
                ]
            }
        )
    )
    product_before = snapshot(repo).fingerprint
    control_before = control_plane_fingerprint(harness)
    collected = cli(
        repo,
        "evidence",
        "--type",
        "build",
        "--command",
        "true",
    )
    assert collected.returncode == 0, collected.stderr
    record = json.loads((harness / "evidence" / "build.json").read_text())
    verified = cli(
        repo, "requirement", "verify", "REQ-001", "--evidence", "build.json"
    )
    assert verified.returncode == 0, verified.stderr
    assert snapshot(repo).fingerprint == product_before
    assert control_plane_fingerprint(harness) != control_before
    validate_evidence(
        json.loads((harness / "evidence" / "build.json").read_text()),
        current_head=git(repo, "rev-parse", "HEAD"),
        current_workspace=snapshot(repo).fingerprint,
        expected_success=True,
    )
    (repo / "tracked.py").write_text("value = 2\n")
    try:
        validate_evidence(
            record,
            current_head=git(repo, "rev-parse", "HEAD"),
            current_workspace=snapshot(repo).fingerprint,
            expected_success=True,
        )
    except EvidenceValidationError as exc:
        assert str(exc) == "EVIDENCE_WORKSPACE_STALE"
    else:
        raise AssertionError("product edit must stale evidence")
