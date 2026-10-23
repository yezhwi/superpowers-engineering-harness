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
