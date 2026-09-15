"""Shared Git workspace facts for evidence, Gate, status, and review scope."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from .git_query import GitQueryError, run_git_query


class WorkspaceError(RuntimeError):
    """Git repository state cannot be read deterministically."""


@dataclass(frozen=True)
class WorkspaceSnapshot:
    head: str
    fingerprint: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class ReviewScope:
    base_ref: str
    base_commit: str
    head_commit: str
    workspace: WorkspaceSnapshot
    files: tuple[str, ...]


def _root(repo_root: Path | None) -> Path:
    return (repo_root or Path.cwd()).resolve()


def _run(repo_root: Path, *args: str) -> bytes:
    try:
        result = run_git_query(repo_root, args)
    except GitQueryError as exc:
        raise WorkspaceError(str(exc)) from exc
    if result.returncode:
        raise WorkspaceError(result.stderr.decode().strip())
    return result.stdout


def git_head(repo_root: Path | None = None) -> str:
    """Return current full Git HEAD SHA."""
    root = _root(repo_root)
    try:
        return _run(root, "rev-parse", "HEAD").decode().strip()
    except WorkspaceError as exc:
        raise WorkspaceError(f"cannot resolve git HEAD: {exc}") from exc


def git_baseline(head: str | None = None, repo_root: Path | None = None) -> dict:
    """Freeze task Git identity: branch name when attached, otherwise the SHA."""
    sha = head or git_head(repo_root)
    try:
        ref = (
            _run(_root(repo_root), "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
        )
    except WorkspaceError:
        ref = sha
    if not ref or ref == "HEAD":
        ref = sha
    return {
        "base_ref": ref,
        "base_commit": sha,
        "head_at_start": sha,
        "head": sha,
    }


def observability_inspected_paths(harness_dir: Path) -> tuple[str, ...]:
    """Return observability inspected paths; missing contract yields an empty tuple."""
    from harness import source_access

    path = harness_dir / "observability.yaml"
    if not source_access.is_file(path):
        return ()
    try:
        document = yaml.safe_load(source_access.read_text(path)) or {}
    except (OSError, yaml.YAMLError):
        return ()
    if not isinstance(document, dict) or not document.get("required"):
        return ()
    paths = (document.get("applicability") or {}).get("inspected_paths") or ()
    return tuple(path for path in paths if path and path != ".")


_PRODUCT_EXCLUDE = (":(exclude).harness", ":(exclude).harness/**")


def _untracked_paths(repo_root: Path) -> set[str]:
    paths = set()
    for name in (
        _run(repo_root, "ls-files", "--others", "--exclude-standard")
        .decode()
        .splitlines()
    ):
        candidate = Path(name)
        # Git owns discovery. Avoid a pre-scope Path.is_file metadata probe;
        # later scoped reads bind actual file content and fail closed on races.
        if (
            name
            and not candidate.is_absolute()
            and ".." not in candidate.parts
            and not (name == ".harness" or name.startswith(".harness/"))
        ):
            paths.add(name)
    return paths


def _working_paths(repo_root: Path) -> set[str]:
    paths = set()
    for args in (
        ("diff", "--name-only", "HEAD", "--", ".", *_PRODUCT_EXCLUDE),
        ("diff", "--cached", "--name-only", "HEAD", "--", ".", *_PRODUCT_EXCLUDE),
    ):
        paths.update(
            name for name in _run(repo_root, *args).decode().splitlines() if name
        )
    return paths | _untracked_paths(repo_root)


def _fingerprint(repo_root: Path) -> str:
    """Product workspace fingerprint; control-plane files are excluded."""
    parts = [
        _run(repo_root, "rev-parse", "HEAD"),
        _run(repo_root, "diff", "--binary", "HEAD", "--", ".", *_PRODUCT_EXCLUDE),
        _run(
            repo_root,
            "diff",
            "--cached",
            "--binary",
            "HEAD",
            "--",
            ".",
            *_PRODUCT_EXCLUDE,
        ),
    ]
    from harness.source_access import _package_open

    for name in sorted(_untracked_paths(repo_root)):
        path = repo_root / name
        with _package_open(path):
            parts.extend([name.encode(), hashlib.sha256(path.read_bytes()).digest()])
    return "sha256:" + hashlib.sha256(b"\0".join(parts)).hexdigest()


def changed_paths_since(
    base_commit: str, repo_root: Path | None = None
) -> tuple[str, ...]:
    """Changed business paths from immutable baseline through current workspace."""
    root = _root(repo_root)
    committed = _run(
        root,
        "diff",
        "--name-only",
        f"{base_commit}..HEAD",
        "--",
        ".",
        *_PRODUCT_EXCLUDE,
    )
    paths = set(name for name in committed.decode().splitlines() if name)
    paths.update(snapshot(root).changed_paths)
    return tuple(sorted(paths))


def protected_paths_fingerprint(
    paths: tuple[str, ...], repo_root: Path | None = None
) -> str:
    """Fingerprint only declared pre-existing user changes."""
    from harness import source_access

    root = _root(repo_root)
    parts: list[bytes] = []
    for name in sorted(paths):
        path = root / name
        diff = _run(root, "diff", "--binary", "HEAD", "--", name)
        parts.extend([name.encode(), diff])
        if not diff and source_access.is_file(path):
            parts.append(hashlib.sha256(source_access.read_bytes(path)).digest())
    return "sha256:" + hashlib.sha256(b"\0".join(parts)).hexdigest()


def snapshot(repo_root: Path | None = None) -> WorkspaceSnapshot:
    """Return HEAD plus all current business changes under one ignore policy."""
    root = _root(repo_root)
    return WorkspaceSnapshot(
        head=git_head(root),
        fingerprint=_fingerprint(root),
        changed_paths=tuple(sorted(_working_paths(root))),
    )


def product_workspace_fingerprint(repo_root: Path | None = None) -> str:
    """Fingerprint product code, tests, and non-control-plane config."""
    return snapshot(repo_root).fingerprint


def control_plane_fingerprint(harness_dir: Path | None = None) -> str:
    """Fingerprint `.harness/` metadata without affecting product freshness."""
    root = (harness_dir or Path(".harness")).resolve()
    parts: list[bytes] = []
    if root.is_dir():
        for path in sorted(
            candidate for candidate in root.rglob("*") if candidate.is_file()
        ):
            parts.extend(
                [
                    path.relative_to(root).as_posix().encode(),
                    hashlib.sha256(path.read_bytes()).digest(),
                ]
            )
    return "sha256:" + hashlib.sha256(b"\0".join(parts)).hexdigest()


def project_task_scope(
    task: dict,
    impact: dict,
    *,
    inspected_paths: tuple[str, ...] | list[str] = (),
    direct_dependencies: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    """Project owned, contract, dependency, and inspected paths into review files.

    Protected user paths never enter this set unless they are also owned,
    contracted, inspected, or declared as dependencies.
    """
    scope = task.get("scope") or {}
    included = set(scope.get("owned_paths") or ())
    included.update(impact.get("contracts") or ())
    included.update(impact.get("direct_dependents") or ())
    included.update(inspected_paths)
    included.update(direct_dependencies)
    return tuple(sorted(included))


def review_scope(base_ref: str, repo_root: Path | None = None) -> ReviewScope:
    """Return effective review files from merge-base through current workspace."""
    root = _root(repo_root)
    base_commit = _run(root, "merge-base", base_ref, "HEAD").decode().strip()
    current = snapshot(root)
    committed = (
        _run(
            root,
            "diff",
            "--name-only",
            f"{base_commit}..{current.head}",
            "--",
            ".",
            *_PRODUCT_EXCLUDE,
        )
        .decode()
        .splitlines()
    )
    files = tuple(
        sorted(set(name for name in committed if name) | set(current.changed_paths))
    )
    return ReviewScope(
        base_ref=base_ref,
        base_commit=base_commit,
        head_commit=current.head,
        workspace=current,
        files=files,
    )
