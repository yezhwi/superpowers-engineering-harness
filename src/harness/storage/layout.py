"""Read-only ownership admission for repository-local stable storage.

Directory identity is separate from file content. A pathname or matching bytes
never grant ownership; malformed/partially initialized storage fails closed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import os
import stat

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.schema_resources import read_schema

CAPABILITY = "harness-storage-layout/v1"
_LIMIT = 256 * 1024


class StorageError(OSError):
    """A stable refusal code, never the raw source payload."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LayoutInspection:
    mode: str
    code: str | None = None
    identity: dict | None = None


@dataclass(frozen=True)
class StorageSession:
    repo_root: Path
    harness_root: Path
    layout: LayoutInspection


def observation_paths(harness_root):
    """Fixed namespace facts only, not read authority for all store payloads."""
    root = Path(harness_root).absolute()
    store = root.parent / ".harness-store"
    return (store, store / "store.yaml", store / "operations", root / "storage-binding.yaml",
            root / "gate.yaml", root / '.transactions')


def _present(path):
    return source_access.is_symlink(path) or source_access.exists(path)


def _directory_identity(path, repo):
    return source_access.node_identity_beneath(path, repo, node_kind="directory")["identity"]


def _document(path, repo):
    snapshot = source_access.read_regular_snapshot_beneath(path, repo, max_bytes=_LIMIT)
    result = yaml.safe_load(snapshot.content)
    if not isinstance(result, dict):
        raise StorageError("STORE_IDENTITY_CHANGED")
    if result.get("version") != 1 or result.get("capabilities") != [CAPABILITY]:
        raise StorageError("STORE_READER_UNSUPPORTED")
    validate(result, read_schema("storage-layout.schema.json"))
    return result


def _refuse_bootstrap(repo):
    """Recognize reserved coordinator names without reading regular journals.

    This is refusal only, never recovery authority. Ordinary v1/v2 publisher
    validation can still inspect its own layout with its own journal present.
    """
    directory = repo / '.harness/.transactions'
    if source_access.is_symlink(directory):
        raise StorageError('STORE_RECOVERY_REQUIRED')
    if not source_access.exists(directory):
        return
    source_access._check(directory, explicit=True)
    opened = source_access._open_beneath(directory, repo)
    try:
        if not stat.S_ISDIR(os.fstat(opened).st_mode):
            raise StorageError('STORE_RECOVERY_REQUIRED')
        names = []
        with os.scandir(opened) as entries:
            for entry in entries:
                if len(names) >= 1024 or entry.name.startswith('storage-activation-'):
                    raise StorageError('STORE_RECOVERY_REQUIRED')
                names.append(entry.name)
        source_access._observe(directory, 'members', tuple(sorted(names)), '*')
    finally:
        os.close(opened)


def _inspect(repo):
    _refuse_bootstrap(repo)
    store = repo / ".harness-store"
    root = repo / ".harness"
    binding_path = root / "storage-binding.yaml"
    if not _present(store):
        if _present(binding_path):
            raise StorageError("STORE_IDENTITY_CHANGED")
        return LayoutInspection("legacy")
    if source_access.is_symlink(store) or not source_access.is_dir(store):
        raise StorageError("STORE_UNOWNED")
    if not _present(store / "store.yaml"):
        raise StorageError("STORE_UNOWNED")
    header = _document(store / "store.yaml", repo)
    if header["kind"] != "store":
        raise StorageError("STORE_IDENTITY_CHANGED")
    store_identity = _directory_identity(store, repo)
    if (header["workspace_root"] != str(repo)
            or header["workspace_identity"] != _directory_identity(repo, repo)
            or header["store_identity"] != store_identity):
        raise StorageError("STORE_IDENTITY_CHANGED")
    operations = store / "operations"
    # Membership is recovery admission, not permission to read any operation.
    if source_access.is_symlink(operations) or not source_access.is_dir(operations):
        raise StorageError("STORE_IDENTITY_CHANGED")
    source_access._check(operations, explicit=True)
    descriptor = source_access._open_beneath(operations, repo)
    try:
        names = tuple(sorted(os.listdir(descriptor)))
        source_access._observe(operations, "members", names, "*")
        if names:
            raise StorageError("STORE_RECOVERY_REQUIRED")
    finally:
        os.close(descriptor)
    if not _present(binding_path):
        raise StorageError("STORE_IDENTITY_CHANGED")
    binding = _document(binding_path, repo)
    if (binding["kind"] != "binding"
            or binding["store_id"] != header["store_id"]
            or binding["workspace_id"] != header["workspace_id"]
            or binding["store_identity"] != store_identity
            or binding["root_identity"] != _directory_identity(root, repo)):
        raise StorageError("STORE_IDENTITY_CHANGED")
    snapshot = source_access.read_regular_snapshot_beneath(root / 'gate.yaml', repo, max_bytes=_LIMIT)
    gate = yaml.safe_load(snapshot.content)
    gate_body = gate.get('gate') if isinstance(gate, dict) else None
    marker = gate_body.get('storage_layout') if isinstance(gate_body, dict) else None
    if (not isinstance(marker, dict) or marker != {'version': 1, 'required_capabilities': [CAPABILITY]}
            or type(marker.get('version')) is not int):
        raise StorageError('STORE_READER_UNSUPPORTED')
    return LayoutInspection("bound", identity={"header": header, "binding": binding})


def inspect_layout(repo_root: Path) -> LayoutInspection:
    """Inspect only; no lock file, probe, root or metadata creation."""
    repo = Path(repo_root).absolute()
    if ".." in repo.parts or repo.is_symlink():
        return LayoutInspection("blocked", "STORE_IDENTITY_CHANGED")
    try:
        return _inspect(repo)
    except StorageError as error:
        return LayoutInspection("blocked", error.code)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError, ValidationError):
        return LayoutInspection("blocked", "STORE_IDENTITY_CHANGED")


def _workspace_root(harness_root):
    from harness.repository import RepositoryNotFoundError, find_git_root

    root = Path(harness_root).absolute()
    try:
        return find_git_root(root.resolve().parent)
    except RepositoryNotFoundError:
        return root.parent


def require_custom_root_admission(harness_root):
    root = Path(harness_root).absolute()
    if root != _workspace_root(root) / '.harness':
        require_layout_admission(root)


def require_layout_admission(harness_root):
    root = Path(harness_root).absolute()
    repo = _workspace_root(root)
    result = inspect_layout(repo)
    if result.mode == "blocked":
        raise StorageError(result.code)
    if result.mode == "bound" and root != repo / '.harness':
        raise StorageError("STORE_IDENTITY_CHANGED")
    return result


@contextmanager
def admit_storage(harness_root: Path):
    from harness.transaction_recovery import PublicationAdmissionError, publication_admission

    root = Path(harness_root).absolute()
    try:
        with publication_admission(root):
            yield StorageSession(root.parent, root, require_layout_admission(root))
    except PublicationAdmissionError as error:
        code = str(error)
        if code.startswith("STORE_"):
            raise StorageError(code) from error
        raise StorageError("STORE_RECOVERY_REQUIRED") from error
