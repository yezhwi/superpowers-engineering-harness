"""Stage and publish Harness artifacts without partial canonical state."""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .context.telemetry import instrument


@dataclass(frozen=True)
class StagedArtifact:
    relative_path: str
    content: bytes
    replace: bool = False


@dataclass
class PublicationOutcome:
    """Invocation-local fact, not authority: commit may precede a raised error."""

    committed: bool = False


def _active_publication_member(document: dict) -> str | None:
    intent = document['intent']
    if intent is None:
        return None
    return Path(document['members'][intent['index']]['path']).name


def _report_publication_failure(document: dict, canonical_member: str | None) -> None:
    # Diagnostic formatting and sinks are subordinate to the publication failure.
    with suppress(BaseException):
        context = {
            'operation_id': document['id'],
            'observed_state': document['state'],
            'retained_location': f".publication-retained/{document['id']}",
        }
        if canonical_member is not None:
            context['canonical_member'] = canonical_member
        prefix = ('PUBLICATION_COMMITTED_CONTEXT ' if document['state'] == 'COMMITTED'
                  else 'PUBLICATION_FAILURE_CONTEXT ')
        print(
            prefix + json.dumps(context, sort_keys=True, separators=(',', ':')),
            file=sys.stderr,
        )


def atomic_write(path: Path, content: bytes) -> None:
    """Atomically replace one standalone Harness artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def stage(
    harness_dir: Path,
    artifacts: list[StagedArtifact],
    *,
    operation_id: str | None = None,
) -> Path:
    """Prepare exclusive files through pinned no-follow directories, never truncate."""
    from . import publication_fs as fs
    from .publication_journal import _name, _open_child, _open_parent

    root = harness_dir.absolute()
    identifier = uuid4().hex if operation_id is None else operation_id
    if (not isinstance(identifier, str) or not identifier or identifier in {'.', '..'}
            or any(char in identifier for char in ('/', '\\', '\x00')) or '..' in root.parts):
        raise ValueError('STAGED_ARTIFACT_PATH_INVALID')
    try:
        paths = [_name(artifact.relative_path) for artifact in artifacts]
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError('STAGED_ARTIFACT_PATH_INVALID') from exc
    if (len(set(paths)) != len(paths) or any(parent in set(paths) for path in paths for parent in path.parents)
            or any(not isinstance(artifact.content, bytes) for artifact in artifacts)):
        raise ValueError('STAGED_ARTIFACT_PATH_INVALID')
    fds = []
    try:
        anchor = fs.open_directory(Path(root.anchor))
        fds.append(anchor)
        root_fd = _open_parent(anchor, Path(*root.parts[1:]), create=True)
        fds.append(root_fd)

        def check_root():
            named_fd = fs.open_directory(root)
            try:
                named, pinned = os.fstat(named_fd), os.fstat(root_fd)
                if (named.st_dev, named.st_ino) != (pinned.st_dev, pinned.st_ino):
                    raise OSError('STAGED_ARTIFACTS_CHANGED')
            finally:
                os.close(named_fd)

        check_root()
        staging = _open_child(root_fd, '.staging', create=True)
        fds.append(staging)
        _require_named_directory(root_fd, '.staging', staging)
        os.mkdir(identifier, mode=0o700, dir_fd=staging)
        fs.sync_directory(staging)
        operation = _open_child(staging, identifier)
        fds.append(operation)

        def check_storage():
            check_root()
            _require_named_directory(root_fd, '.staging', staging)
            _require_named_directory(staging, identifier, operation)

        for artifact, relative in zip(artifacts, paths, strict=True):
            check_storage()
            parent = _open_parent(operation, relative.parent, create=True)
            try:
                check_storage()
                named = _open_parent(operation, relative.parent)
                try:
                    current, pinned = os.fstat(named), os.fstat(parent)
                    if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
                        raise OSError('STAGED_ARTIFACTS_CHANGED')
                finally:
                    os.close(named)
                opened = os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
                with os.fdopen(opened, 'wb') as stream:
                    stream.write(artifact.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                fs.sync_directory(parent)
            finally:
                os.close(parent)
        check_storage()
        fs.sync_directory(operation)
        return root / '.staging' / identifier
    finally:
        for fd in reversed(fds):
            os.close(fd)


@dataclass(frozen=True)
class _StageSnapshot:
    identity: tuple[int, int]
    payloads: dict[str, bytes]
    directories: frozenset[str]


def _relative_name(name: str) -> str:
    from .publication_journal import _name

    return _name(name).as_posix()


def _stage_snapshot(path: Path) -> _StageSnapshot:
    from . import publication_fs as fs

    payloads = {}
    directories = set()

    def scan(fd, prefix):
        with os.scandir(fd) as entries:
            names = sorted(entry.name for entry in entries)
        for name in names:
            relative = f'{prefix}/{name}' if prefix else name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
                opened = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                try:
                    if (os.fstat(opened).st_dev, os.fstat(opened).st_ino) != (info.st_dev, info.st_ino):
                        raise OSError('STAGED_ARTIFACTS_CHANGED')
                    scan(opened, relative)
                finally:
                    os.close(opened)
            elif stat.S_ISREG(info.st_mode):
                opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
                with os.fdopen(opened, 'rb') as stream:
                    actual = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(actual.st_mode)
                            or (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino)):
                        raise OSError('STAGED_ARTIFACTS_CHANGED')
                    payloads[relative] = stream.read()
                    named = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if (named.st_dev, named.st_ino) != (actual.st_dev, actual.st_ino):
                        raise OSError('STAGED_ARTIFACTS_CHANGED')
            else:
                raise OSError('STAGED_ARTIFACTS_CHANGED')

    fd = fs.open_directory(path)
    try:
        info = os.fstat(fd)
        scan(fd, '')
        return _StageSnapshot((info.st_dev, info.st_ino), payloads, frozenset(directories))
    finally:
        os.close(fd)


def _require_stage(path: Path, expected: _StageSnapshot) -> None:
    if _stage_snapshot(path) != expected:
        raise OSError('STAGED_ARTIFACTS_CHANGED')


def _require_named_directory(parent_fd: int, name: str, pinned_fd: int) -> None:
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    pinned = os.fstat(pinned_fd)
    if (named.st_dev, named.st_ino) != (pinned.st_dev, pinned.st_ino):
        raise OSError('STAGED_ARTIFACTS_CHANGED')


def _retain_stage(root: Path, path: Path, *, expected: _StageSnapshot | None = None,
                  root_fd: int | None = None) -> None:
    """Archive whole disposable directory, never check-then-unlink its files.

    Storage housekeeping after commit is not canonical compensation. Its failure
    leaves canonical transaction committed and all moved input objects retained.
    """
    from . import publication_fs as fs
    from .publication_journal import _open_child, _write_new

    if path.parent != root / '.staging':
        raise ValueError('STAGED_ARTIFACT_PATH_INVALID')
    fds = []
    try:
        opened = fs.open_directory(root)
        fds.append(opened)
        if root_fd is not None:
            pinned, named = os.fstat(root_fd), os.fstat(opened)
            if (pinned.st_dev, pinned.st_ino) != (named.st_dev, named.st_ino):
                raise OSError('STAGED_ARTIFACTS_CHANGED')
        parent = _open_child(opened, '.staging')
        fds.append(parent)
        _require_named_directory(opened, '.staging', parent)
        source = _open_child(parent, path.name)
        fds.append(source)
        info = os.fstat(source)
        identity = (info.st_dev, info.st_ino)
        if expected is not None and identity != expected.identity:
            raise OSError('STAGED_ARTIFACTS_CHANGED')
        retained = _open_child(opened, '.publication-retained', create=True)
        fds.append(retained)
        _require_named_directory(opened, '.publication-retained', retained)
        name = 'stage-' + uuid4().hex
        os.mkdir(name, mode=0o700, dir_fd=retained)
        fs.sync_directory(retained)
        archive = _open_child(retained, name)
        fds.append(archive)

        def check_storage():
            named_root = fs.open_directory(root)
            try:
                current, pinned = os.fstat(named_root), os.fstat(opened)
                if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
                    raise OSError('STAGED_ARTIFACTS_CHANGED')
            finally:
                os.close(named_root)
            _require_named_directory(opened, '.staging', parent)
            _require_named_directory(opened, '.publication-retained', retained)
            _require_named_directory(retained, name, archive)

        check_storage()
        _write_new(archive, 'manifest.json', {'version': 1, 'kind': 'disposable-stage',
                                             'source_name': path.name, 'source_identity': list(identity)})
        check_storage()
        _require_named_directory(parent, path.name, source)
        fs.move_noreplace(parent, path.name, archive, 'input')
        fs.sync_directory(parent)
        fs.sync_directory(archive)
        check_storage()
        actual = os.stat('input', dir_fd=archive, follow_symlinks=False)
        _write_new(archive, 'retained.json', {'version': 1, 'observed_identity': [actual.st_dev, actual.st_ino]})
        if (actual.st_dev, actual.st_ino) != identity:
            raise OSError('STAGED_ARTIFACTS_CHANGED')
        if expected is not None:
            _require_stage(root / '.publication-retained' / name / 'input', expected)
        # Never sweep a stage directory recreated by another writer after move.
        if path.exists() or path.is_symlink():
            raise OSError('STAGED_ARTIFACTS_CHANGED')
    finally:
        for fd in reversed(fds):
            os.close(fd)


@instrument('publish')
def publish(
    harness_dir: Path,
    stage_dir: Path,
    *,
    replace_paths: frozenset[str] = frozenset(),
    delete_paths: frozenset[str] = frozenset(),
    after_publish: Callable[[], None] | None = None,
    durable: bool = False,
    expected_sources: dict[str, bytes | None] | None = None,
    expected_artifacts: tuple[StagedArtifact, ...] | None = None,
    outcome: PublicationOutcome | None = None,
) -> None:
    """Exact recoverable publication; durable=False never selects unsafe rename.

    Legacy callers capture staged membership on entry. Protected callers must
    supply both earlier-captured expected_artifacts and expected_sources.
    """
    from . import publication_journal as journal
    from . import source_access
    from .telemetry_lock import telemetry_lock
    from .transaction_recovery import require_no_pending_publications

    if outcome is not None:
        outcome.committed = False
    root, staged = harness_dir.absolute(), stage_dir.absolute()
    if staged.parent != root / '.staging':
        raise ValueError('STAGED_ARTIFACT_PATH_INVALID')
    with telemetry_lock(root):
        require_no_pending_publications(root)
        snapshot = _stage_snapshot(staged)
        payloads = {_relative_name(name): content for name, content in snapshot.payloads.items()}
        if expected_artifacts is not None:
            declared = {_relative_name(item.relative_path): item.content for item in expected_artifacts}
            if len(declared) != len(expected_artifacts) or payloads != declared:
                raise OSError('STAGED_ARTIFACTS_CHANGED')
        deletions = {_relative_name(name) for name in delete_paths}
        if deletions & payloads.keys():
            raise ValueError('STAGED_DELETE_CONFLICT')
        existing = {}
        for name in sorted(payloads.keys() | deletions):
            target = root / name
            if target.is_symlink():
                raise OSError('canonical artifact must be a regular file')
            existing[name] = (source_access.read_regular_bytes_beneath(target, root)
                              if target.exists() else None)
            if name in payloads and existing[name] is not None and name not in replace_paths:
                raise FileExistsError('canonical artifact exists')
        if expected_sources is not None and existing != expected_sources:
            raise OSError('TRANSACTION_RECOVERY_BLOCKED: expected source changed')
        members = tuple(journal.Member(name, existing[name], payloads.get(name)) for name in sorted(existing))
        if not members:
            if after_publish is not None:
                after_publish()
            _require_stage(staged, snapshot)
            _retain_stage(root, staged, expected=snapshot)
            return
        operation = None
        failure_member = None
        try:
            with journal.prepare(root, members) as operation:
                try:
                    _require_stage(staged, snapshot)
                    operation.apply()
                    if after_publish is not None:
                        after_publish()
                    _require_stage(staged, snapshot)
                    try:
                        operation.commit()
                    finally:
                        if outcome is not None:
                            outcome.committed = operation.document['state'] == 'COMMITTED'
                except BaseException:
                    with suppress(BaseException):
                        failure_member = _active_publication_member(operation.document)
                    if operation.document['state'] not in {'COMMITTED', 'ABORTED'}:
                        try:
                            operation.abort()
                        except BaseException:  # noqa: BLE001 - Compensation must not replace active primary.
                            with suppress(BaseException):
                                failure_member = (
                                    _active_publication_member(operation.document) or failure_member
                                )
                            # Even a diagnostic adapter's cancellation cannot replace primary.
                            with suppress(BaseException):
                                print('PUBLICATION_ABORT_FAILED: recovery required; primary failure preserved', file=sys.stderr)
                    raise
                _retain_stage(root, staged, expected=snapshot, root_fd=operation.fds['root'])
        except BaseException:
            if operation is not None:
                _report_publication_failure(operation.document, failure_member)
            raise


def recover_pending_publications(harness_dir: Path) -> None:
    from .transaction_recovery import recover_pending_publications as recover

    recover(harness_dir)


def cleanup_stale_staging(harness_dir: Path) -> None:
    """Retain stale inputs without relying on them for canonical recovery."""
    from . import publication_fs as fs
    from .telemetry_lock import telemetry_lock

    root = harness_dir.absolute()
    with telemetry_lock(root):
        directory = root / '.staging'
        if not directory.exists() and not directory.is_symlink():
            return
        fd = fs.open_directory(directory)
        try:
            names = sorted(os.listdir(fd))
        finally:
            os.close(fd)
        for name in names:
            _retain_stage(root, directory / name)
