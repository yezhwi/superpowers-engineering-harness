"""Cooperative, outside-repository candidate proof runner."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shlex
import stat
import subprocess
import tempfile
import tomllib
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from functools import lru_cache

import yaml
from jsonschema import ValidationError, validate

from .schema_resources import read_schema


PROFILE_VERSION = "candidate-proof-profile/v1"
INPUT_POLICY = {
    "git": "forbidden",
    "hooks": "forbidden",
    "network": "forbidden",
    "secrets": "forbidden",
    "dynamic_dependencies": "forbidden",
}
DECLARED_ENVIRONMENT = frozenset({"LC_ALL", "PYTHONHASHSEED", "SOURCE_DATE_EPOCH", "TZ"})
PROFILES = frozenset(
    {"python-script-v1", "pytest-junit-v1", "python-module-build-v1"}
)
class CandidateRunnerError(RuntimeError):
    pass


def _refuse(code: str = "CANDIDATE_PROOF_UNQUALIFIED") -> None:
    raise CandidateRunnerError(code)


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _alias(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith("-") or "\0" in value:
        _refuse()
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _refuse()
    return path.as_posix()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=repo,
        capture_output=True,
    )


def _tree_files(repo: Path, tree: str) -> list[tuple[str, str, str]]:
    if not isinstance(tree, str) or len(tree) != 40:
        _refuse()
    result = _git(repo, "ls-tree", "-r", "-z", tree)
    if result.returncode:
        _refuse("CANDIDATE_DRIFT")
    rows: list[tuple[str, str, str]] = []
    aliases: dict[str, str] = {}
    for field in result.stdout.split(b"\0"):
        if not field:
            continue
        try:
            header, raw_path = field.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split(" ")
            path = _relative(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            _refuse()
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            _refuse()
        parts = PurePosixPath(path).parts
        for index in range(1, len(parts) + 1):
            prefix = PurePosixPath(*parts[:index]).as_posix()
            key = _alias(prefix)
            if key in aliases and aliases[key] != prefix:
                _refuse()
            aliases[key] = prefix
        rows.append((mode, oid, path))
    return rows


def _blob(repo: Path, oid: str) -> bytes:
    result = _git(repo, "cat-file", "blob", oid)
    if result.returncode:
        _refuse("CANDIDATE_DRIFT")
    return result.stdout


def _materialize(
    repo: Path, rows: list[tuple[str, str, str]], destination: Path
) -> None:
    links: list[tuple[Path, bytes]] = []
    for mode, oid, path in rows:
        target = destination.joinpath(*PurePosixPath(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            _refuse()
        content = _blob(repo, oid)
        if mode == "120000":
            links.append((target, content))
            continue
        target.write_bytes(content)
        target.chmod(0o555 if mode == "100755" else 0o444)
    for target, content in links:
        try:
            link = content.decode("utf-8")
        except UnicodeDecodeError:
            _refuse()
        if not link or "\0" in link or PurePosixPath(link).is_absolute():
            _refuse()
        unresolved = (
            PurePosixPath(target.relative_to(destination).as_posix()).parent / link
        )
        resolved_parts: list[str] = []
        for part in unresolved.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if not resolved_parts:
                    _refuse()
                resolved_parts.pop()
            else:
                resolved_parts.append(part)
        if not resolved_parts:
            _refuse()
        target.symlink_to(link)
    for target, _content in links:
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(destination.resolve())
            info = resolved.lstat()
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            _refuse()
        if not stat.S_ISREG(info.st_mode):
            _refuse()


def _is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _writable_paths(
    spec: dict, rows: list[tuple[str, str, str]], destination: Path
) -> tuple[str, ...]:
    values = spec.get("writable_paths")
    if not isinstance(values, list) or not values:
        _refuse()
    writable: list[str] = []
    aliases: set[str] = set()
    tree_paths = [path for _mode, _oid, path in rows]
    for value in values:
        path = _relative(value)
        key = _alias(path)
        if key in aliases or any(
            _is_within(path, other) or _is_within(other, path) for other in writable
        ):
            _refuse()
        if any(_is_within(path, item) or _is_within(item, path) for item in tree_paths):
            _refuse()
        aliases.add(key)
        writable.append(path)
        destination.joinpath(*PurePosixPath(path).parts).mkdir(parents=True)
    return tuple(writable)


def _excluded(path: str, writable: tuple[str, ...]) -> bool:
    return any(_is_within(path, root) for root in writable)


def _verify_export(
    repo: Path,
    rows: list[tuple[str, str, str]],
    destination: Path,
    writable: tuple[str, ...] = (),
) -> None:
    expected = {path: (mode, oid) for mode, oid, path in rows}
    actual: set[str] = set()
    for root, directories, files in os.walk(destination, followlinks=False):
        base = Path(root)
        for name in [*directories, *files]:
            target = base / name
            path = target.relative_to(destination).as_posix()
            if _excluded(path, writable):
                continue
            info = target.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            actual.add(path)
            if path not in expected:
                _refuse("CANDIDATE_DRIFT")
    if actual != set(expected):
        _refuse("CANDIDATE_DRIFT")
    for path, (mode, oid) in expected.items():
        target = destination.joinpath(*PurePosixPath(path).parts)
        info = target.lstat()
        expected_bytes = _blob(repo, oid)
        if mode == "120000":
            if not stat.S_ISLNK(info.st_mode):
                _refuse("CANDIDATE_DRIFT")
            actual_bytes = os.readlink(target).encode("utf-8")
        else:
            if not stat.S_ISREG(info.st_mode):
                _refuse("CANDIDATE_DRIFT")
            actual_bytes = target.read_bytes()
            executable = bool(stat.S_IMODE(info.st_mode) & 0o111)
            if executable != (mode == "100755"):
                _refuse("CANDIDATE_DRIFT")
        if actual_bytes != expected_bytes:
            _refuse("CANDIDATE_DRIFT")


def _fingerprint(root: Path, writable: tuple[str, ...] = ()) -> str:
    parts: list[bytes] = []
    for base, directories, files in os.walk(root, followlinks=False):
        directory = Path(base)
        for name in sorted([*directories, *files]):
            path = directory / name
            relative = path.relative_to(root).as_posix()
            if _excluded(relative, writable):
                continue
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if stat.S_ISLNK(info.st_mode):
                kind = b"link"
                content = os.readlink(path).encode("utf-8")
            elif stat.S_ISREG(info.st_mode):
                kind = b"file"
                content = path.read_bytes()
            else:
                _refuse()
            parts.extend(
                [
                    relative.encode(),
                    kind,
                    oct(stat.S_IMODE(info.st_mode)).encode(),
                    content,
                ]
            )
    return _hash(b"\0".join(parts))


def _regular_bytes(path: Path) -> bytes:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            _refuse()
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        _refuse()
    try:
        current = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
        ):
            _refuse()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read()
        after = os.fstat(descriptor)
        if (
            (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            _refuse("CANDIDATE_DRIFT")
        return data
    finally:
        os.close(descriptor)


def _dependencies(spec: dict, destination: Path) -> dict:
    declarations = spec.get("dependencies")
    if not isinstance(declarations, list):
        _refuse()
    files: list[dict[str, object]] = []
    aliases: set[str] = set()
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != {"source", "target"}:
            _refuse()
        source_value = declaration["source"]
        if not isinstance(source_value, str) or not Path(source_value).is_absolute():
            _refuse()
        source = Path(source_value)
        target_name = _relative(declaration["target"])
        key = _alias(target_name)
        if key in aliases:
            _refuse()
        aliases.add(key)
        before = _regular_bytes(source)
        target = destination.joinpath(*PurePosixPath(target_name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(before)
        target.chmod(0o444)
        if _regular_bytes(source) != before:
            _refuse("CANDIDATE_DRIFT")
        files.append(
            {
                "source": source.as_posix(),
                "target": target_name,
                "sha256": _hash(before),
                "size": len(before),
            }
        )
    for base, directories, _files in os.walk(destination, topdown=False):
        Path(base).chmod(0o555)
        for name in directories:
            (Path(base) / name).chmod(0o555)
    return {"files": files}


def _runtime_inputs(stdlib_roots, library_root, configuration):
    """Capture actual runtime bytes and membership; never substitute stat caches."""
    roots = sorted({str(Path(root).resolve(strict=True)) for root in stdlib_roots})
    library = Path(library_root).resolve(strict=True)
    paths = set()
    for name in roots:
        root = Path(name)
        if not root.is_dir():
            _refuse()
        for base, directories, files in os.walk(root, followlinks=False, onerror=lambda error: _refuse()):
            directories[:] = sorted(value for value in directories
                                     if value not in {'site-packages', 'dist-packages', '__pycache__'})
            if any((Path(base) / value).is_symlink() for value in directories):
                _refuse()
            paths.update(Path(base) / value for value in files if not value.endswith(('.pyc', '.pyo')))
    if not library.is_dir():
        _refuse()
    # Native libraries in the declared vendor LIBDIR. Other loader locations
    # require explicit closure; _verify_native_runtime rejects unresolved links.
    paths.update(path for path in library.iterdir() if path.name.endswith('.dylib') or '.so' in path.name)
    records = []
    for path in sorted(paths):
        target = path.resolve(strict=True)
        if not any(target.is_relative_to(Path(root)) for root in [*roots, str(library)]):
            _refuse()
        raw = _regular_bytes(target)
        records.append({'source': str(path), 'resolved': str(target), 'sha256': _hash(raw), 'size': len(raw)})
    config = {}
    for name in sorted(set(configuration)):
        path = Path(name)
        if path.is_symlink():
            _refuse()
        config[name] = _hash(_regular_bytes(path)) if os.path.lexists(path) else None
    return {'stdlib_roots': roots, 'library_root': str(library), 'files': records, 'configuration': config}


@lru_cache(maxsize=512)
def _native_load_commands(name, fingerprint, inspector_fingerprint):
    # Cache only deterministic parsed commands, keyed by actual file/tool bytes.
    # Every runtime snapshot still reads and hashes all runtime input files.
    del inspector_fingerprint
    try:
        result = subprocess.run(['/usr/bin/otool', '-l', name], capture_output=True, timeout=15)
        if result.returncode or _hash(_regular_bytes(Path(name))) != fingerprint:
            _refuse()
        dependencies, rpaths, command = [], [], None
        for line in result.stdout.decode('utf-8').splitlines():
            value = line.strip()
            if value.startswith('cmd '):
                command = value[4:]
            elif command == 'LC_RPATH' and value.startswith('path '):
                rpaths.append(value[5:].split(' (offset ', 1)[0])
            elif command in {'LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB',
                             'LC_LOAD_UPWARD_DYLIB', 'LC_LAZY_LOAD_DYLIB'} and value.startswith('name '):
                dependencies.append(value[5:].split(' (offset ', 1)[0])
        return tuple(dependencies), tuple(rpaths)
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        _refuse()


def _verify_native_runtime(executable, inputs):
    """Darwin vendor closure; OS shared-cache libraries remain platform TCB."""
    tool = Path('/usr/bin/otool')
    tool_bytes = _regular_bytes(tool)
    known = {str(Path(item['resolved'])) for item in inputs['files']}
    known.add(str(executable))
    native = {str(executable)}
    native.update(name for name in known if Path(name).suffix == '.dylib' or '.so' in Path(name).name)
    fingerprints = {item['resolved']: item['sha256'] for item in inputs['files']}
    fingerprints[str(executable)] = _hash(_regular_bytes(executable))
    commands = {name: _native_load_commands(name, fingerprints[name], _hash(tool_bytes)) for name in sorted(native)}
    allowed_roots = [Path(root) for root in [*inputs['stdlib_roots'], inputs['library_root']]]
    def resolved_path(value, image):
        value = value.replace('@loader_path', str(Path(image).parent))
        value = value.replace('@executable_path', str(executable.parent))
        if not value.startswith('/'):
            _refuse()
        return Path(value).resolve()
    for name, (dependencies, rpaths) in commands.items():
        search = []
        for image, values in ((name, rpaths), (str(executable), commands[str(executable)][1])):
            for value in values:
                directory = resolved_path(value, image)
                if not any(directory.is_relative_to(root) for root in allowed_roots):
                    _refuse()
                search.append(directory)
        for dependency in dependencies:
            if dependency.startswith(('/usr/lib/', '/System/Library/')):
                continue
            if dependency.startswith('@rpath/'):
                targets = {str((directory / dependency[7:]).resolve()) for directory in search
                           if os.path.lexists(directory / dependency[7:])}
                if not targets or not targets <= known:
                    _refuse()
            elif str(resolved_path(dependency, name)) not in known:
                _refuse()
    if _regular_bytes(tool) != tool_bytes:
        _refuse('CANDIDATE_DRIFT')
    return {'source': str(tool), 'sha256': _hash(tool_bytes)}


def _runtime(interpreter: str) -> dict:
    path = Path(interpreter)
    if not path.is_absolute():
        _refuse()
    try:
        resolved = path.resolve(strict=True)
        info = resolved.lstat()
    except OSError:
        _refuse()
    if not stat.S_ISREG(info.st_mode):
        _refuse()
    executable = _regular_bytes(resolved)
    if executable[:4] not in {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                               b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                               b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}:
        _refuse()
    probe = (
        "import json,platform,sys,sysconfig;print(json.dumps({"
        "'implementation':platform.python_implementation(),'version':platform.python_version(),"
        "'actual_executable':sys.executable,'stdlib':[sysconfig.get_path('stdlib'),sysconfig.get_path('platstdlib')],"
        "'libdir':sysconfig.get_config_var('LIBDIR'),'prefix':sys.prefix,"
        "'zip_paths':[p for p in sys.path if p.endswith('.zip')],"
        "'platform':{k:getattr(platform,k)() for k in ('system','release','version','machine')}}))"
    )
    with tempfile.TemporaryDirectory(prefix='harness-runtime-probe-') as directory:
        identity = subprocess.run(
            [str(path), '-I', '-S', '-B', '-X', f'pycache_prefix={directory}/cache', '-c', probe],
            cwd=directory, env={'PATH': str(path.parent)}, capture_output=True,
        )
    if identity.returncode:
        _refuse()
    try:
        data = json.loads(identity.stdout)
    except json.JSONDecodeError:
        _refuse()
    if (not isinstance(data, dict) or data.get('implementation') != 'CPython'
            or not isinstance(data.get('platform'), dict) or data['platform'].get('system') != 'Darwin'
            or not isinstance(data.get('actual_executable'), str)
            or Path(data['actual_executable']).resolve() != resolved):
        _refuse()
    configuration = [str(path.parent.parent / 'pyvenv.cfg'), str(resolved.parent.parent / 'pyvenv.cfg'),
                     str(path.with_suffix('._pth')), str(resolved.with_suffix('._pth')), *data['zip_paths']]
    try:
        inputs = _runtime_inputs(data['stdlib'], data['libdir'], configuration)
        inspector = _verify_native_runtime(resolved, inputs)
    except (OSError, TypeError, KeyError, ValueError):
        _refuse()
    if _regular_bytes(resolved) != executable:
        _refuse("CANDIDATE_DRIFT")
    return {
        'runtime_inputs': inputs,
        'platform': data['platform'],
        'native_inspector': inspector,
        "implementation": data["implementation"],
        "version": data["version"],
        "executable": path.as_posix(),
        "resolved_executable": resolved.as_posix(),
        "executable_sha256": _hash(executable),
    }


def _environment(
    spec: dict,
    interpreter: str,
    dependency_root: Path,
    export: Path,
    writable: tuple[str, ...],
) -> tuple[dict[str, str], dict[str, object]]:
    declared = spec.get("environment")
    if not isinstance(declared, dict) or any(
        name not in DECLARED_ENVIRONMENT or not isinstance(value, str)
        for name, value in declared.items()
    ):
        _refuse()
    output = export.joinpath(*PurePosixPath(writable[0]).parts)
    home = output / ".home"
    cache = output / ".cache"
    config = output / ".config"
    for path in (home, cache, config):
        path.mkdir(parents=True, exist_ok=True)
    env = {
        "GIT_CEILING_DIRECTORIES": str(export.parent),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(home),
        "LC_ALL": "C",
        "PATH": str(Path(interpreter).parent),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(cache / 'bytecode'),
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(dependency_root),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "TZ": "UTC",
        "XDG_CACHE_HOME": str(cache),
        "XDG_CONFIG_HOME": str(config),
    }
    env.update(declared)
    projection = {
        "names": sorted(env),
        "declared": {name: _hash(value.encode()) for name, value in sorted(declared.items())},
        "ambient_inherited": [],
    }
    return env, projection


def _make_read_only(root: Path, writable: tuple[str, ...]) -> None:
    paths = sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if _excluded(relative, writable) or path.is_symlink():
            continue
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            path.chmod(0o555)
        elif stat.S_ISREG(info.st_mode):
            path.chmod(0o555 if info.st_mode & 0o111 else 0o444)
        else:
            _refuse()
    root.chmod(0o555)


def _outputs(root: Path, writable: tuple[str, ...]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for base in writable:
        output = root.joinpath(*PurePosixPath(base).parts)
        for path in sorted(output.rglob("*")):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                _refuse()
            data = path.read_bytes()
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _hash(data),
                    "size": len(data),
                }
            )
    return result


def _retain_failed_outputs(
    repo: Path,
    candidate: dict,
    export: Path,
    writable: tuple[str, ...],
    outputs: list[dict[str, object]],
) -> str:
    identity = _hash(
        json.dumps(
            {
                "candidate_tree": candidate["candidate_tree"],
                "outputs": outputs,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    target = (
        repo
        / ".harness"
        / "evidence"
        / "candidate-run-output"
        / identity[7:]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError:
        _refuse()
    for item in outputs:
        path = str(item["path"])
        owner = next((root for root in writable if _is_within(path, root)), None)
        if owner is None:
            _refuse()
        relative = PurePosixPath(path).relative_to(PurePosixPath(owner))
        destination = target.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = export.joinpath(*PurePosixPath(path).parts)
        data = source.read_bytes()
        if _hash(data) != item["sha256"]:
            _refuse("CANDIDATE_DRIFT")
        destination.write_bytes(data)
        destination.chmod(0o400)
    return target.relative_to(repo).as_posix()


def _safe_command(argv: list[str], root: Path) -> str:
    values = [Path(argv[0]).name, *argv[1:]]
    return shlex.join(
        [
            value.replace(str(root), "<candidate-export>")
            for value in values
        ]
    )


def _validate_spec(spec: dict) -> None:
    try:
        validate(spec, read_schema("candidate-proof-spec.schema.json"))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise CandidateRunnerError("CANDIDATE_PROOF_UNQUALIFIED") from exc
    if spec.get("input_policy") != INPUT_POLICY or spec.get("profile") not in PROFILES:
        _refuse()


def _selectors(spec: dict) -> list[str]:
    values = spec.get("selectors")
    if not isinstance(values, list) or not values:
        _refuse()
    result = []
    for value in values:
        if not isinstance(value, str) or "::" not in value:
            _refuse()
        selector = _relative(value.split("::", 1)[0])
        suffix = value[len(value.split("::", 1)[0]) :]
        if "[" in suffix or "\0" in suffix or any(
            part in {"", ".", ".."} for part in suffix.split("::")[1:]
        ):
            _refuse()
        result.append(selector + suffix)
    return result


def _collected_nodes(stdout: bytes) -> list[str]:
    nodes: list[str] = []
    for raw in stdout.decode("utf-8", errors="strict").splitlines():
        value = raw.strip()
        if "::" not in value or value.startswith(("=", "<")):
            continue
        path = value.split("::", 1)[0]
        _relative(path)
        if value in nodes:
            _refuse()
        nodes.append(value)
    if not nodes:
        _refuse()
    return nodes


def _junit_nodes(path: Path, collected: list[str]) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        _refuse()
    cases = list(root.iter("testcase"))
    if not cases:
        _refuse()
    nodes: list[str] = []
    for case in cases:
        if any(case.find(name) is not None for name in ("failure", "error", "skipped")):
            _refuse()
        classname = case.get("classname")
        name = case.get("name")
        if not classname or not name:
            _refuse()
        matches = []
        for node in collected:
            parts = node.split("::")
            if parts[-1] != name:
                continue
            module = parts[0]
            if module.endswith(".py"):
                module = module[:-3]
            expected_class = ".".join([module.replace("/", "."), *parts[1:-1]])
            if (
                classname == expected_class
                or classname.endswith("." + expected_class)
                or expected_class.endswith("." + classname)
            ):
                matches.append(node)
        if len(matches) != 1 or matches[0] in nodes:
            _refuse()
        nodes.append(matches[0])
    if set(nodes) != set(collected):
        _refuse()
    return sorted(nodes)


def _matches_node(binding: str, executed: str) -> bool:
    return executed == binding or executed.startswith(binding + "[")


def _derive_qualification(
    repo: Path,
    candidate: dict,
    evidence_type: str,
    executed: list[str],
) -> tuple[list[str], list[str], list[dict[str, object]], list[str], list[str]]:
    from .candidate_assessment import CandidateAssessmentError, derive_qualification

    try:
        return derive_qualification(repo, candidate, evidence_type, executed)
    except CandidateAssessmentError as exc:
        raise CandidateRunnerError(str(exc)) from exc


def _local_build_configuration(export: Path) -> tuple[str, list[str]]:
    path = export / "pyproject.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CandidateRunnerError("CANDIDATE_PROOF_UNQUALIFIED") from exc
    build = document.get("build-system")
    if not isinstance(build, dict) or build.get("requires") != []:
        _refuse()
    backend = build.get("build-backend")
    backend_paths = build.get("backend-path")
    if (
        not isinstance(backend, str)
        or not backend
        or any(
            not (part.replace("_", "a").isalnum())
            for part in backend.replace(":", ".").split(".")
        )
        or not isinstance(backend_paths, list)
        or not backend_paths
    ):
        _refuse()
    normalized: list[str] = []
    for value in backend_paths:
        relative = "." if value == "." else _relative(value)
        target = export if relative == "." else export.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(export.resolve())
            info = target.lstat()
        except (OSError, RuntimeError, ValueError):
            _refuse()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            _refuse()
        normalized.append(relative)
    return backend, normalized


def run(repo: Path, candidate: dict, spec: dict) -> dict:
    """Execute one strict cooperative profile and return honest candidate-domain facts."""
    _validate_spec(spec)
    profile = spec["profile"]
    rows = _tree_files(repo, candidate.get("candidate_tree"))
    with tempfile.TemporaryDirectory(prefix="harness-candidate-proof-") as directory:
        work = Path(directory)
        export = work / "export"
        dependencies = work / "dependencies"
        export.mkdir()
        dependencies.mkdir()
        if _git(export, "rev-parse", "--is-inside-work-tree").returncode == 0:
            _refuse()
        _materialize(repo, rows, export)
        _verify_export(repo, rows, export)
        writable = _writable_paths(spec, rows, export)
        dependency_record = _dependencies(spec, dependencies)
        runtime = _runtime(spec["interpreter"])
        env, environment = _environment(
            spec, spec["interpreter"], dependencies, export, writable
        )
        before = _fingerprint(export, writable)
        _make_read_only(export, writable)
        executed_tests: list[str] = []
        covered_tests: list[str] = []
        covered_cases: list[str] = []
        bindings: list[dict[str, object]] = []
        plan_items: list[str] = []
        interfaces: list[str] = []
        if profile == "python-script-v1":
            script = _relative(spec.get("script"))
            script_path = export.joinpath(*PurePosixPath(script).parts)
            try:
                script_info = script_path.lstat()
            except OSError:
                _refuse()
            if not stat.S_ISREG(script_info.st_mode) or stat.S_ISLNK(script_info.st_mode):
                _refuse()
            args = spec.get("args")
            if not isinstance(args, list) or any(
                not isinstance(value, str)
                or "\0" in value
                or value.startswith("-")
                for value in args
            ):
                _refuse()
            evidence_type = "custom"
            command = [spec["interpreter"], "-S", script, *args]
            result = subprocess.run(command, cwd=export, env=env, capture_output=True)
        elif profile == "pytest-junit-v1":
            evidence_type = spec["evidence_type"]
            selectors = _selectors(spec)
            base = [
                spec["interpreter"],
                "-S",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
            ]
            collection = subprocess.run(
                [*base, "--collect-only", *selectors],
                cwd=export,
                env=env,
                capture_output=True,
            )
            if collection.returncode:
                _refuse()
            collected = _collected_nodes(collection.stdout)
            junit = f"{writable[0]}/junit.xml"
            command = [*base, *selectors, f"--junitxml={junit}"]
            result = subprocess.run(command, cwd=export, env=env, capture_output=True)
            if result.returncode:
                _refuse()
            executed_tests = _junit_nodes(export / junit, collected)
            (
                covered_tests,
                covered_cases,
                bindings,
                plan_items,
                interfaces,
            ) = _derive_qualification(repo, candidate, evidence_type, executed_tests)
            if not bindings:
                _refuse()
        else:
            evidence_type = "build"
            _local_build_configuration(export)
            build_output = export.joinpath(
                *PurePosixPath(writable[0]).parts, "dist"
            )
            build_output.mkdir()
            command = [
                spec["interpreter"],
                "-S",
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--outdir",
                f"{writable[0]}/dist",
                ".",
            ]
            result = subprocess.run(command, cwd=export, env=env, capture_output=True)
            if result.returncode:
                _refuse()
            artifacts = list(build_output.iterdir())
            if len(artifacts) != 1:
                _refuse()
            artifact_path = artifacts[0]
            if not artifact_path.name.endswith(".whl"):
                _refuse()
            try:
                artifact_info = artifact_path.lstat()
            except OSError:
                _refuse()
            if not stat.S_ISREG(artifact_info.st_mode) or stat.S_ISLNK(artifact_info.st_mode):
                _refuse()
        _verify_export(repo, rows, export, writable)
        if _runtime(spec['interpreter']) != runtime:
            _refuse('CANDIDATE_DRIFT')
        after = _fingerprint(export, writable)
        if before != after:
            _refuse("CANDIDATE_DRIFT")
        outputs = _outputs(export, writable)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        source_config = {
            "schema": spec["schema"],
            "profile": profile,
            "environment": environment,
            "input_policy": dict(INPUT_POLICY),
            "writable_paths": list(writable),
        }
        execution = {
            "profile": profile,
            "argv": command,
            "exit_code": result.returncode,
            "candidate_tree": candidate["candidate_tree"],
            "parent_commit": candidate["parent"],
            "source_before": before,
            "source_after": after,
            "runtime": runtime,
            "dependencies": dependency_record,
            "source_config": source_config,
            "stdout_sha256": _hash(result.stdout),
            "stderr_sha256": _hash(result.stderr),
            "outputs": outputs,
        }
        if result.returncode != 0:
            execution["retained_output_ref"] = _retain_failed_outputs(
                repo, candidate, export, writable, outputs
            )
        record = {
            "type": evidence_type,
            "timestamp": timestamp,
            "command": _safe_command(command, export),
            "exit_code": result.returncode,
            "execution_domain": "outside-git",
            "candidate_tree": candidate["candidate_tree"],
            "source_fingerprint": before,
            "covered_tests": covered_tests,
            "covered_test_cases": covered_cases,
            "executed_tests": executed_tests,
        }
        qualification = {
            "coverage_complete": result.returncode == 0,
            "profile_version": PROFILE_VERSION,
            "evidence_type": evidence_type,
            "bindings": bindings,
            "interfaces": interfaces,
            "plan_items": plan_items,
        }
        return {
            "execution": execution,
            "record": record,
            "qualification": qualification,
        }
