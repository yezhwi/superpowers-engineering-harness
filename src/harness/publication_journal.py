"""Inode-preserving v2 transactions with append-only recovery state.

Active descriptor is immutable. Slots and state frames live in retention from
preparation onward; retirement moves descriptor only, never displaced objects.
Unknown identities/content stop recovery, rather than authorize a guessed repair.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from . import publication_fs as fs
from .transaction_recovery import ERROR, _locked

_RESERVED = {'.transactions', '.publication-retained', '.staging'}
_STATES = {'PREPARED', 'APPLYING', 'VALIDATING', 'ABORTING', 'COMMITTED', 'ABORTED', 'BLOCKED'}
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _blocked() -> OSError:
    return OSError(f'{ERROR}: publication identity or state conflict; objects retained')


def _digest(content: bytes | None) -> str | None:
    return None if content is None else hashlib.sha256(content).hexdigest()


def _encoded(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(',', ':')).encode()


def _id(info) -> list[int]:
    return [info.st_dev, info.st_ino]


def _name(path: str) -> Path:
    if not isinstance(path, str) or not path or '\\' in path or '\x00' in path:
        raise _blocked()
    value = Path(path)
    if (value.is_absolute() or '..' in value.parts or value.as_posix() != path
            or not value.parts or value.parts[0] in _RESERVED):
        raise _blocked()
    return value


def _identity(fd: int, name: str) -> list[int] | None:
    try:
        return _id(os.stat(name, dir_fd=fd, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _observe(fd: int, name: str) -> tuple[list[int], str] | None:
    try:
        opened = os.open(name, _READ, dir_fd=fd)
    except FileNotFoundError:
        return None
    with os.fdopen(opened, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise _blocked()
        digest = hashlib.sha256()
        while chunk := stream.read(65536):
            digest.update(chunk)
        if _identity(fd, name) != _id(info):
            raise _blocked()
        return _id(info), digest.hexdigest()


def _read_document(fd: int, name: str) -> dict:
    opened = os.open(name, _READ, dir_fd=fd)
    with os.fdopen(opened, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise _blocked()
        raw = stream.read()
        result = json.loads(raw)
    if not isinstance(result, dict) or raw != _encoded(result):
        raise _blocked()
    return result


def _write_new(fd: int, name: str, document: dict) -> None:
    """Exclusive durable metadata publication, never replace unknown journal bytes."""
    temporary = f'.record-{uuid4().hex}.tmp'
    opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=fd)
    # On interruption/errors keep private temporary bytes, never sweep unknowns.
    with os.fdopen(opened, 'wb') as stream:
        stream.write(_encoded(document))
        stream.flush()
        os.fsync(stream.fileno())
    fs.move_noreplace(fd, temporary, fd, name)
    fs.sync_directory(fd)


def _open_child(fd: int, name: str, *, create: bool = False) -> int:
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=fd)
        except FileExistsError:
            pass
        else:
            fs.sync_directory(fd)
    return os.open(name, _FLAGS, dir_fd=fd)


def _open_parent(root_fd: int, parent: Path, *, create: bool = False) -> int:
    fd = os.dup(root_fd)
    try:
        for part in parent.parts:
            child = _open_child(fd, part, create=create)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class Member:
    path: str
    expected: bytes | None
    payload: bytes | None


def _validate(document: dict) -> None:
    if (set(document) != {'version', 'id', 'root', 'root_path', 'storage', 'parents', 'members', 'state', 'intent'}
            or document['version'] != 2 or document['state'] not in _STATES
            or not isinstance(document['id'], str) or not re.fullmatch('[0-9a-f]{32}', document['id'])
            or not isinstance(document['root_path'], str) or not Path(document['root_path']).is_absolute()
            or not isinstance(document['parents'], dict) or not isinstance(document['members'], list)
            or not document['members']):
        raise _blocked()

    def identity(value, nullable=False):
        return ((value is None and nullable) or (isinstance(value, list) and len(value) == 2
                and all(type(item) is int and item >= 0 for item in value)))

    def digest(value):
        return value is None or (isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value))

    if (not identity(document['root']) or set(document['storage']) != {'active', 'retained', 'slots', 'capability'}
            or not all(identity(value) for value in document['storage'].values())):
        raise _blocked()
    seen = set()
    parents = set()
    for member in document['members']:
        if (not isinstance(member, dict) or set(member) != {'path', 'before', 'after', 'original', 'candidate', 'progress'}
                or member['progress'] not in {'PREPARED', 'APPLIED', 'RESTORED'}
                or not digest(member['before']) or not digest(member['after'])
                or not identity(member['original'], True) or not identity(member['candidate'], True)
                or (member['before'] is None) != (member['original'] is None)
                or (member['after'] is None) != (member['candidate'] is None)):
            raise _blocked()
        path = _name(member['path'])
        if member['path'] in seen:
            raise _blocked()
        seen.add(member['path'])
        parents.add(path.parent.as_posix())
    if (set(document['parents']) != parents
            or not all(identity(value) for value in document['parents'].values())):
        raise _blocked()
    progress = [member['progress'] for member in document['members']]
    state = document['state']
    if ((state == 'PREPARED' and any(value != 'PREPARED' for value in progress))
            or (state in {'VALIDATING', 'COMMITTED'} and any(value != 'APPLIED' for value in progress))
            or (state == 'APPLYING' and 'RESTORED' in progress)
            or (state == 'ABORTED' and 'APPLIED' in progress)
            or (state in {'PREPARED', 'VALIDATING', 'COMMITTED', 'ABORTED'} and document['intent'] is not None)):
        raise _blocked()
    intent = document['intent']
    if intent is not None and (not isinstance(intent, dict) or set(intent) != {'index', 'direction'}
            or type(intent['index']) is not int or not 0 <= intent['index'] < len(document['members'])
            or intent['direction'] not in {'forward', 'abort'}):
        raise _blocked()


def _immutable(document: dict) -> dict:
    result = copy.deepcopy(document)
    result.pop('state')
    result.pop('intent')
    for member in result['members']:
        member.pop('progress')
    return result


def _transition(before: dict, after: dict) -> None:
    """Validate legal state AND per-member intent/progress edges, not hashes alone."""
    if _immutable(before) != _immutable(after):
        raise _blocked()
    old_state, new_state = before['state'], after['state']
    old_intent, new_intent = before['intent'], after['intent']
    old_members, new_members = before['members'], after['members']
    if old_state != new_state:
        edges = {('PREPARED', 'APPLYING'), ('PREPARED', 'ABORTING'),
                 ('APPLYING', 'VALIDATING'), ('APPLYING', 'ABORTING'),
                 ('VALIDATING', 'ABORTING'), ('VALIDATING', 'COMMITTED'),
                 ('ABORTING', 'ABORTED')}
        if ((old_state, new_state) not in edges or old_intent is not None
                or new_intent is not None or old_members != new_members):
            raise _blocked()
        return
    if old_state not in {'APPLYING', 'ABORTING'}:
        raise _blocked()
    direction = 'forward' if old_state == 'APPLYING' else 'abort'
    start, end = ('PREPARED', 'APPLIED') if direction == 'forward' else ('APPLIED', 'RESTORED')
    if new_intent is not None:
        if (old_intent is not None or new_intent['direction'] != direction
                or old_members != new_members
                or old_members[new_intent['index']]['progress'] != start):
            raise _blocked()
    elif old_intent is not None:
        if old_intent['direction'] != direction:
            raise _blocked()
        advanced = copy.deepcopy(old_members)
        index = old_intent['index']
        if advanced[index]['progress'] != start:
            raise _blocked()
        advanced[index]['progress'] = end
        if new_members not in (old_members, advanced):
            raise _blocked()
    elif old_state != 'ABORTING' or old_members != new_members:
        raise _blocked()


class Operation:
    """All methods require continuous telemetry_lock; context exit closes FDs only."""

    def __init__(self, root: Path, document: dict, fds: dict[str, int]):
        self.root = root
        self.document = document
        self.fds = fds
        self.sequence = 0
        self.previous = _digest(_encoded(document))
        self.initial_hash = self.previous
        self.initial_written = True
        self.known_frames = {}
        self.finished = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        cleanup_error = None
        for fd in self.fds.values():
            try:
                os.close(fd)
            except OSError as error:
                if cleanup_error is None:
                    cleanup_error = error
        self.fds.clear()
        if cleanup_error is not None and exc_type is None:
            raise cleanup_error

    def _check(self):
        _locked(self.root)
        if str(self.root) != self.document['root_path']:
            raise _blocked()
        for key, expected in [('root', self.document['root']), *self.document['storage'].items()]:
            if _id(os.fstat(self.fds[key])) != expected:
                raise _blocked()
        named = fs.open_directory(self.root)
        try:
            if _id(os.fstat(named)) != self.document['root']:
                raise _blocked()
        finally:
            os.close(named)
        for key, name in [('active', '.transactions'), ('retained', '.publication-retained')]:
            if _identity(self.fds['root'], name) != self.document['storage'][key]:
                raise _blocked()
        if (_identity(self.fds['retained'], self.document['id']) != self.document['storage']['slots']
                or _identity(self.fds['slots'], 'capability') != self.document['storage']['capability']):
            raise _blocked()
        allowed = {*(f'new-{i}' for i, member in enumerate(self.document['members']) if member['after'] is not None),
                   *(f'old-{i}' for i, member in enumerate(self.document['members']) if member['after'] is None and member['before'] is not None),
                   *(f'state-{i:08d}.json' for i in self.known_frames), 'capability'}
        if self.document['state'] in {'COMMITTED', 'ABORTED'}:
            allowed.add('manifest.json')
        if self.finished:
            allowed.add('active.json')
        if set(os.listdir(self.fds['slots'])) - allowed:
            raise _blocked()
        if self.initial_written:
            fd, name = ((self.fds['slots'], 'active.json') if self.finished
                        else (self.fds['active'], self.document['id'] + '.json'))
            if _digest(_encoded(_read_document(fd, name))) != self.initial_hash:
                raise _blocked()
        for number, digest in self.known_frames.items():
            if _digest(_encoded(_read_document(self.fds['slots'], f'state-{number:08d}.json'))) != digest:
                raise _blocked()
        for parent, expected in self.document['parents'].items():
            if _id(os.fstat(self.fds['parent:' + parent])) != expected:
                raise _blocked()
            opened = _open_parent(self.fds['root'], Path(parent))
            try:
                if _id(os.fstat(opened)) != expected:
                    raise _blocked()
            finally:
                os.close(opened)

    def _save(self, **updates):
        self._check()
        document = copy.deepcopy(self.document)
        document.update(updates)
        _validate(document)
        _transition(self.document, document)
        frame = {'version': 2, 'sequence': self.sequence + 1,
                 'previous': self.previous, 'operation': document}
        _write_new(self.fds['slots'], f'state-{self.sequence + 1:08d}.json', frame)
        self.sequence += 1
        self.previous = _digest(_encoded(frame))
        self.known_frames[self.sequence] = self.previous
        self.document = document

    def _locations(self, index):
        member = self.document['members'][index]
        path = Path(member['path'])
        canonical = (self.fds['parent:' + path.parent.as_posix()], path.name)
        slot = (self.fds['slots'], f'new-{index}' if member['after'] is not None else f'old-{index}')
        return member, canonical, slot

    def _layout(self, index, direction):
        member, canonical, slot = self._locations(index)
        original, candidate = member['original'], member['candidate']
        if original is not None and candidate is not None:
            before, after = (original, candidate), (candidate, original)
        elif candidate is not None:
            before, after = (None, candidate), (candidate, None)
        elif original is not None:
            before, after = (original, None), (None, original)
        else:
            before = after = (None, None)
        if direction == 'abort':
            before, after = after, before
        return member, canonical, slot, before, after

    def _values(self, index, direction, *, after):
        member, canonical, slot, pre, post = self._layout(index, direction)
        ids = post if after else pre
        values = (_observe(*canonical), _observe(*slot))
        for value, expected_id in zip(values, ids, strict=True):
            if value is None:
                if expected_id is not None:
                    raise _blocked()
            elif value[0] != expected_id or value[1] != (
                    member['before'] if expected_id == member['original'] else member['after']):
                raise _blocked()

    def _settle_intent(self):
        intent = self.document['intent']
        if intent is None:
            return
        index, direction = intent['index'], intent['direction']
        _member, canonical, slot, before, after = self._layout(index, direction)
        current = (_identity(*canonical), _identity(*slot))
        if current == after:
            self._values(index, direction, after=True)
            members = copy.deepcopy(self.document['members'])
            members[index]['progress'] = 'APPLIED' if direction == 'forward' else 'RESTORED'
            self._save(members=members, intent=None)
        elif current == before:
            self._values(index, direction, after=False)
            self._save(intent=None)
        else:
            raise _blocked()

    def _step(self, index, direction):
        self._check()
        self._values(index, direction, after=False)
        self._save(intent={'index': index, 'direction': direction})
        member, canonical, slot = self._locations(index)
        if member['original'] is not None and member['candidate'] is not None:
            fs.exchange(*canonical, *slot)
        elif member['candidate'] is not None:
            fs.move_noreplace(*(slot + canonical if direction == 'forward' else canonical + slot))
        elif member['original'] is not None:
            fs.move_noreplace(*(canonical + slot if direction == 'forward' else slot + canonical))
        fs.sync_directory(canonical[0])
        fs.sync_directory(slot[0])
        self._settle_intent()
        expected = 'APPLIED' if direction == 'forward' else 'RESTORED'
        if self.document['members'][index]['progress'] != expected:
            raise _blocked()

    def apply(self) -> None:
        self._check()
        if self.document['state'] != 'PREPARED':
            raise _blocked()
        self._save(state='APPLYING')
        for index in range(len(self.document['members'])):
            self._step(index, 'forward')
        self._save(state='VALIDATING')

    def _sync_values(self, index, *, after):
        """Synchronize both live and retained objects before terminal authority."""
        self._values(index, 'forward', after=after)
        _member, canonical, slot, before_ids, after_ids = self._layout(index, 'forward')
        for (fd, name), expected in zip((canonical, slot), after_ids if after else before_ids, strict=True):
            if expected is None:
                continue
            opened = os.open(name, _READ, dir_fd=fd)
            try:
                info = os.fstat(opened)
                if not stat.S_ISREG(info.st_mode) or _id(info) != expected:
                    raise _blocked()
                os.fsync(opened)
            except BaseException:
                try:
                    os.close(opened)
                except OSError:
                    pass  # Preserve primary synchronization/identity failure.
                raise
            else:
                os.close(opened)
        fs.sync_directory(canonical[0])
        fs.sync_directory(slot[0])

    def commit(self) -> None:
        self._check()
        if self.document['state'] != 'VALIDATING' or self.document['intent'] is not None:
            raise _blocked()
        for index in range(len(self.document['members'])):
            self._sync_values(index, after=True)
        self._save(state='COMMITTED')
        self._finish()

    def abort(self) -> None:
        self._check()
        if self.document['state'] in {'COMMITTED', 'BLOCKED'}:
            raise _blocked()
        if self.document['state'] == 'ABORTED':
            self._finish()
            return
        self._settle_intent()
        self._save(state='ABORTING')
        for index in reversed(range(len(self.document['members']))):
            if self.document['members'][index]['progress'] == 'APPLIED':
                self._step(index, 'abort')
            elif self.document['members'][index]['progress'] == 'PREPARED':
                self._values(index, 'forward', after=False)
        for index in range(len(self.document['members'])):
            self._sync_values(index, after=False)
        self._save(state='ABORTED')
        self._finish()

    def _finish(self):
        self._check()
        if self.document['state'] not in {'COMMITTED', 'ABORTED'}:
            raise _blocked()
        if self.finished:
            return
        for index in range(len(self.document['members'])):
            self._values(index, 'forward', after=self.document['state'] == 'COMMITTED')
        if _identity(self.fds['slots'], 'manifest.json') is None:
            _write_new(self.fds['slots'], 'manifest.json', self.document)
        elif _read_document(self.fds['slots'], 'manifest.json') != self.document:
            raise _blocked()
        fs.sync_directory(self.fds['slots'])
        fs.move_noreplace(self.fds['active'], self.document['id'] + '.json',
                          self.fds['slots'], 'active.json')
        fs.sync_directory(self.fds['slots'])
        fs.sync_directory(self.fds['active'])
        fs.sync_directory(self.fds['root'])
        self.finished = True


def prepare(root: Path, members: tuple[Member, ...]) -> Operation:
    root = root.absolute()
    _locked(root)
    if not members or any(not isinstance(member, Member) for member in members):
        raise _blocked()
    paths = [_name(member.path) for member in members]
    if len(set(paths)) != len(paths) or any(
            value is not None and not isinstance(value, bytes)
            for member in members for value in (member.expected, member.payload)):
        raise _blocked()
    fds = {}
    try:
        fds['root'] = fs.open_directory(root)
        fds['active'] = _open_child(fds['root'], '.transactions', create=True)
        if os.listdir(fds['active']):
            raise _blocked()
        fds['retained'] = _open_child(fds['root'], '.publication-retained', create=True)
        operation_id = uuid4().hex
        os.mkdir(operation_id, mode=0o700, dir_fd=fds['retained'])
        fs.sync_directory(fds['retained'])
        fds['slots'] = _open_child(fds['retained'], operation_id)
        fds['capability'] = _open_child(fds['slots'], 'capability', create=True)
        fs.check_capabilities(fds['capability'])
        document = {'version': 2, 'id': operation_id, 'root': _id(os.fstat(fds['root'])), 'root_path': str(root),
                    'storage': {name: _id(os.fstat(fds[name])) for name in ('active', 'retained', 'slots', 'capability')},
                    'parents': {}, 'members': [], 'state': 'PREPARED', 'intent': None}
        for index, (member, path) in enumerate(zip(members, paths, strict=True)):
            parent_name = path.parent.as_posix()
            key = 'parent:' + parent_name
            if key not in fds:
                fds[key] = _open_parent(fds['root'], path.parent, create=True)
                if os.fstat(fds[key]).st_dev != os.fstat(fds['slots']).st_dev:
                    raise fs.PublicationUnsupported('PUBLICATION_UNSUPPORTED: cross-device target')
                fs.sync_directory(fds[key])
                document['parents'][parent_name] = _id(os.fstat(fds[key]))
            original = _observe(fds[key], path.name)
            if (None if original is None else original[1]) != _digest(member.expected):
                raise _blocked()
            candidate = None
            if member.payload is not None:
                opened = os.open(f'new-{index}', os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fds['slots'])
                with os.fdopen(opened, 'wb') as stream:
                    candidate = _id(os.fstat(stream.fileno()))
                    stream.write(member.payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            document['members'].append({'path': member.path, 'before': _digest(member.expected),
                                        'after': _digest(member.payload), 'original': None if original is None else original[0],
                                        'candidate': candidate, 'progress': 'PREPARED'})
        _validate(document)
        fs.sync_directory(fds['slots'])
        operation = Operation(root, document, fds)
        operation.initial_written = False
        operation._check()
        _write_new(fds['active'], operation_id + '.json', document)
        operation.initial_written = True
        return operation
    except BaseException:
        for fd in fds.values():
            os.close(fd)
        raise


def recover(root: Path, operation_path: Path) -> None:
    root = root.absolute()
    _locked(root)
    fds = {}
    try:
        fds['root'] = fs.open_directory(root)
        fds['active'] = _open_child(fds['root'], '.transactions')
        document = _read_document(fds['active'], operation_path.name)
        _validate(document)
        if (operation_path.parent.absolute() != root / '.transactions'
                or operation_path.name != document['id'] + '.json'):
            raise _blocked()
        initial = copy.deepcopy(document)
        fds['retained'] = _open_child(fds['root'], '.publication-retained')
        fds['slots'] = _open_child(fds['retained'], document['id'])
        fds['capability'] = _open_child(fds['slots'], 'capability')
        for parent in document['parents']:
            fds['parent:' + parent] = _open_parent(fds['root'], Path(parent))
        operation = Operation(root, document, fds)
        frames = sorted(name for name in os.listdir(fds['slots']) if re.fullmatch(r'state-\d{8}\.json', name))
        allowed = {*(f'new-{i}' for i, member in enumerate(document['members']) if member['after'] is not None),
                   *(f'old-{i}' for i, member in enumerate(document['members']) if member['after'] is None and member['before'] is not None),
                   *frames, 'manifest.json', 'capability'}
        if set(os.listdir(fds['slots'])) - allowed:
            raise _blocked()
        for number, name in enumerate(frames, 1):
            frame = _read_document(fds['slots'], name)
            if (name != f'state-{number:08d}.json' or set(frame) != {'version', 'sequence', 'previous', 'operation'}
                    or frame['version'] != 2 or frame['sequence'] != number or frame['previous'] != operation.previous):
                raise _blocked()
            _validate(frame['operation'])
            if _immutable(frame['operation']) != _immutable(initial):
                raise _blocked()
            _transition(operation.document, frame['operation'])
            operation.sequence = number
            operation.previous = _digest(_encoded(frame))
            operation.known_frames[number] = operation.previous
            operation.document = frame['operation']
        operation._check()
        if operation.document['state'] in {'COMMITTED', 'ABORTED'}:
            for index in range(len(operation.document['members'])):
                operation._sync_values(index, after=operation.document['state'] == 'COMMITTED')
            operation._finish()
        else:
            operation.abort()
    except (ValueError, TypeError, KeyError) as exc:
        raise _blocked() from exc
    finally:
        for fd in fds.values():
            os.close(fd)
