"""Independent local tool facts; no product Context, execution or version guesses."""
from __future__ import annotations

import csv
import errno
import hashlib
import importlib
import io
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from email.parser import BytesParser
from importlib import metadata
from pathlib import Path

from .context.model import ContextBuildError
from .schema_resources import SCHEMA_NAMES, read_schema, schema_versions
from .source_access import (
    RegularFileSnapshot,
    RegularFileTooLargeError,
    read_regular_snapshot_beneath,
)

PACKAGE = 'superpowers-engineering-harness'
LIMIT = 16 * 1024 * 1024
MODULES = ('harness', 'harness.cli', 'harness.evidence_plan', 'harness.execution_capture')


@dataclass
class ToolIdentitySnapshot:
    report: dict
    files: dict[Path, tuple[str, RegularFileSnapshot]] = field(default_factory=dict)
    schemas: dict | None = None


def _hash(value: bytes) -> str:
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def _version(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value))


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _json(content: bytes) -> dict:
    value = json.loads(content, object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise TypeError('tool manifest must be an object')
    return value


def _read(snapshot: ToolIdentitySnapshot, path: Path, component: str) -> bytes:
    path = path.absolute()
    observed = read_regular_snapshot_beneath(path, Path(path.anchor), max_bytes=LIMIT)
    previous = snapshot.files.get(path)
    if previous is not None and previous[1] != observed:
        raise ContextBuildError('CONTEXT_STALE', 'tool input changed')
    snapshot.files[path] = (component, observed)
    return observed.content


def _cli(snapshot: ToolIdentitySnapshot) -> dict:
    result = {'status': 'INVALID', 'package': PACKAGE, 'candidate_version': None,
              'verified_version': None, 'module_paths': {}, 'metadata_path': None}
    try:
        distribution = metadata.distribution(PACKAGE)
    except metadata.PackageNotFoundError:
        return {**result, 'status': 'MISSING'}
    except (OSError, ValueError, TypeError):
        return result
    # Filesystem metadata origin must be known before any potentially unbounded
    # stdlib metadata/RECORD property read. Other providers cannot attest origin.
    origin = getattr(distribution, '_path', None)
    if not isinstance(origin, Path) or not origin.name.endswith('.dist-info'):
        return {**result, 'status': 'SOURCE_AMBIGUOUS'}
    try:
        document = BytesParser().parsebytes(_read(snapshot, origin / 'METADATA', 'cli_identity'))
        names, versions = document.get_all('Name', []), document.get_all('Version', [])
        if (len(names) != 1 or len(versions) != 1 or not _version(versions[0])
                or re.sub(r'[-_.]+', '-', names[0].lower()) != PACKAGE):
            return result
        result.update(candidate_version=versions[0], metadata_path=str(origin / 'METADATA'))
        direct_url = origin / 'direct_url.json'
        # Register absence too: appearing metadata must not silently certify a
        # different editable provenance at finalization.
        if direct_url.is_symlink() or direct_url.exists():
            direct = _json(_read(snapshot, direct_url, 'cli_identity'))
            info = direct.get('dir_info', {})
            if (not isinstance(info, dict)
                    or ('editable' in info and not isinstance(info['editable'], bool))):
                return result
            if info.get('editable') is True:
                return {**result, 'status': 'SOURCE_AMBIGUOUS'}
        else:
            snapshot.report['_absent_direct_url'] = str(direct_url)
        try:
            record = _read(snapshot, origin / 'RECORD', 'cli_identity').decode('utf-8')
        except FileNotFoundError:
            return {**result, 'status': 'SOURCE_AMBIGUOUS'}
        # RECORD is the same wheel file enumeration used by distribution.files,
        # but parsed from already bounded bytes instead of a second unbounded read.
        files = {row[0] for row in csv.reader(io.StringIO(record)) if row}
        expected_meta = origin.name + '/METADATA'
        if expected_meta not in files:
            return {**result, 'status': 'SOURCE_AMBIGUOUS'}
        if Path(distribution.locate_file(expected_meta)).resolve() != (origin / 'METADATA').resolve():
            return {**result, 'status': 'SOURCE_AMBIGUOUS'}
        for name in MODULES:
            module = importlib.import_module(name)
            actual = Path(module.__file__).resolve()
            relative = 'harness/__init__.py' if name == 'harness' else name.replace('.', '/') + '.py'
            result['module_paths'][name] = str(actual)
            if relative not in files or Path(distribution.locate_file(relative)).resolve() != actual:
                return {**result, 'status': 'SOURCE_AMBIGUOUS'}
        return {**result, 'status': 'VERIFIED', 'verified_version': versions[0]}
    except ContextBuildError as exc:
        return {**result, 'status': 'CHANGED' if exc.code == 'CONTEXT_STALE' else 'INVALID'}
    except (OSError, ValueError, TypeError, UnicodeError, AttributeError, RecursionError, csv.Error):
        return result


def _schemas() -> dict:
    versions = schema_versions()
    for name in SCHEMA_NAMES:
        read_schema(name)  # identity alone does not prove parseable schema bytes
    encoded = json.dumps(versions, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return {'status': 'VERIFIED', 'versions': versions, 'sha256': _hash(encoded),
            'resource_prefix': 'package:harness/schemas/'}


def _skills(snapshot: ToolIdentitySnapshot, path: Path | None) -> dict:
    result = {'status': 'NOT_PROVIDED', 'path': None, 'version': None, 'sha256': None}
    if path is None:
        return result
    result.update(status='INVALID', path=str(path))
    try:
        if not path.is_absolute() or path.name != 'package.json':
            return result
        raw = _read(snapshot, path, 'skills_identity')
        document = _json(raw)
        if document.get('name') != PACKAGE or not _version(document.get('version')):
            return result
        cli = snapshot.report['cli_identity']
        status = ('UNVERIFIABLE' if cli['status'] != 'VERIFIED' else
                  'MATCH' if cli['verified_version'] == document['version'] else 'MISMATCH')
        return {**result, 'status': status, 'version': document['version'], 'sha256': _hash(raw)}
    except FileNotFoundError:
        return {**result, 'status': 'MISSING'}
    except PermissionError:
        return {**result, 'status': 'UNREADABLE'}
    except ContextBuildError as exc:
        return {**result, 'status': 'CHANGED' if exc.code == 'CONTEXT_STALE' else 'INVALID'}
    except OSError as exc:
        return {**result, 'status': 'INVALID' if exc.errno in {None, errno.ELOOP, errno.ENOTDIR} else 'UNREADABLE'}
    except (ValueError, TypeError, UnicodeError, RecursionError, RegularFileTooLargeError):
        return result


def begin_tool_identity(skills_package: Path | None) -> ToolIdentitySnapshot:
    snapshot = ToolIdentitySnapshot({'diagnostics': [], 'errors': []})
    snapshot.report['cli_identity'] = _cli(snapshot)
    try:
        schema = _schemas()
    except (OSError, ValueError, TypeError, ContextBuildError, RecursionError):
        schema = {'status': 'INVALID', 'versions': None, 'sha256': None,
                  'resource_prefix': 'package:harness/schemas/'}
    snapshot.schemas = schema.get('versions')
    snapshot.report['schema_identity'] = schema
    snapshot.report['skills_identity'] = _skills(snapshot, skills_package)
    return snapshot


def finish_tool_identity(snapshot: ToolIdentitySnapshot) -> dict:
    report = deepcopy(snapshot.report)
    for path, (component, previous) in snapshot.files.items():
        try:
            current = read_regular_snapshot_beneath(path, Path(path.anchor), max_bytes=LIMIT)
            changed = current != previous
        except (OSError, ValueError, ContextBuildError):
            changed = True
        if changed:
            report[component]['status'] = 'CHANGED'
            if component == 'skills_identity':
                report[component]['sha256'] = None
    absent = report.pop('_absent_direct_url', None)
    if absent and (Path(absent).is_symlink() or Path(absent).exists()):
        report['cli_identity']['status'] = 'CHANGED'
    if report['cli_identity']['status'] != 'VERIFIED':
        report['cli_identity']['verified_version'] = None
        if report['skills_identity']['status'] in {'MATCH', 'MISMATCH'}:
            report['skills_identity']['status'] = 'UNVERIFIABLE'
    if snapshot.schemas is not None:
        try:
            changed = _schemas()['versions'] != snapshot.schemas
        except (OSError, ValueError, TypeError, ContextBuildError, RecursionError):
            changed = True
        if changed:
            report['schema_identity'].update(status='CHANGED', versions=None, sha256=None)
    for component in ('cli_identity', 'schema_identity', 'skills_identity'):
        status = report[component]['status']
        if status not in {'VERIFIED', 'MATCH', 'NOT_PROVIDED'}:
            report['diagnostics'].append({'code': 'TOOL_' + status, 'component': component,
                                         'source_ref': None, 'message': 'Tool input could not be certified.'})
    return report
