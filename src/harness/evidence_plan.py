"""Read-only declared-target diagnostics; no execution or Gate authority."""

from __future__ import annotations

import ast
import hashlib
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from . import source_access
from .collect_evidence import command_covers_test, record_covers_test
from .context.freshness import capture, contained_path, file_version, require_fresh
from .context.integrity import _load_stable
from .context.model import ContextBuildError
from .evidence_validator import EvidenceStatus, project_evidence
from .telemetry_lock import telemetry_lock
from .test_plan import TEST_EVIDENCE_TYPES


@contextmanager
def diagnostic_sources(harness_dir: Path):
    """Load stable facts without generating Context, expansions or indexes."""
    root = harness_dir.absolute()
    with telemetry_lock(root):
        _require_no_pending_publications(root)
        before = capture(root)
        if not source_access.exists(root / 'decisions/index.yaml') and source_access.members(root / 'decisions', 'DEC-*.yaml'):
            raise ContextBuildError('INVALID_HARNESS_STATE', 'decision index missing; explicit reindex required')
        source = _load_stable(root, before)
        proposed_versions = {}
        yield source, before, proposed_versions
        _require_no_pending_publications(root)
        require_fresh(before, capture(root))
        for name, expected in proposed_versions.items():
            path = contained_path(root.parent, name)
            _regular_path(root.parent, path)
            if file_version(path) != expected:
                raise ContextBuildError('CONTEXT_STALE', 'declared target changed during diagnosis')


def _require_no_pending_publications(root: Path):
    """Read-only diagnostics cannot repair or certify partial publication."""
    _regular_path(root.parent, root)
    directory = root / '.transactions'
    if directory.is_symlink() or (source_access.exists(directory) and not source_access.is_dir(directory)):
        raise ContextBuildError('TRANSACTION_RECOVERY_BLOCKED', 'recovery storage is unsafe')
    if source_access.is_dir(directory) and source_access.members(directory, '*'):
        raise ContextBuildError('TRANSACTION_RECOVERY_REQUIRED', 'recover publication before read-only diagnosis')


def _regular_path(root: Path, path: Path):
    for member in (path, *path.parents):
        if member == root.parent:
            break
        if member.is_symlink():
            raise ContextBuildError('CONTEXT_REFERENCE_BROKEN', 'declared target cannot use symlinks')


def inspect_declared_test(repo_root: Path, test: str, versions: dict) -> str | None:
    """Resolve static Python selectors without import/collection side effects.

    Dynamic/parametrized selectors are explicitly unverified, never guessed valid.
    File presence is not a claim that a runner executed the file.
    """
    filename, *nodes = test.split('::')
    if not filename or PureWindowsPath(filename).drive or '\\' in filename or any(c in filename for c in '*?['):
        raise ContextBuildError('CONTEXT_REFERENCE_BROKEN', 'noncanonical declared test')
    path = contained_path(repo_root, filename)
    _regular_path(repo_root, path)
    if not source_access.is_file(path):
        versions[filename] = file_version(path)
        return 'FILE_MISSING'
    data = source_access.read_regular_bytes_beneath(path, repo_root)
    version = 'sha256:' + hashlib.sha256(data).hexdigest()
    previous = versions.setdefault(filename, version)
    if previous != version:
        raise ContextBuildError('CONTEXT_STALE', 'declared target bytes changed')
    if not nodes:
        return None
    if path.suffix != '.py' or any(not node or '[' in node for node in nodes):
        return 'SELECTOR_UNVERIFIED'
    try:
        body = ast.parse(data).body
    except (SyntaxError, UnicodeError, ValueError) as exc:
        raise ContextBuildError('CONTEXT_SCHEMA_INVALID', 'cannot parse declared test selector') from exc
    for index, node in enumerate(nodes):
        match = next((item for item in body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == node), None)
        if match is None:
            return 'SELECTOR_MISSING'
        if index < len(nodes) - 1 and not isinstance(match, ast.ClassDef):
            return 'SELECTOR_UNVERIFIED'
        body = match.body
    return None


def case_records(source):
    for kind, records in (('requirements', source.requirements), ('invariants', source.invariants)):
        for record in records:
            for case in record.get('test_plan', {}).get('cases', []):
                yield kind, record, case


def test_references(source) -> dict[str, list[dict]]:
    references = {test: [] for test in (source.impact or {}).get('impact', {}).get('required_tests', [])}
    items = (source.plan or {}).get('items', [])
    for _kind, owner, case in case_records(source):
        qualified = f"{owner['id']}/{case['id']}"
        plan_items = sorted(item['id'] for item in items if qualified in item.get('test_case_refs', []) or owner['id'] in item.get('requirement_refs', []) or owner['id'] in item.get('invariant_refs', []))
        ref = {'owner': owner['id'], 'case': case['id'], 'plan_items': plan_items}
        for test in case.get('tests', []):
            references.setdefault(test, []).append(ref)
    # Plan surfaces are not guessed test paths. Only already-declared tests link.
    for test, refs in references.items():
        for item in items:
            if test in item.get('surfaces', []):
                refs.append({'plan_items': [item['id']]})
    return references


def environment_report(source) -> dict:
    return {
        'execution_authority': 'NOT_GRANTED_BY_DIAGNOSTIC',
        'prerequisites': 'NOT_VERIFIED',
        'shared_resource_policy': 'SERIAL_UNLESS_DECLARED_ISOLATION',
        'authorizations': source.task.get('authorizations', {}),
    }


def plan_evidence(harness_dir: Path) -> dict:
    root = harness_dir.absolute()
    with diagnostic_sources(root) as (source, before, versions):
        diagnostics = []
        references = test_references(source)
        executable = set()
        for test, refs in sorted(references.items()):
            problem = inspect_declared_test(root.parent, test, versions)
            if problem:
                diagnostics.append({'code': 'MISSING_DECLARED_TEST' if problem != 'SELECTOR_UNVERIFIED' else problem,
                                    'test': test, 'reason': problem, 'references': refs})
            else:
                executable.add(test)
        for _kind, owner, case in case_records(source):
            if case['strategy'] != 'manual' and not case.get('tests'):
                diagnostics.append({'code': 'UNBOUND_TEST_CASE', 'owner': owner['id'], 'case': case['id']})
        fresh = []
        for evidence in source.evidence:
            path = contained_path(root.parent, evidence['ref'])
            projection = project_evidence(path, source.workspace.head, source.workspace.fingerprint, expected_success=None)
            if projection.status is not EvidenceStatus.FRESH:
                diagnostics.append({'code': projection.code, 'evidence': evidence['ref']})
            record = projection.record
            if (projection.status is EvidenceStatus.FRESH and record['exit_code'] == 0 and record['type'] in TEST_EVIDENCE_TYPES
                    and record.get('scope') in {None, 'related'} and record.get('phase') != 'red'):
                fresh.append(record)
        uncovered = []
        for test in sorted(executable):
            if not any(record_covers_test(record, test, root.parent) and command_covers_test(record.get('command', ''), test, root.parent) for record in fresh):
                uncovered.append(test)
                diagnostics.append({'code': 'NO_FRESH_COVERAGE', 'test': test, 'references': references[test]})
        if source.plan_assessment is not None:
            for blocker in source.plan_assessment.final_blockers:
                if blocker.code.startswith('PLAN_'):
                    diagnostics.append({'code': blocker.code, 'plan_item': blocker.source})
        # Whole-file targets already subsume their explicitly declared selectors.
        minimal = [test for test in uncovered if '::' not in test or test.split('::', 1)[0] not in uncovered]
        report = {
            'version': 1, 'task_id': source.task['task']['id'], 'advisory': True,
            'execution_authority': False, 'source_versions': before,
            'diagnostics': diagnostics,
            'execution_counts': {'tests': 0, 'business': 0, 'environment': 0},
            'execution_plan': {'scope': 'related', 'tests': minimal},
            'environment': environment_report(source),
        }
    return report
