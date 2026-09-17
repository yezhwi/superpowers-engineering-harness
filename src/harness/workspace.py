"""Shared Git workspace facts for evidence, Gate, status, and review scope."""

import hashlib
import re
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


_CONTRACT_REF = re.compile(r"^[A-Z]{2,}-[0-9]+(?::|$)")


def is_contract_ref(value: str) -> bool:
    """True for labels such as DEC-001 or DEC-001:orders, not repo paths."""
    return isinstance(value, str) and bool(_CONTRACT_REF.match(value))


def is_review_file(value: str) -> bool:
    """True for a repository-relative path that is not a contract label."""
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/") or "\\" in value or ".." in value.split("/"):
        return False
    return not is_contract_ref(value)


def canonical_scope_files(files: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Order-insensitive, de-duplicated review file set."""
    return tuple(sorted(set(files)))


def project_typed_scope(
    task: dict,
    impact: dict,
    *,
    inspected_paths: tuple[str, ...] | list[str] = (),
    direct_dependencies: tuple[str, ...] | list[str] = (),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split review files from contract labels. Do not mix then compare as paths."""
    scope = task.get("scope") or {}
    files: list[str] = []
    refs: list[str] = []
    for item in (
        *(scope.get("owned_paths") or ()),
        *(impact.get("contracts") or ()),
        *(impact.get("direct_dependents") or ()),
        *inspected_paths,
        *direct_dependencies,
    ):
        if is_contract_ref(item):
            refs.append(item)
        elif is_review_file(item):
            files.append(item)
    return canonical_scope_files(files), canonical_scope_files(refs)


def project_task_scope(
    task: dict,
    impact: dict,
    *,
    inspected_paths: tuple[str, ...] | list[str] = (),
    direct_dependencies: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    """Project owned, path-like contract, dependency, and inspected paths.

    Protected user paths never enter this set unless they are also owned,
    contracted, inspected, or declared as dependencies. Contract labels such
    as ``DEC-001:`` stay in ``project_typed_scope`` refs, not files.
    """
    files, _refs = project_typed_scope(
        task,
        impact,
        inspected_paths=inspected_paths,
        direct_dependencies=direct_dependencies,
    )
    return files


def claimed_scope_sets(review_scope: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read files/contract_refs; migrate DEC-* labels out of files."""
    files: list[str] = []
    refs: list[str] = list(review_scope.get("contract_refs") or [])
    for item in review_scope.get("files") or []:
        if is_contract_ref(item):
            refs.append(item)
        elif item:
            files.append(item)
    return canonical_scope_files(files), canonical_scope_files(refs)


def scope_files_mismatch(claimed, expected) -> str | None:
    """Return a DIAGNOSABILITY_SCOPE_MISMATCH message, or None if sets match."""
    actual = set(claimed)
    want = set(expected)
    if actual == want:
        return None
    extra = sorted(actual - want)
    missing = sorted(want - actual)
    parts = ["DIAGNOSABILITY_SCOPE_MISMATCH"]
    if extra:
        parts.append("actual-only: " + ", ".join(extra))
    if missing:
        parts.append("expected-only: " + ", ".join(missing))
    return "; ".join(parts)


def scope_projection_mismatch(
    claimed_files, expected_files, claimed_refs=(), expected_refs=()
) -> str | None:
    """Compare path files and contract refs as independent sets."""
    file_msg = scope_files_mismatch(claimed_files, expected_files)
    ref_msg = scope_files_mismatch(claimed_refs, expected_refs)
    if not file_msg and not ref_msg:
        return None
    if file_msg and not ref_msg:
        return file_msg
    parts = ["DIAGNOSABILITY_SCOPE_MISMATCH"]
    if file_msg:
        parts.extend(file_msg.split("; ")[1:])
    if ref_msg:
        suffix = "; ".join(ref_msg.split("; ")[1:])
        parts.append("contract_refs " + suffix if suffix else "contract_refs")
    return "; ".join(parts)


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
