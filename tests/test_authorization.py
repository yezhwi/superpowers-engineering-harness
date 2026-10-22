import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    assert cli(repo, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


def task(repo):
    return yaml.safe_load((repo / ".harness/current-task.yaml").read_text())


def test_authorizations_are_independent(tmp_path):
    setup(tmp_path)
    result = cli(tmp_path, "authorize", "commit")

    assert result.returncode == 0
    assert task(tmp_path)["authorizations"]["commit"]["granted"] is True
    assert task(tmp_path)["authorizations"]["push"]["granted"] is False


def test_full_suite_is_forbidden_even_with_other_authorization(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, "authorize", "commit").returncode == 0

    result = cli(
        tmp_path,
        "evidence",
        "--type",
        "unit_test",
        "--scope",
        "full_suite",
        "--command",
        "true",
    )

    assert result.returncode == 2
    assert "FULL_SUITE_FORBIDDEN" in result.stderr


def test_candidate_commit_requires_independent_commit_grant_and_never_grants_push(tmp_path, monkeypatch, capsys):
    """Isolated authority seam; real complete lifecycle is tested in CLI recovery."""
    import pytest
    from test_transaction_recovery import _prepared_candidate_intent
    from harness import controlplane
    from harness.candidate_commit import CandidateRefusal, controlled_commit

    repo, operation, operation_path, current = _prepared_candidate_intent(tmp_path, monkeypatch, gate_bound=True)
    operation_path.unlink()
    monkeypatch.chdir(repo)
    message = tmp_path / 'message.txt'
    message.write_text('candidate\n')
    index = (repo / '.git/index').read_bytes()
    with pytest.raises(CandidateRefusal, match='USER_AUTHORITY_REQUIRED'):
        controlled_commit(repo, operation['payload']['candidate_id'], message)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip() == operation['payload']['parent']
    assert controlplane.cmd_authorize('commit', True) == 0
    result = controlled_commit(repo, operation['payload']['candidate_id'], message)
    assert result['status'] == 'COMMITTED'
    current = task(repo)
    assert current['authorizations']['commit']['granted'] is False
    assert all(current['authorizations'][name]['granted'] is False for name in ('push', 'create_mr', 'ready_mr', 'merge', 'deploy'))
    assert (repo / '.git/index').read_bytes() == index


def test_candidate_commit_authority_is_narrow_and_non_inheriting(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, "authorize", "commit").returncode == 0
    current = task(tmp_path)
    assert current["authorizations"]["commit"]["granted"] is True
    assert all(not current["authorizations"][name]["granted"] for name in ("push", "create_mr", "ready_mr", "merge", "deploy"))
