"""Finite workspace Git queries with owned file capture, not arbitrary fd grants."""

import re
import subprocess
from pathlib import Path
from tempfile import TemporaryFile


class GitQueryError(ValueError):
    pass


def _validate(args: tuple[str, ...]) -> None:
    if not args or any(
        not isinstance(arg, str) or not arg or "\0" in arg for arg in args
    ):
        raise GitQueryError("GIT_QUERY_INVALID")
    architecture_pathspec = (
        "--",
        ".",
        ":(exclude).harness",
        ":(exclude).harness/**",
    )
    if args in {
        ("rev-parse", "HEAD"),
        ("rev-parse", "--abbrev-ref", "HEAD"),
        ("ls-files", "--others", "--exclude-standard"),
        ("ls-files", "-z", *architecture_pathspec),
        ("ls-files", "--deleted", "-z", *architecture_pathspec),
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            *architecture_pathspec,
        ),
    }:
        return
    if (
        args[0] == "rev-parse"
        and len(args) == 3
        and args[1] == "--verify"
        and not args[2].startswith("-")
    ):
        return
    if (
        args[0] == "log"
        and len(args) >= 6
        and args[1] == "-1"
        and args[2] == "--format=%H%x09%an%x09%aI"
        and not args[3].startswith("-")
        and args[4] == "--"
        and all(not path.startswith("-") for path in args[5:])
    ):
        return
    if (
        len(args) == 3
        and args[0] == "merge-base"
        and all(not ref.startswith("-") for ref in args[1:])
    ):
        return
    if args[0] == "diff":
        rest = args[1:]
        if rest and rest[0] == "--cached":
            rest = rest[1:]
        if (
            len(rest) >= 4
            and rest[0] in {"--binary", "--name-only"}
            and not rest[1].startswith("-")
            and rest[2] == "--"
        ):
            return
        if (
            len(rest) == 10
            and rest[:5] == (
                "--no-ext-diff",
                "--no-textconv",
                "--name-status",
                "--no-renames",
                "-z",
            )
            and (
                rest[5] == "HEAD"
                or re.fullmatch(r"[0-9a-f]{40,64}\.\.HEAD", rest[5]) is not None
            )
            and rest[6:] == architecture_pathspec
        ):
            return
    raise GitQueryError("GIT_QUERY_INVALID")


def run_git_query(
    repo_root: Path, args: tuple[str, ...]
) -> subprocess.CompletedProcess:
    """Keep stdout/stderr deadlock-free without subprocess.PIPE fd wrapping.

    TemporaryFile handles own their descriptors and close on every exit path.
    No source guard suspension or permission to open pre-existing fds is used.
    Native Git internals remain outside Python source-read auditing.
    """
    args = tuple(args)
    _validate(args)
    command = ["git", "-c", "core.fsmonitor=false", *args]
    if args[0] == "diff" and "--no-ext-diff" not in args:
        command[4:4] = ["--no-ext-diff", "--no-textconv"]
    with TemporaryFile() as stdout, TemporaryFile() as stderr:
        result = subprocess.run(
            command, cwd=repo_root, stdout=stdout, stderr=stderr, check=False
        )
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            command, result.returncode, stdout.read(), stderr.read()
        )
