import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    assert cli(repo, "init").returncode == 0
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    task_path = repo / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))


def proposal_args() -> tuple[str, ...]:
    return (
        "--topic",
        "cache",
        "--question",
        "Which cache?",
        "--context",
        "Redis exists",
        "--option",
        "local=local cache",
        "--option",
        "redis=shared cache",
        "--recommend",
        "redis",
        "--reason",
        "existing infrastructure",
        "--tradeoff",
        "network dependency",
        "--scope",
        "src/service/**",
        "--constraint",
        "no new cache",
    )


def test_decision_propose_and_accept_persist_user_choice(tmp_path):
    """Break caught: CLI accepts a choice without durable decision artifact."""
    setup(tmp_path)

    proposed = cli(tmp_path, "decision", "propose", *proposal_args())
    accepted = cli(tmp_path, "decision", "accept", "DEC-001", "--option", "redis")

    assert proposed.returncode == 0, proposed.stderr
    assert accepted.returncode == 0, accepted.stderr
    record = yaml.safe_load(
        (tmp_path / ".harness" / "decisions" / "DEC-001.yaml").read_text()
    )
    assert record["selected"]["option"] == "redis"
    assert record["selected"]["source"] == "accepted_recommendation"


def test_file_proposal_preserves_structured_grant_without_accepting(tmp_path):
    from test_decision import proposal

    setup(tmp_path)
    value = proposal(recommendation='local')
    grant = {'version': 1, 'task_id': 'TASK-042', 'operation': 'MIGRATE',
             'expected_impact_hash': 'sha256:' + 'a' * 64, 'contract_hash': 'sha256:' + 'b' * 64,
             'original_source': {'path': 'original.yaml', 'hash': 'sha256:' + 'c' * 64,
                                 'tests_hash': 'sha256:' + 'd' * 64},
             'historical_sources': [], 'retirements': [], 'bindings': [], 'plan_refs': []}
    value['options'][0]['test_scope_authorization'] = grant
    path = tmp_path / 'proposal.yaml'
    path.write_text(yaml.safe_dump(value))
    result = cli(tmp_path, 'decision', 'propose', '--file', str(path))
    assert result.returncode == 0, result.stderr
    record = yaml.safe_load((tmp_path / '.harness/decisions/DEC-001.yaml').read_text())
    assert record['options'][0]['test_scope_authorization'] == grant
    assert record['status'] == 'PROPOSED' and record['selected'] is None
    assert record['accepted_at'] is None


def test_file_proposal_cannot_mix_flags_or_supply_authoritative_selection(tmp_path):
    from test_decision import proposal

    setup(tmp_path)
    path = tmp_path / 'proposal.yaml'
    value = proposal()
    path.write_text(yaml.safe_dump(value))
    before = (tmp_path / '.harness/decisions/index.yaml').read_bytes()
    mixed = cli(tmp_path, 'decision', 'propose', '--file', str(path), *proposal_args())
    assert mixed.returncode == 2
    value['selected'] = {'option': 'redis', 'source': 'accepted_recommendation', 'decided_by': 'user'}
    path.write_text(yaml.safe_dump(value))
    forged = cli(tmp_path, 'decision', 'propose', '--file', str(path))
    assert forged.returncode == 2
    assert (tmp_path / '.harness/decisions/index.yaml').read_bytes() == before
    assert not (tmp_path / '.harness/decisions/DEC-001.yaml').exists()


def test_missing_file_proposal_fails_cleanly_without_metadata_writes(tmp_path):
    setup(tmp_path)
    before = (tmp_path / '.harness/decisions/index.yaml').read_bytes()
    result = cli(tmp_path, 'decision', 'propose', '--file', str(tmp_path / 'missing.yaml'))
    assert result.returncode == 2
    assert 'Traceback' not in result.stderr
    assert (tmp_path / '.harness/decisions/index.yaml').read_bytes() == before
