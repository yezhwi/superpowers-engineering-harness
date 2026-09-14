"""Scoped checks for trusted Python source reads, not an OS sandbox.

The audit hook observes open, not stat or arbitrary native/subprocess I/O.
Metadata queries must use these helpers. Scope is not inherited by new threads.
This module is not yet wired into Context/Gate production reads.
"""

import hashlib
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from threading import Lock

from harness.context.model import ContextBuildError


@dataclass
class _Scope:
    root: Path
    allowed: frozenset[Path]
    member_rules: tuple[tuple[Path, str], ...] = ()
    violated: bool = False
    stale: bool = False
    observations: dict = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)


class SourceObservations:
    """Detached snapshot access, not permission to mutate the active guard."""

    def __init__(self, scope: _Scope):
        self._scope = scope

    def resource_snapshot(self) -> dict[str, str]:
        return dict(sorted(self._scope.resources.items()))

    def snapshot(self) -> dict:
        result = {}
        for (path, kind, pattern), value in sorted(self._scope.observations.items()):
            key = path.relative_to(self._scope.root).as_posix()
            label = f"members:{pattern}" if kind == "members" else kind
            result.setdefault(key, {})[label] = deepcopy(value)
        return result


def _stale() -> None:
    for scope in _SCOPES.get():
        scope.stale = True
    raise ContextBuildError("CONTEXT_STALE", "observed source changed")


def _observe(path: Path, kind: str, value, pattern: str = "") -> None:
    key = (Path(os.path.abspath(path)), kind, pattern)
    for scope in _SCOPES.get():
        if key in scope.observations and scope.observations[key] != value:
            _stale()
        scope.observations[key] = value


def _hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _members(path: Path, pattern: str) -> tuple[str, ...] | None:
    if not path.exists():
        return None
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    return tuple(sorted(member.name for member in path.glob(pattern)))


def _verify(scope: _Scope) -> None:
    from harness.schema_resources import _resource_bytes

    for name, previous in scope.resources.items():
        try:
            current = _hash(_resource_bytes(name))
        except OSError:
            _stale()
        if current != previous:
            _stale()
    for (path, kind, pattern), previous in scope.observations.items():
        _check(path, explicit=True)
        try:
            if kind == "bytes":
                try:
                    current = _hash(path.read_bytes())
                except FileNotFoundError:
                    current = None
            elif kind == "exists":
                current = path.exists()
            elif kind == "is_file":
                current = path.is_file()
            elif kind == "is_dir":
                current = path.is_dir()
            elif kind == "is_symlink":
                current = path.is_symlink()
            else:
                current = _members(path, pattern)
        except OSError:
            _stale()
        if current != previous:
            _stale()


_SCOPES: ContextVar[tuple[_Scope, ...]] = ContextVar(
    "harness_source_scopes", default=()
)
_PACKAGE_OPEN: ContextVar[Path | None] = ContextVar(
    "harness_package_open", default=None
)
_INSTALL_LOCK = Lock()
_INSTALLED = False


def _deny(scope: _Scope) -> None:
    scope.violated = True
    for active in _SCOPES.get():
        active.violated = True
    raise ContextBuildError("CONTEXT_REFERENCE_BROKEN", "undeclared source access")


def _check(path: Path, *, explicit: bool = False) -> None:
    scopes = _SCOPES.get()
    if not scopes:
        return
    lexical = Path(os.path.abspath(path))
    try:
        resolved = lexical.resolve()
    except (OSError, RuntimeError):
        for scope in scopes:
            scope.violated = True
        raise ContextBuildError(
            "CONTEXT_REFERENCE_BROKEN", "unresolvable source"
        ) from None
    for scope in scopes:
        relevant = (
            explicit
            or lexical.is_relative_to(scope.root)
            or resolved.is_relative_to(scope.root)
        )
        if relevant and (
            not resolved.is_relative_to(scope.root)
            or (
                resolved not in scope.allowed
                and not any(
                    resolved.parent == directory and fnmatchcase(resolved.name, pattern)
                    for directory, pattern in scope.member_rules
                )
            )
        ):
            _deny(scope)


def _audit(event: str, args: tuple) -> None:
    if event != "open" or not _SCOPES.get():
        return
    path = args[0]
    if isinstance(path, int):
        # No provenance proof for a pre-opened descriptor in an active scope.
        _deny(_SCOPES.get()[-1])
    candidate = Path(os.path.abspath(os.fsdecode(path)))
    if candidate == _PACKAGE_OPEN.get():
        return
    _check(candidate)


@contextmanager
def _package_open(path: Path):
    """Trusted resource adapter grants one lexical file, never a directory."""
    token = _PACKAGE_OPEN.set(Path(os.path.abspath(path)))
    try:
        yield
    finally:
        _PACKAGE_OPEN.reset(token)


def reject_resource() -> None:
    for scope in _SCOPES.get():
        scope.violated = True
    raise ContextBuildError("CONTEXT_REFERENCE_BROKEN", "unregistered schema resource")


def observe_resource(name: str, content: bytes) -> None:
    version = _hash(content)
    for scope in _SCOPES.get():
        if name in scope.resources and scope.resources[name] != version:
            _stale()
        scope.resources[name] = version


def _install() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if not _INSTALLED:
            sys.addaudithook(_audit)
            _INSTALLED = True


@contextmanager
def source_scope(root: Path, *, allowed, member_rules=()):
    """Restrict open under root; nested scopes cannot override outer denials.

    sticky violation survives a consumer swallowing the immediate exception.
    No global Path/open monkeypatches; unrelated threads keep their own scopes.
    """
    _install()
    root = Path(root).resolve()
    declared = set()
    for path in allowed:
        path = Path(path).resolve()
        if not path.is_relative_to(root):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", "source declaration outside root"
            )
        declared.add(path)
    rules = []
    for directory, pattern in member_rules:
        directory = Path(directory).resolve()
        if (
            not directory.is_relative_to(root)
            or not pattern
            or any(part in pattern for part in ("/", "\\", "**"))
        ):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", "invalid source member rule"
            )
        declared.add(directory)
        rules.append((directory, pattern))
    scope = _Scope(root, frozenset(declared), tuple(rules))
    token = _SCOPES.set((*_SCOPES.get(), scope))
    try:
        yield SourceObservations(scope)
    finally:
        try:
            if scope.violated:
                raise ContextBuildError(
                    "CONTEXT_REFERENCE_BROKEN", "undeclared source access"
                )
            if scope.stale:
                _stale()
            _verify(scope)
        finally:
            _SCOPES.reset(token)


def read_bytes(path: Path) -> bytes:
    _check(path, explicit=True)
    try:
        content = Path(path).read_bytes()
    except FileNotFoundError:
        _observe(path, "bytes", None)
        raise
    _observe(path, "bytes", _hash(content))
    return content


def read_text(path: Path, *, encoding: str = "utf-8") -> str:
    return read_bytes(path).decode(encoding)


def exists(path: Path) -> bool:
    _check(path, explicit=True)
    result = Path(path).exists()
    _observe(path, "exists", result)
    return result


def is_file(path: Path) -> bool:
    _check(path, explicit=True)
    result = Path(path).is_file()
    _observe(path, "is_file", result)
    return result


def is_dir(path: Path) -> bool:
    _check(path, explicit=True)
    result = Path(path).is_dir()
    _observe(path, "is_dir", result)
    return result


def is_symlink(path: Path) -> bool:
    _check(path, explicit=True)
    result = Path(path).is_symlink()
    _observe(path, "is_symlink", result)
    return result


def members(directory: Path, pattern: str) -> tuple[Path, ...]:
    """Observe one directory; returned names do not grant member read authority."""
    _check(directory, explicit=True)
    if (
        not pattern
        or "/" in pattern
        or "\\" in pattern
        or "**" in pattern
        or pattern in {".", ".."}
    ):
        raise ContextBuildError("CONTEXT_REFERENCE_BROKEN", "nonlocal member pattern")
    names = _members(Path(directory), pattern)
    _observe(directory, "members", names, pattern)
    return tuple(Path(directory) / name for name in (names or ()))
