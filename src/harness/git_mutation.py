"""Fixed native-Git mutation seam for candidate publication only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from . import source_access


class GitMutationError(RuntimeError):
    pass


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    # Never silently discard an injected Git input or ignore system configuration.
    if any(key.startswith("GIT_") for key in os.environ):
        raise GitMutationError("GIT_MUTATION_ENV_UNSUPPORTED")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if extra:
        allowed = {f"GIT_{role}_{field}" for role in ("AUTHOR", "COMMITTER")
                   for field in ("NAME", "EMAIL", "DATE")}
        if set(extra) != allowed or any(
            not isinstance(value, str) or not value or any(c in value for c in "\x00\r\n")
            for value in extra.values()
        ):
            raise GitMutationError("GIT_MUTATION_ENV_UNSUPPORTED")
        env.update(extra)
    return env


def _run(repo: Path, args: tuple[str, ...], *, identity=None, message=None) -> bytes:
    env = _environment(identity)
    executable = shutil.which("git", path=env.get("PATH"))
    if executable is None:
        raise GitMutationError("GIT_MUTATION_TOOL_UNSUPPORTED")
    try:
        result = subprocess.run([executable, *args], cwd=repo, env=env,
                                input=message, capture_output=True)
    except OSError as exc:
        raise GitMutationError("GIT_MUTATION_IO_UNSUPPORTED") from exc
    if result.returncode:
        raise GitMutationError("GIT_MUTATION_COMMAND_UNSUPPORTED")
    return result.stdout


def repository_policy(repo: Path) -> dict:
    """Bind effective config, hook bytes, tool and relevant environment; no overrides."""
    _environment()
    git_dir = repo / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise GitMutationError("GIT_MUTATION_REPOSITORY_UNSUPPORTED")
    unsupported = ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                   "BISECT_LOG", "sequencer", "rebase-apply", "rebase-merge",
                   "info/grafts", "objects/info/alternates", "refs/replace", "index.lock")
    if any(os.path.lexists(git_dir / name) for name in unsupported):
        raise GitMutationError("GIT_MUTATION_STATE_UNSUPPORTED")
    index = git_dir / 'index'
    if (not os.path.lexists(index) or not stat.S_ISREG(index.lstat().st_mode)
            or any(git_dir.glob('sharedindex.*'))):
        raise GitMutationError("GIT_MUTATION_INDEX_UNSUPPORTED")
    if _run(repo, ("rev-parse", "--show-object-format")).strip() != b"sha1":
        raise GitMutationError("GIT_MUTATION_REPOSITORY_UNSUPPORTED")
    raw = _run(repo, ("config", "--null", "--list"))
    config = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        key, _, value = entry.partition(b"\n")
        config[key.decode("utf-8").lower()] = value.decode("utf-8")
    denied = {"core.hookspath", "core.fsmonitor", "core.worktree", "core.sparsecheckout",
              "core.sparsecheckoutcone", "core.splitindex", "commit.template",
              "commit.cleanup", "commit.signoff", "index.sparse"}
    if any(key in denied or key.startswith(("filter.", "extensions.", "includeif."))
           for key in config):
        raise GitMutationError("GIT_MUTATION_CONFIG_UNSUPPORTED")
    if config.get("commit.gpgsign", "false").lower() not in {"false", "no", "0", "off"}:
        raise GitMutationError("GIT_MUTATION_CONFIG_UNSUPPORTED")
    paths = _run(repo, ('ls-files', '-z')).split(b'\0')[:-1]
    debug = _run(repo, ('ls-files', '--debug', '-z'))
    flags = re.findall(rb'[ \t]flags: ([0-9a-f]+)$', debug, re.MULTILINE)
    if len(flags) != len(paths) or any(int(value, 16) & 0x60008000 for value in flags):
        raise GitMutationError("GIT_MUTATION_INDEX_UNSUPPORTED")
    hooks = {}
    directory = git_dir / "hooks"
    if directory.is_symlink():
        raise GitMutationError("GIT_MUTATION_HOOK_UNSUPPORTED")
    if directory.exists():
        for path in sorted(directory.iterdir()):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or (
                not path.name.endswith(".sample") and info.st_mode & 0o111
            ):
                raise GitMutationError("GIT_MUTATION_HOOK_UNSUPPORTED")
            hooks[path.name] = [stat.S_IMODE(info.st_mode),
                                _digest(source_access.read_regular_bytes_beneath(path, git_dir))]
    executable = Path(shutil.which("git")).resolve()
    environment = {key: os.environ.get(key) for key in
                   ("HOME", "XDG_CONFIG_HOME", "PATH", "LANG", "LC_ALL", "TZ")}
    origins = _run(repo, ("config", "--null", "--show-origin", "--list"))
    pieces = origins.rstrip(b"\0").split(b"\0")
    sources = {}
    try:
        if len(pieces) % 2:
            raise ValueError('invalid config origins')
        for origin in pieces[::2]:
            if not origin.startswith(b"file:"):
                raise ValueError('unsupported config origin')
            path = Path(os.fsdecode(origin[5:]))
            if not path.is_absolute():
                path = repo / path
            sources[os.fsdecode(origin)] = _digest(
                source_access.read_regular_bytes_beneath(path, path.parent)
            )
    except (OSError, ValueError) as exc:
        raise GitMutationError("GIT_MUTATION_CONFIG_UNSUPPORTED") from exc
    return {
        "config": _digest(origins + json.dumps(sources, sort_keys=True).encode()),
        "hooks": _digest(json.dumps(hooks, sort_keys=True).encode()),
        "tool": _digest(executable.read_bytes()),
        "environment": _digest(json.dumps(environment, sort_keys=True).encode()),
        "author_name": config.get("user.name"),
        "author_email": config.get("user.email"),
    }


def _oid(value: str) -> bool:
    return isinstance(value, str) and len(value) == 40 and set(value) <= set("0123456789abcdef")


def commit_tree(repo: Path, tree: str, parent: str, message: bytes, identity: dict[str, str]) -> str:
    if not all(_oid(value) for value in (tree, parent)):
        raise GitMutationError("GIT_MUTATION_OBJECT_INVALID")
    repository_policy(repo)
    oid = _run(repo, ("commit-tree", tree, "-p", parent), identity=identity,
               message=message).decode("ascii").strip()
    if not _oid(oid):
        raise GitMutationError("GIT_MUTATION_OBJECT_INVALID")
    return oid


def update_ref(repo: Path, full_ref: str, proposed: str, expected_old: str) -> None:
    if (not isinstance(full_ref, str) or not full_ref.startswith("refs/heads/")
            or any(ch.isspace() or ord(ch) < 32 for ch in full_ref)
            or not all(_oid(value) for value in (proposed, expected_old))):
        raise GitMutationError("GIT_MUTATION_REF_INVALID")
    repository_policy(repo)
    try:
        _run(repo, ("update-ref", full_ref, proposed, expected_old))
    except GitMutationError as exc:
        if str(exc) == "GIT_MUTATION_COMMAND_UNSUPPORTED":
            raise GitMutationError("CANDIDATE_REF_CONFLICT") from exc
        raise
