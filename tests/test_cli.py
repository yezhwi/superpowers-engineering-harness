"""Cross-command P2 CLI contract tests."""

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
