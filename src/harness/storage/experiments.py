"""Read-only experiment qualification. No GC authority or destructive API."""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.schema_resources import read_schema
from harness.transaction_recovery import _locked
from .archive import ReferenceOrigin, resolve_archive, validate_origin
from .journal import _relative
from .layout import StorageError, admit_storage, require_layout_admission

_DEFAULT_LIMITS = {'max_nodes': 8192, 'max_bytes': 64 * 1024 * 1024, 'max_manifests': 128, 'max_depth': 128}


def _limits(value):
    if not isinstance(value, dict) or set(value) != set(_DEFAULT_LIMITS):
        raise StorageError('STORE_UNSAFE_NODE')
    for name, cap in _DEFAULT_LIMITS.items():
        if type(value[name]) is not int or not 0 < value[name] <= cap:
            raise StorageError('STORE_UNSAFE_NODE')
    return dict(value)


def _path(value, experiment_id):
    path = _relative(value)
    parent = Path('.harness-store/experiments') / experiment_id
    if path == parent or not path.is_relative_to(parent) or path.name == 'manifest.yaml':
        raise StorageError('STORE_UNSAFE_NODE')
    return path


@dataclass
class _Scan:
    session: object
    limits: dict
    nodes: dict = field(default_factory=dict)
    logical_bytes: int = 0
    complete: bool = True

    def tree(self, relative):
        pending, selected, unsafe = [(relative, 0)], {}, False
        device = self.session.layout.identity['header']['workspace_identity'][0]
        while pending:
            path, depth = pending.pop()
            key = path.as_posix()
            if key in self.nodes:
                selected[key] = self.nodes[key]
                continue
            if len(self.nodes) >= self.limits['max_nodes'] or depth > self.limits['max_depth']:
                self.complete = False
                break
            parent = source_access._open_beneath(self.session.repo_root / path.parent, self.session.repo_root)
            try:
                info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                node = {'identity': [info.st_dev, info.st_ino], 'kind': 'opaque', 'sha256': None, 'size': None}
                if info.st_dev != device:
                    unsafe = True
                elif stat.S_ISDIR(info.st_mode):
                    opened = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        held = os.fstat(opened)
                        if [held.st_dev, held.st_ino] != node['identity']:
                            raise StorageError('STORE_IDENTITY_CHANGED')
                        node['kind'] = 'directory'
                        with os.scandir(opened) as children:
                            for child in children:
                                if len(pending) + len(self.nodes) >= self.limits['max_nodes']:
                                    self.complete = False
                                    break
                                pending.append((path / child.name, depth + 1))
                    finally:
                        os.close(opened)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    if self.logical_bytes + info.st_size > self.limits['max_bytes']:
                        self.complete = False
                        break
                    snapshot = source_access.read_regular_snapshot_beneath(
                        self.session.repo_root / path, self.session.repo_root, max_bytes=self.limits['max_bytes'])
                    if ([snapshot.device, snapshot.inode] != node['identity'] or len(snapshot.content) != info.st_size):
                        raise StorageError('STORE_IDENTITY_CHANGED')
                    node.update(kind='file', sha256=hashlib.sha256(snapshot.content).hexdigest(), size=info.st_size)
                    self.logical_bytes += info.st_size
                else:
                    unsafe = True  # Never open FIFO/symlink/device or count linked bytes as reclaimable.
                self.nodes[key] = node
                selected[key] = node
            finally:
                os.close(parent)
            if not self.complete:
                break
        return selected, unsafe


def _source_task(session, manifest):
    source = manifest['source_task']
    handle = resolve_archive(session, source['ref'], ReferenceOrigin(**source['origin']))
    if handle.token['member_content_digest'] != source['sha256']:
        raise StorageError('STORE_PLAN_STALE')
    document = yaml.safe_load(handle.read_bytes())
    validate(document, read_schema('task.schema.json'))
    if document['task']['id'] != source['id']:
        raise StorageError('STORE_IDENTITY_CHANGED')
    return document['state'] in {'DONE', 'ESCALATED'}


def _live_references(session):
    """Bounded current declarations, never claim closure over retained trees."""
    from harness.impact import typed_contracts
    try:
        raw = source_access.read_regular_snapshot_beneath(
            session.harness_root / 'impact.yaml', session.repo_root, max_bytes=1024 * 1024)
        contracts = typed_contracts(yaml.safe_load(raw.content)['impact'])
        if len(contracts) > 1024:
            return [], False
        paths = []
        for item in contracts:
            name = item['ref'].partition('#')[0]
            if any(mark in name for mark in ('${', '*', '?', '[')):
                return paths, False
            path = Path(name)
            if path.is_absolute():
                try:
                    path = path.relative_to(session.repo_root)
                except ValueError:
                    continue
            if path.is_relative_to(Path('.harness-store/experiments')):
                paths.append(_relative(path.as_posix()))
        return paths, True
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError):
        return [], False


def _base_report(limits):
    return {'version': 1, 'kind': 'storage_prune_preview', 'deletion_authorized': False,
            'candidates': [], 'objects': [], 'scan_complete': True, 'limits': limits,
            'logical_bytes': 0, 'physical_savings_estimate': None, 'freed_bytes': 0,
            'reference_scope': 'declared_manifest_and_current_impact_only', 'global_reference_closure': False,
            'limits_scope': 'experiment_objects', 'rebuild_identity_assurance': 'DECLARED_ONLY',
            'protected_namespaces': ['.harness', '.harness-store/operations', '.harness-store/receipts',
                                     '.harness-store/history', '.harness-store/retained', '.harness-store/quarantine']}


def classify_candidates(session, manifests: tuple[dict, ...], limits: dict) -> dict:
    """Qualify objects for review, NOT deletion. Grants for migration are irrelevant."""
    _locked(session.harness_root)
    if require_layout_admission(session.harness_root) != session.layout or session.layout.mode != 'bound':
        raise StorageError('STORE_UNOWNED')
    limits = _limits(limits)
    if not isinstance(manifests, tuple):
        raise StorageError('STORE_UNSAFE_NODE')
    report, scan = _base_report(limits), _Scan(session, limits)
    ids, paths = set(), []
    live, live_complete = _live_references(session)
    report['current_reference_scan_complete'] = live_complete
    for number, manifest in enumerate(manifests):
        if number >= limits['max_manifests']:
            scan.complete = False
            break
        try:
            validate(manifest, read_schema('storage-experiment.schema.json'))
            if (manifest['workspace_id'] != session.layout.identity['header']['workspace_id']
                    or manifest['store_id'] != session.layout.identity['header']['store_id']
                    or manifest['experiment_id'] in ids):
                raise StorageError('STORE_IDENTITY_CHANGED')
            ids.add(manifest['experiment_id'])
            for reference in manifest['must_keep']:
                name = reference['path']
                if any(mark in name for mark in ('${', '*', '?', '[')):
                    raise StorageError('STORE_REFERENCE_AMBIGUOUS')
                declared = _relative(name)
                if not declared.is_relative_to(Path('.harness-store/experiments') / manifest['experiment_id']):
                    raise StorageError('STORE_REFERENCE_AMBIGUOUS')
            selected = [_path(obj['path'], manifest['experiment_id']) for obj in manifest['objects']]
            for index, path in enumerate(selected):
                if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
                       for other in [*paths, *selected[:index]]):
                    raise StorageError('STORE_REFERENCE_AMBIGUOUS')
            paths.extend(selected)
            terminal = _source_task(session, manifest)
            for obj, path in zip(manifest['objects'], selected, strict=True):
                validate_origin(obj['origin'])
                if obj['origin'] != manifest['source_task']['origin']:
                    raise StorageError('STORE_REFERENCE_AMBIGUOUS')
                row = {'path': obj['path'], 'category': obj['category'], 'status': 'retained',
                       'origin': obj['origin'], 'original_path': obj['path'], 'identity': obj['identity'],
                       'deletion_authorized': False, 'logical_bytes': None, 'sha256': obj['sha256'],
                       'reason': 'INPUT_RESULT_OR_OPAQUE', 'known_references': []}
                report['objects'].append(row)
                try:
                    nodes, unsafe = scan.tree(path)
                    root = nodes.get(path.as_posix())
                    if not scan.complete or unsafe or root is None:
                        raise StorageError('STORE_UNSAFE_NODE')
                    digest = (root['sha256'] if obj['kind'] == 'file' else hashlib.sha256(json.dumps(
                        {str(Path(name).relative_to(path)): value for name, value in sorted(nodes.items())},
                        sort_keys=True, separators=(',', ':')).encode()).hexdigest())
                    if root['identity'] != obj['identity'] or root['kind'] != obj['kind'] or digest != obj['sha256']:
                        raise StorageError('STORE_IDENTITY_CHANGED')
                    row['logical_bytes'] = sum(node['size'] or 0 for node in nodes.values())
                    if obj['category'] == 'runtime':
                        row['reason'] = 'RUNTIME_REBUILD_OR_REFERENCE_UNQUALIFIED'
                        refs = [item for item in manifest['must_keep'] if
                                Path(item['path']) == path or Path(item['path']).is_relative_to(path)
                                or path.is_relative_to(Path(item['path']))]
                        refs.extend({'path': other.as_posix(), 'reason': 'current_impact_contract'} for other in live
                                    if other == path or other.is_relative_to(path) or path.is_relative_to(other))
                        row['known_references'] = refs
                        rebuild = obj.get('rebuild')
                        if terminal and rebuild and not refs and live_complete and manifest['reference_scope'] == 'declared_only':
                            for reference in rebuild['input_refs']:
                                resolve_archive(session, reference, ReferenceOrigin(**obj['origin'])).read_bytes()
                            row.update(status='runtime_review_only', reason='GC_AUTHORITY_NOT_IMPLEMENTED')
                except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError, ValidationError) as error:
                    row.update(status='unknown', reason=error.code if isinstance(error, StorageError) else 'STORE_UNSAFE_NODE')
        except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError, ValidationError) as error:
            report['objects'].append({'status': 'unknown', 'reason': error.code if isinstance(error, StorageError)
                                      else 'STORE_UNSAFE_NODE', 'logical_bytes': None, 'deletion_authorized': False})
    report.update(scan_complete=scan.complete, logical_bytes=scan.logical_bytes, observed_nodes=len(scan.nodes))
    return report


def preview_experiments(repo_root, *, limits=None):
    """Read bounded one-level manifests only; never adopt unmanifested directories."""
    limits = _limits(_DEFAULT_LIMITS if limits is None else limits)
    with admit_storage(Path(repo_root) / '.harness') as session:
        if session.layout.mode != 'bound':
            raise StorageError('STORE_UNOWNED')
        parent = source_access._open_beneath(session.repo_root / '.harness-store/experiments', session.repo_root)
        manifests, unknown, complete = [], [], True
        try:
            with os.scandir(parent) as children:
                for number, child in enumerate(children):
                    if number >= limits['max_manifests']:
                        complete = False
                        break
                    name = child.name
                    path = session.repo_root / '.harness-store/experiments' / name / 'manifest.yaml'
                    try:
                        if not re.fullmatch('[0-9a-f]{32}', name):
                            raise StorageError('STORE_UNOWNED')
                        raw = source_access.read_regular_snapshot_beneath(path, session.repo_root, max_bytes=1024 * 1024)
                        manifest = yaml.safe_load(raw.content)
                        if not isinstance(manifest, dict) or manifest.get('experiment_id') != name:
                            raise StorageError('STORE_IDENTITY_CHANGED')
                        manifests.append(manifest)
                    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError) as error:
                        unknown.append({'path': str(path.parent.relative_to(session.repo_root)), 'status': 'unknown',
                                        'reason': error.code if isinstance(error, StorageError) else 'STORE_UNSAFE_NODE',
                                        'deletion_authorized': False, 'logical_bytes': None})
        finally:
            os.close(parent)
        report = classify_candidates(session, tuple(manifests), limits)
        report['objects'].extend(unknown)
        report['scan_complete'] = report['scan_complete'] and complete
        return report
