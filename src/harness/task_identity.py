"""Reserve task IDs from live authoritative identities, without rewriting history."""
import re
import stat
from pathlib import Path

import yaml

from .source_access import read_regular_bytes_beneath

TASK_ID = re.compile(r"TASK-([0-9]+)")
ARCHIVE_ID = re.compile(r"^(TASK-[0-9]+)(?:-|$)")


class TaskIdentityError(ValueError):
    """Safe task-entry refusal; no identity source could be changed."""


def _key(value):
    if not isinstance(value, str) or not (match := TASK_ID.fullmatch(value)):
        raise TaskIdentityError("TASK_ID_RESERVATION_INVALID")
    return match[1].lstrip("0") or "0"


def _members(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return ()
    if not stat.S_ISDIR(info.st_mode):
        raise TaskIdentityError("TASK_ID_RESERVATION_INVALID")
    return tuple(sorted(path.iterdir()))


def _document(path, root):
    document = yaml.safe_load(read_regular_bytes_beneath(path, root))
    if not isinstance(document, dict):
        raise TaskIdentityError("TASK_ID_RESERVATION_INVALID")
    return document


def require_available(harness_dir: Path, task_id: str, task: dict, *, migration=False):
    """Run under existing publication ownership before any task identity writes.

    History names/documents and persistent decisions reserve IDs, including
    leading-zero aliases. This is not an all-time registry after every identity
    trace has been removed. Legacy same-ID migration preserves existing behavior.
    """
    root = harness_dir.absolute()
    try:
        target = _key(task_id)
        current = task["task"]["id"]
        if migration and current == task_id:
            return  # No new identity; existing scope-binding restrictions still run.
        used = set()
        if current is not None:
            used.add(_key(current))
        for archive in _members(root / "history"):
            named = ARCHIVE_ID.match(archive.name)
            if named:
                used.add(_key(named[1]))
            info = archive.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise TaskIdentityError("TASK_ID_RESERVATION_INVALID")
            if not stat.S_ISDIR(info.st_mode):
                continue
            path = archive / "current-task.yaml"
            try:
                document = _document(path, root)
            except FileNotFoundError:
                continue  # The archive name still reserves its identity.
            identity = document["task"]["id"]
            if identity is not None:
                used.add(_key(identity))
        for path in _members(root / "decisions"):
            if path.name == "index.yaml":
                records = _document(path, root)["decisions"]
                if not isinstance(records, list):
                    raise TaskIdentityError("TASK_ID_RESERVATION_INVALID")
                for record in records:
                    used.add(_key(record["task_id"]))
            elif path.match("DEC-*.yaml"):
                used.add(_key(_document(path, root)["task_id"]))
        if target in used:
            raise TaskIdentityError("TASK_ID_ALREADY_USED")
    except TaskIdentityError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise TaskIdentityError("TASK_ID_RESERVATION_INVALID") from exc
