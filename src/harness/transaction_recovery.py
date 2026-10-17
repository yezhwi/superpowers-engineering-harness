"""Durable publication journal, separate from disposable staging artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

ERROR = 'TRANSACTION_RECOVERY_BLOCKED'


class PublicationAdmissionError(OSError):
    """Canonical facts cannot be consumed until publication is resolved."""


def _locked(root: Path):
    from .telemetry_lock import _HELD
    if str(root.resolve()) not in getattr(_HELD, 'paths', set()):
        raise OSError(f'{ERROR}: publication lock required')


def _path(root: Path, name: str) -> Path:
    relative = Path(name)
    if not name or relative.is_absolute() or '..' in relative.parts:
        raise OSError(f'{ERROR}: invalid journal path')
    target = root / relative
    for member in (root, *target.parents):
        if member == root.parent:
            break
        if member.is_symlink():
            raise OSError(f'{ERROR}: symlink storage')
    if target.is_symlink():
        raise OSError(f'{ERROR}: symlink member')
    if target.exists() and not stat.S_ISREG(target.stat().st_mode):
        raise OSError(f'{ERROR}: nonregular member')
    return target


def _bytes(root: Path, name: str) -> bytes | None:
    from . import source_access
    target = _path(root, name)
    return source_access.read_regular_bytes_beneath(target, root) if target.exists() else None


def _encode(content: bytes | None):
    if content is None:
        return None
    return {'sha256': hashlib.sha256(content).hexdigest(), 'base64': base64.b64encode(content).decode('ascii')}


def _decode(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'sha256', 'base64'}:
        raise ValueError('invalid journal content')
    content = base64.b64decode(value['base64'], validate=True)
    if hashlib.sha256(content).hexdigest() != value['sha256']:
        raise ValueError('journal content hash mismatch')
    return content


def _sync_directory(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _journal(root: Path, path: Path) -> dict:
    try:
        document = json.loads(_bytes(root, path.relative_to(root).as_posix()))
        if set(document) != {'version', 'state', 'members'} or document['version'] != 1:
            raise ValueError('invalid journal')
        if document['state'] not in {'PREPARED', 'COMMITTED'} or not isinstance(document['members'], list):
            raise ValueError('invalid journal state')
        seen = set()
        for member in document['members']:
            if set(member) != {'path', 'before', 'after'} or member['path'] in seen:
                raise ValueError('invalid journal member')
            relative = Path(member['path'])
            if not relative.parts or relative.is_absolute() or '..' in relative.parts or '\\' in member['path']:
                raise ValueError('invalid journal path')
            if member['path'].split('/')[0] in {'.transactions', '.staging', '.publication-retained'}:
                raise ValueError('journal cannot publish recovery storage')
            seen.add(member['path'])
            _decode(member['before'])
            _decode(member['after'])
        return document
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise OSError(f'{ERROR}: invalid journal') from exc


def begin(root: Path, members: list[tuple[Path, bytes | None, bytes | None]]) -> Path:
    _locked(root)
    directory = root / '.transactions'
    if directory.is_symlink():
        raise OSError(f'{ERROR}: symlink journal directory')
    directory.mkdir(mode=0o700, exist_ok=True)
    if any(directory.iterdir()):
        raise OSError(f'{ERROR}: unfinished or unknown operation')
    document = {'version': 1, 'state': 'PREPARED', 'members': []}
    for target, before, after in members:
        name = target.relative_to(root).as_posix()
        _path(root, name)
        if _bytes(root, name) != before:
            raise OSError(f'{ERROR}: member changed before publication')
        document['members'].append({'path': name, 'before': _encode(before), 'after': _encode(after)})
    path = directory / f'{uuid4().hex}.json'
    _write(path, json.dumps(document, sort_keys=True).encode())
    _sync_directory(root)
    return path


def commit(root: Path, path: Path):
    _locked(root)
    document = _journal(root, path)
    for member in document['members']:
        if _bytes(root, member['path']) != _decode(member['after']):
            raise OSError(f'{ERROR}: member changed after publication')
        _sync_directory((root / member['path']).parent)
    document['state'] = 'COMMITTED'
    _write(path, json.dumps(document, sort_keys=True).encode())


def recover_operation(root: Path, path: Path):
    _locked(root)
    document = _journal(root, path)
    unknown = False
    for member in reversed(document['members']):
        name = member['path']
        before, after = _decode(member['before']), _decode(member['after'])
        try:
            current = _bytes(root, name)
        except OSError:
            unknown = True
            continue
        if document['state'] == 'COMMITTED':
            unknown |= current != after
            continue
        if current == before:
            continue
        if current != after:
            unknown = True
            continue  # never restore over bytes this operation does not own
        target = _path(root, name)
        if before is None:
            target.unlink(missing_ok=True)
            _sync_directory(target.parent)
        else:
            _write(target, before)
    if unknown:
        raise OSError(f'{ERROR}: unmanaged or interleaved edit; journal retained')
    path.unlink()
    _sync_directory(path.parent)


def _pending_paths(root: Path) -> list[Path]:
    _locked(root)
    directory = root / '.transactions'
    if directory.is_symlink():
        raise OSError(f'{ERROR}: symlink journal directory')
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise OSError(f'{ERROR}: invalid journal directory')
    paths = sorted(directory.iterdir())
    # Multiple operations cannot legally overlap; don't guess recovery order.
    if len(paths) > 1:
        raise OSError(f'{ERROR}: interleaved or unknown operations')
    for path in paths:
        if path.suffix != '.json':
            raise OSError(f'{ERROR}: unknown journal member')
    return paths


def require_no_pending_publications(root: Path) -> None:
    """Read-only admission; never recover or probe filesystem capabilities."""
    if _pending_paths(root):
        raise OSError('TRANSACTION_RECOVERY_REQUIRED: pending publication')


@contextmanager
def publication_admission(root: Path):
    """Hold publication lock from pending refusal through complete fact use."""
    from .telemetry_lock import telemetry_lock

    contexts = ExitStack()
    try:
        try:
            contexts.enter_context(telemetry_lock(root))
            require_no_pending_publications(root)
        except OSError as exc:
            message = str(exc)
            if not message.startswith('TRANSACTION_RECOVERY_'):
                message = f'{ERROR}: cannot inspect recovery state'
            raise PublicationAdmissionError(message) from exc
        yield
    except BaseException:
        # Preserve admission, body and cancellation failures over secondary
        # native cleanup I/O; cleanup is still attempted exactly once.
        try:
            contexts.close()
        except OSError:
            try:
                print(
                    'PUBLICATION_LOCK_TEARDOWN_FAILED: cleanup during existing failure',
                    file=sys.stderr,
                )
            except OSError:
                pass  # A broken warning stream must not replace primary error.
        raise
    else:
        # No primary failure: owner teardown reaches command-specific policy.
        contexts.close()


@contextmanager
def publication_recovery(root: Path):
    """Explicit recovery entry: keep owner through recovery and complete use.

    Unlike read-only admission this may compensate pending publications. Preserve
    primary recovery/body/cancellation failure with the same cleanup policy.
    """
    from .telemetry_lock import telemetry_lock

    contexts = ExitStack()
    try:
        contexts.enter_context(telemetry_lock(root))
        recover_pending_publications(root)
        yield
    except BaseException:
        try:
            contexts.close()
        except OSError:
            try:
                print(
                    'PUBLICATION_LOCK_TEARDOWN_FAILED: cleanup during existing failure',
                    file=sys.stderr,
                )
            except OSError:
                pass
        raise
    else:
        contexts.close()


def recover_pending_publications(root: Path):
    for path in _pending_paths(root):
        try:
            document = json.loads(_bytes(root, path.relative_to(root).as_posix()))
            version = document.get('version') if isinstance(document, dict) else None
        except (ValueError, TypeError) as exc:
            raise OSError(f'{ERROR}: invalid journal') from exc
        if type(version) is not int:
            raise OSError(f'{ERROR}: unknown journal version')
        if version == 1:
            recover_operation(root, path)
        elif version == 2:
            from .publication_journal import recover

            recover(root, path)
        else:
            raise OSError(f'{ERROR}: unknown journal version')
