"""Cross-command P2 CLI contract tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def cli(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


def test_gate_preview_command_is_not_introduced(tmp_path):
    result = cli(tmp_path, "gate", "preview")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice: 'preview'" in result.stderr


@pytest.mark.parametrize(
    "args,suggestion",
    [
        (("plan", "status", "--verbsoe"), "--verbose"),
        (("plan", "status", "--jsno=true"), "--json"),
        (("context", "--profle-json=profile.json"), "--profile-json"),
        (("context", "validate", "--jsno"), "--json"),
        (("architecture", "scope", "add", "MOD-001", "--hepl"), "--help"),
        (("evidence", "run", "--type", "unit_test", "--command", "true",
          "--coverd-test", "tests/test_x.py"), "--covered-test"),
        (("evidence", "plan", "--jsno"), "--json"),
    ],
)
def test_unknown_flag_suggests_current_command_option_without_execution(
    tmp_path, args, suggestion
):
    result = cli(tmp_path, *args)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unrecognized arguments:" in result.stderr
    assert f"Did you mean: {suggestion}?" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        ("plan", "begin", "P-001", "--verbsoe"),
        ("plan", "status", "--reasno"),
        ("context", "validate", "--profle-json", "profile.json"),
        ("architecture", "scope", "add", "MOD-001", "--jsno"),
        ("--verbsoe",),
        ("plan", "status", "--zzzzzzzzzzzzzz"),
        ("plan", "status", "verbose"),
        ("plan", "status", "--", "--verbsoe"),
    ],
)
def test_unknown_flag_never_suggests_unavailable_or_unreliable_option(tmp_path, args):
    result = cli(tmp_path, *args)

    assert result.returncode == 2
    assert "unrecognized arguments:" in result.stderr
    assert "Did you mean:" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_ambiguous_unknown_flag_does_not_guess(capsys):
    from harness.cli import _HarnessArgumentParser

    parser = _HarnessArgumentParser()
    parser.add_argument("--foo-a", action="store_true")
    parser.add_argument("--foo-b", action="store_true")

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--foo-c"])

    assert exc.value.code == 2
    assert "Did you mean:" not in capsys.readouterr().err


def test_partial_parsing_preserves_unknown_flags_for_caller():
    from harness.cli import _HarnessArgumentParser

    parser = _HarnessArgumentParser()
    subcommands = parser.add_subparsers(dest="command")
    status = subcommands.add_parser("status")
    status.add_argument("--verbose", action="store_true")

    parsed, extras = parser.parse_known_args(["status", "--verbsoe"])

    assert parsed.command == "status"
    assert parsed.verbose is False
    assert extras == ["--verbsoe"]


def test_task_prune_public_interface_is_exact(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0

    preview = cli(tmp_path, "task", "prune")
    missing = cli(tmp_path, "task", "prune", "--apply")
    extra = cli(tmp_path, "task", "prune", "--keep", "4")

    assert preview.returncode == 0
    assert json.loads(preview.stdout)["phase"] == "preview"
    assert missing.returncode == 2 and missing.stderr == "TASK_PRUNE_ARGUMENTS_INVALID\n"
    assert extra.returncode == 2 and extra.stderr == "TASK_PRUNE_ARGUMENTS_INVALID\n"


def test_task_prune_output_is_structured_and_sanitized(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0

    result = cli(tmp_path, "task", "prune", "--apply", "--plan-id", "bad\n/private/secret")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert set(payload) == {"task_id", "plan_id", "reason", "counts", "phase", "mutation_started"}
    assert "/private/secret" not in result.stdout + result.stderr
    assert "\n/private/secret" not in result.stdout + result.stderr


def test_task_prune_recursive_yaml_is_one_sanitized_json_error(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    (tmp_path / ".harness/requirements.yaml").write_text("secret: &loop [*loop]\n")

    result = cli(tmp_path, "task", "prune")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["reason"] == "STRUCTURED_INPUT_LIMIT"
    assert "/" not in result.stderr and "secret" not in result.stderr


def test_task_prune_invalid_arguments_use_bounded_command_specific_refusal(tmp_path):
    sentinel = os.environ.get("HOME", "/private/environment-secret")
    cases = [
        ("--unknown", sentinel),
        ("--plan-id",),
        ("--bad\n/private/control",),
        ("--unknown", "/private/absolute-secret"),
    ]

    for arguments in cases:
        result = cli(tmp_path, "task", "prune", *arguments)

        assert result.returncode == 2
        assert json.loads(result.stdout) == {
            "counts": {
                "candidate_groups": 0,
                "distinct_ids": 0,
                "logical_bytes": 0,
                "removed_entries": 0,
                "removed_groups": 0,
                "skipped_groups": 0,
                "trusted_groups": 0,
            },
            "mutation_started": False,
            "phase": "refused",
            "plan_id": "",
            "reason": "INVALID_ARGUMENTS",
            "task_id": "UNKNOWN",
        }
        assert result.stderr == "TASK_PRUNE_ARGUMENTS_INVALID\n"
        assert all(token not in result.stdout + result.stderr for token in arguments)
        assert sentinel not in result.stdout + result.stderr

    unchanged = cli(tmp_path, "plan", "status", "--verbsoe")
    assert unchanged.returncode == 2
    assert unchanged.stdout == ""
    assert "unrecognized arguments: --verbsoe" in unchanged.stderr
    assert "Did you mean: --verbose?" in unchanged.stderr


def test_task_prune_outside_repository_is_typed_and_does_not_disclose_path(tmp_path):
    private_root = tmp_path / "private-repository-sentinel"
    private_root.mkdir()

    result = cli(private_root, "task", "prune")

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "counts": {
            "candidate_groups": 0,
            "distinct_ids": 0,
            "logical_bytes": 0,
            "removed_entries": 0,
            "removed_groups": 0,
            "skipped_groups": 0,
            "trusted_groups": 0,
        },
        "mutation_started": False,
        "phase": "refused",
        "plan_id": "",
        "reason": "REPOSITORY_NOT_FOUND",
        "task_id": "UNKNOWN",
    }
    assert result.stderr == "TASK_PRUNE_REPOSITORY_NOT_FOUND\n"
    assert str(private_root) not in result.stdout + result.stderr


def test_task_prune_early_refusals_contain_discovery_and_stream_failures(
    tmp_path,
):
    probe = r'''import io, json, sys
import harness.cli as cli

original_stdout = sys.stdout
original_stderr = sys.stderr

class DeadStream:
    def write(self, _value):
        raise OSError("private stream path")
    def flush(self):
        raise OSError("private stream path")

normal_stdout = io.StringIO()
normal_stderr = io.StringIO()
cli.sys.stdout = normal_stdout
cli.sys.stderr = normal_stderr
try:
    cli._task_prune(["--normal-private-argument"])
except SystemExit as exc:
    normal_code = exc.code

captured = io.StringIO()
cli.sys.stdout = DeadStream()
cli.sys.stderr = captured
try:
    cli._task_prune(["--private-argument"])
except SystemExit as exc:
    invalid_code = exc.code
invalid_stderr = captured.getvalue()

cli.sys.stderr = DeadStream()
try:
    cli._task_prune(["--another-private-argument"])
except SystemExit as exc:
    both_dead_code = exc.code

discovery_stdout = io.StringIO()
discovery_stderr = io.StringIO()
cli.sys.stdout = discovery_stdout
cli.sys.stderr = discovery_stderr
cli.find_git_root = lambda _path: (_ for _ in ()).throw(OSError("/private/discovery-path"))
discovery_code = cli._task_prune([])

cli.sys.stdout = original_stdout
cli.sys.stderr = original_stderr
original_stdout.write(json.dumps({
    "invalid_code": invalid_code,
    "invalid_stderr": invalid_stderr,
    "normal_code": normal_code,
    "normal_stdout": normal_stdout.getvalue(),
    "normal_stderr": normal_stderr.getvalue(),
    "both_dead_code": both_dead_code,
    "discovery_code": discovery_code,
    "discovery_stdout": discovery_stdout.getvalue(),
    "discovery_stderr": discovery_stderr.getvalue(),
}))
'''
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )
    assert result.returncode == 0
    observed = json.loads(result.stdout)
    assert observed["normal_code"] == 2
    assert json.loads(observed["normal_stdout"])["reason"] == "INVALID_ARGUMENTS"
    assert observed["normal_stderr"] == "TASK_PRUNE_ARGUMENTS_INVALID\n"
    assert "normal-private-argument" not in json.dumps(observed)
    assert observed["invalid_code"] == 2
    emergency = json.loads(observed["invalid_stderr"])
    assert emergency["reason"] == "RESULT_EMISSION_FAILED"
    assert emergency["counts"]["removed_entries"] == 0
    assert "private" not in observed["invalid_stderr"]
    assert observed["both_dead_code"] == 2
    assert observed["discovery_code"] == 2
    assert json.loads(observed["discovery_stdout"])["reason"] == "REPOSITORY_NOT_FOUND"
    assert observed["discovery_stderr"] == "TASK_PRUNE_REPOSITORY_NOT_FOUND\n"
    assert "/private/discovery-path" not in json.dumps(observed)
def test_candidate_commit_reports_sanitized_durable_outcomes_with_dead_streams(tmp_path, monkeypatch):
    from test_workspace import candidate_repo, git
    from harness import cli as command_line
    from harness.schema_resources import read_schema
    from jsonschema import validate

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / 'config'))
    repo = candidate_repo(tmp_path)
    (repo / 'tracked.py').write_text('value = 2\n')
    git(repo, 'add', 'tracked.py')
    index = (repo / '.git/index').read_bytes()
    result = cli(repo, 'candidate', 'prepare', '--path', 'tracked.py', '--json')
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    validate(document, read_schema('candidate-command-result.schema.json'))
    assert document['schema'] == 'candidate-command-result/v1'
    assert document['ok'] is True
    assert document['command'] == 'candidate prepare'
    assert document['phase'] == 'PREPARED'
    assert document['mutation_started'] is False
    artifact = repo / document['artifact_ref']
    original = artifact.read_bytes()
    class DeadStream:
        def write(self, text):
            raise BrokenPipeError('secret absolute path must never escape')
        def flush(self):
            raise BrokenPipeError('secret absolute path must never escape')
    with monkeypatch.context() as patch:
        patch.chdir(repo)
        patch.setattr(sys, 'stdout', DeadStream())
        patch.setattr(sys, 'stderr', DeadStream())
        assert command_line.main(['candidate', 'prepare', '--path', 'tracked.py', '--json']) == 0
    assert artifact.read_bytes() == original
    assert (repo / '.git/index').read_bytes() == index
    from test_cli_task_recovery import _exercise_candidate_workflow
    strict = tmp_path / 'strict'
    strict.mkdir()
    _exercise_candidate_workflow(strict, faults=True)


def test_candidate_command_correlates_under_same_task_lock(tmp_path, monkeypatch, capsys):
    import threading
    import yaml
    from test_workspace import candidate_repo, git
    from harness import candidate_commit, cli as command_line
    from harness.telemetry_lock import telemetry_lock

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / 'config'))
    repo = candidate_repo(tmp_path)
    (repo / 'tracked.py').write_text('value = 2\n')
    git(repo, 'add', 'tracked.py')
    attempted, acquired = threading.Event(), threading.Event()
    original = candidate_commit.command_result
    workers = []
    def competing_task():
        attempted.set()
        with telemetry_lock(repo / '.harness'):
            path = repo / '.harness/current-task.yaml'
            task = yaml.safe_load(path.read_text())
            task['task']['id'] = 'TASK-2'
            path.write_text(yaml.safe_dump(task))
            acquired.set()
    def correlated(*args, **kwargs):
        worker = threading.Thread(target=competing_task)
        workers.append(worker)
        worker.start()
        assert attempted.wait(2)
        acquired.wait(0.15)
        return original(*args, **kwargs)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(candidate_commit, 'command_result', correlated)
    try:
        assert command_line.main(['candidate', 'prepare', '--path', 'tracked.py', '--json']) == 0
    finally:
        for worker in workers:
            worker.join(timeout=5)
    document = json.loads(capsys.readouterr().out)
    assert document['task_id'] == 'TASK-1'
    assert acquired.is_set()


@pytest.mark.parametrize('boundary', ['lock', 'correlation'])
def test_candidate_boundary_failure_is_sanitized_unknown_outcome(tmp_path, monkeypatch, capsys, boundary):
    import importlib
    from test_workspace import candidate_repo
    from harness import candidate_commit, cli as command_line

    repo = candidate_repo(tmp_path)
    def fault(*args, **kwargs):
        raise OSError('/private/home/SECRET_TOKEN=secret-value')
    if boundary == 'lock':
        monkeypatch.setattr(importlib.import_module('harness.telemetry_lock'), 'telemetry_lock', fault)
    else:
        monkeypatch.setattr(candidate_commit, 'command_result', fault)
    monkeypatch.chdir(repo)
    assert command_line.main(['candidate', 'status', '--candidate', 'sha256:' + 'a' * 64, '--json']) == 70
    output = capsys.readouterr()
    assert 'SECRET_TOKEN' not in output.out + output.err
    document = json.loads(output.out)
    assert document['reason_code'] == 'CANDIDATE_INTERNAL_ERROR'
    assert document['phase'] == 'UNKNOWN' and document['mutation_started'] is None


def test_candidate_unknown_intent_reports_uncertainty_not_false_no_mutation(tmp_path, monkeypatch):
    from test_workspace import candidate_repo, git
    from harness.candidate_commit import prepare

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / 'config'))
    repo = candidate_repo(tmp_path)
    (repo / 'tracked.py').write_text('value = 2\n')
    git(repo, 'add', 'tracked.py')
    prepared = prepare(repo, ['tracked.py'])
    operations = repo / '.harness/.candidate-operations'
    operations.mkdir()
    (operations / ('a' * 64 + '.json')).write_text('{}')
    result = cli(repo, 'candidate', 'status', '--candidate', prepared['candidate'], '--json')
    assert result.returncode == 1
    outcome = json.loads(result.stdout)
    assert outcome['reason_code'] == 'RECOVERY_UNSUPPORTED'
    assert outcome['phase'] == 'UNKNOWN'
    assert outcome['mutation_started'] is None


def test_candidate_internal_exception_is_sanitized_exit70(tmp_path, monkeypatch, capsys):
    from test_workspace import candidate_repo
    from harness import candidate_commit, cli as command_line
    from harness.schema_resources import read_schema
    from jsonschema import validate

    repo = candidate_repo(tmp_path)
    def failing_prepare(*args):
        raise RuntimeError('/private/home/SECRET_TOKEN=secret-value')
    monkeypatch.chdir(repo)
    monkeypatch.setattr(candidate_commit, 'prepare', failing_prepare)
    assert command_line.main(['candidate', 'prepare', '--path', 'tracked.py', '--json']) == 70
    output = capsys.readouterr()
    assert 'SECRET_TOKEN' not in output.out + output.err
    document = json.loads(output.out)
    validate(document, read_schema('candidate-command-result.schema.json'))
    assert document['reason_code'] == 'CANDIDATE_INTERNAL_ERROR'
    assert document['mutation_started'] is False
    assert document['phase'] == 'NOT_STARTED'


@pytest.mark.parametrize('arguments,exit_code', [
    (('candidate', 'prepare', '--path', 'SECRET_MASK_ME'), 2),
    (('candidate', 'prepare', '--pa', 'SECRET_MASK_ME', '--json'), 2),
    (('gate', '--candid', 'SECRET_MASK_ME', '--json'), 2),
    (('gate', '--candidate', 'SECRET_MASK_ME'), 2),
    (('candidate', 'status', '--candidate', 'sha256:' + 'a' * 64, '--json'), 1),
])
def test_candidate_cli_has_closed_sanitized_failure_envelope(tmp_path, arguments, exit_code):
    from jsonschema import validate
    from harness.schema_resources import read_schema

    result = cli(tmp_path, *arguments)
    assert result.returncode == exit_code
    assert 'SECRET_MASK_ME' not in result.stdout + result.stderr
    document = json.loads(result.stdout)
    validate(document, read_schema('candidate-command-result.schema.json'))
    assert document['schema'] == 'candidate-command-result/v1'
    assert document['ok'] is False
    assert document['reason_code'] == 'CANDIDATE_UNSUPPORTED'
    assert document['mutation_started'] is False
    assert not list(tmp_path.iterdir())
