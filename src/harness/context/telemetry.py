"""Opt-in, invocation-local timing; never a source of Context authority."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from uuid import uuid4

PHASES = (
    'lock_wait', 'capture', 'source_load', 'evidence_validate', 'gate_assess',
    'selection', 'expansion_plan', 'publish', 'integrity_validate', 'overhead',
)
COUNTERS = (
    'source_loads', 'gate_assessments', 'full_context_builds',
    'expansion_candidates', 'expansion_events_written', 'evidence_records',
)
_ACTIVE: ContextVar[ContextTelemetry | None] = ContextVar('context_telemetry', default=None)


def active() -> ContextTelemetry | None:
    return _ACTIVE.get()


class ContextTelemetry:
    def __init__(self, *, clock=time.monotonic, progress: bool = False):
        self.clock = clock
        self.progress = progress
        self.started = self.last = clock()
        self.current = 'overhead'
        self.phases = dict.fromkeys(PHASES, 0.0)
        self.counters = dict.fromkeys(COUNTERS, 0)
        self.task_id = None
        self.context_published = False
        self.cancelled = False
        self.finished = None

    def _tick(self):
        now = self.clock()
        self.phases[self.current] += (now - self.last) * 1000
        self.last = now
        return now

    @contextmanager
    def activate(self):
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)

    @contextmanager
    def phase(self, name: str):
        if name not in self.phases:
            raise ValueError('unknown Context phase')
        self._tick()
        parent, self.current = self.current, name
        try:
            yield
        finally:
            now = self._tick()
            self.current = parent
            if self.progress:
                print(
                    f'phase={name} count={sum(self.counters.values())} '
                    f'elapsed_ms={(now - self.started) * 1000:.3f}',
                    file=sys.stderr,
                )

    def increment(self, name: str, count: int = 1):
        self.counters[name] += count

    def finish(self, outcome: str, context_published: bool) -> dict:
        # One terminal record, including stdout failures and cancellation.
        if self.finished is None:
            now = self._tick()
            self.finished = {
                'version': 1, 'operation': 'context.generate', 'task_id': self.task_id,
                'outcome': 'CANCELLED' if self.cancelled else outcome,
                'context_published': context_published,
                'timing_scope': 'context_operation_excludes_profile_output',
                'phase_semantics': 'exclusive',
                'total_ms': (now - self.started) * 1000,
                'phases_ms': dict(self.phases), 'counters': dict(self.counters),
            }
        return self.finished

    @contextmanager
    def cancellation_handler(self):
        # Signal handler does no I/O and never interrupts a publication transaction.
        previous = signal.getsignal(signal.SIGTERM)
        def cancelled(signum, frame):
            self.cancelled = True
        signal.signal(signal.SIGTERM, cancelled)
        try:
            yield
        finally:
            signal.signal(signal.SIGTERM, previous)


@contextmanager
def phase(name: str):
    timer = active()
    if timer is None:
        yield
    else:
        with timer.phase(name):
            yield


def increment(name: str, count: int = 1):
    timer = active()
    if timer is not None:
        timer.increment(name, count)


def instrument(name: str, counter: str | None = None):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            timer = active()
            if timer is None:
                return function(*args, **kwargs)
            if counter is not None:
                timer.increment(counter)
            with timer.phase(name):
                return function(*args, **kwargs)
        return measured
    return decorate


class ProfileDestination:
    """Pinned identity, no-follow ancestor walk, atomic no-overwrite publication."""

    def __init__(self, path: Path, repo_root: Path):
        self.path = Path(os.path.abspath(path))
        root = repo_root.resolve()
        if self.path.is_relative_to(root) or self.path.resolve().is_relative_to(root):
            raise OSError('profile destination must be outside repository')
        fd = self._open_parent()
        try:
            self.identity = self._identity(fd)
            self._absent(fd)
            if not os.access(self.path.parent, os.W_OK):
                raise PermissionError('profile directory is not writable')
        finally:
            os.close(fd)

    @staticmethod
    def _identity(fd):
        value = os.fstat(fd)
        return value.st_dev, value.st_ino

    def _open_parent(self):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.path.anchor, flags)
        try:
            for name in self.path.parent.parts[1:]:
                child = os.open(name, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _absent(self, fd):
        try:
            os.stat(self.path.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError('profile destination already exists')

    def publish(self, report: dict):
        fd = self._open_parent()
        temporary = f'.harness-profile-{uuid4().hex}'
        created = False
        try:
            if self._identity(fd) != self.identity:
                raise OSError('profile parent changed')
            self._absent(fd)
            data = (json.dumps(report, allow_nan=False, indent=2) + '\n').encode()
            out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            created = True
            with os.fdopen(out, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            check = self._open_parent()
            try:
                if self._identity(check) != self.identity:
                    raise OSError('profile parent changed')
            finally:
                os.close(check)
            # link is an atomic no-replace rename equivalent: unlike replace(),
            # a competing file/symlink cannot be overwritten at commit time.
            os.link(temporary, self.path.name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.fsync(fd)
        finally:
            if created:
                os.unlink(temporary, dir_fd=fd)
            os.close(fd)
