"""Bound task candidate/archive construction; lifecycle remains in journal.py."""
from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import stat
from uuid import uuid4

import yaml
from jsonschema import validate

from harness import source_access, workspace
from harness._scope_replay import _genesis_artifacts, encode, load_scope
from harness.schema_resources import read_schema
from harness.task_identity import require_available
from harness.templates import templates_dir
from .archive import load_history
from .journal import DirectoryOperation, _resources, prepare_turnover
from .layout import CAPABILITY, StorageError, admit_storage
from .migration import _action, _digest, _encoded, _file, reader_identity

_ARCHIVE_FILES = {
    'current-task.yaml', 'requirements.yaml', 'invariants.yaml', 'gate.yaml', 'impact.yaml',
    'observability.yaml', 'plan.yaml', 'plan-execution.yaml', 'alignment.yaml', 'alignment-freeze.yaml',
    'test-scope-baseline.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml', 'telemetry.json',
    'config.yaml', 'risk-boundaries.yaml', 'architecture.yaml',
}
_ARCHIVE_DIRS = {'findings', 'evidence', 'decisions', 'interface-contracts'}
_POLICY_FILES = {'config.yaml', 'risk-boundaries.yaml', 'architecture.yaml'}
_POLICY_DIRS = {'decisions', 'interface-contracts'}
_TEMPLATES = ('current-task.yaml', 'requirements.yaml', 'invariants.yaml', 'gate.yaml', 'impact.yaml', 'observability.yaml')
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _source_snapshot(root, *, recover=False, repo=None):
    """Finite task-owned inputs only; no history/retention/experiment expansion."""
    repo = root.parent if repo is None else repo
    history = root / 'history'
    if source_access.is_symlink(history):
        raise StorageError('STORE_UNSAFE_NODE')
    if source_access.exists(history):
        opened = source_access._open_beneath(history, repo)
        try:
            with os.scandir(opened) as entries:
                if next(entries, None) is not None:
                    raise StorageError('STORE_PLAN_STALE')  # Explicit M1 must precede turnover.
        finally:
            os.close(opened)
    files, facts, total = {}, {}, 0
    names = _ARCHIVE_FILES | _ARCHIVE_DIRS | ({'behavior-fixtures'} if recover else set())
    pending = [(root / name).relative_to(repo) for name in sorted(names)]
    device = root.stat().st_dev
    while pending:
        relative = pending.pop()
        parent = source_access._open_beneath(repo / relative.parent, repo)
        try:
            try:
                info = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if info.st_dev != device or len(facts) >= 4096:
                raise StorageError('STORE_UNSAFE_NODE')
            key = '.harness/' + (repo / relative).relative_to(root).as_posix()
            fact = {'identity': [info.st_dev, info.st_ino], 'size': info.st_size}
            if stat.S_ISDIR(info.st_mode):
                fact['kind'] = 'directory'
                opened = os.open(relative.name, _FLAGS, dir_fd=parent)
                try:
                    held = os.fstat(opened)
                    if [held.st_dev, held.st_ino] != fact['identity']:
                        raise StorageError('STORE_PLAN_STALE')
                    with os.scandir(opened) as children:
                        for child in children:
                            if len(pending) + len(facts) >= 4096:
                                raise StorageError('STORE_UNSAFE_NODE')
                            pending.append(relative / child.name)
                finally:
                    os.close(opened)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if info.st_size > 4 * 1024 * 1024 or total > 64 * 1024 * 1024:
                    raise StorageError('STORE_UNSAFE_NODE')
                data = source_access.read_regular_snapshot_beneath(repo / relative, repo, max_bytes=4 * 1024 * 1024)
                if [data.device, data.inode] != fact['identity']:
                    raise StorageError('STORE_PLAN_STALE')
                fact.update(kind='file', sha256=hashlib.sha256(data.content).hexdigest())
                files[key] = data.content
            else:
                raise StorageError('STORE_UNSAFE_NODE')
            facts[key] = fact
        finally:
            os.close(parent)
    return dict(sorted(facts.items())), files


def _write(path, content):
    action = _action('write', path)
    action['content'] = base64.b64encode(content).decode()
    return action


def _copy(source, target, facts):
    fact = facts[source]
    return _action('copy', target, source=source, identity=fact['identity'], sha256=fact['sha256'])


def _policy(session, plan_digest):
    header, binding = session.layout.identity['header'], session.layout.identity['binding']
    activation_id = header.get('activation_operation_id')
    current_id = binding.get('operation_id')
    if not activation_id or not current_id:
        raise StorageError('STORE_READER_UNSUPPORTED')
    with _resources() as resources:
        _, path, _, document, _, state, _ = DirectoryOperation(session.repo_root, activation_id)._load(resources)
        if (path.name != 'descriptor.json' or state.phase != 'COMMITTED' or document['kind'] != 'storage_activation'
                or document['plan']['store_id'] != header['store_id']
                or document['plan']['workspace_id'] != header['workspace_id']):
            raise StorageError('STORE_IDENTITY_CHANGED')
        original = document['authority']
        receipt_digest = _digest(document)
    with _resources() as resources:
        _, path, _, current, _, state, _ = DirectoryOperation(session.repo_root, current_id)._load(resources)
        if (path.name != 'descriptor.json' or state.phase != 'COMMITTED'
                or current['plan']['candidate_generation_id'] != binding['generation_id']
                or current['plan']['store_id'] != header['store_id']):
            raise StorageError('STORE_IDENTITY_CHANGED')
        expected_root = (current['root_identity'] if current['kind'] == 'storage_activation'
                         else state.objects.get('.harness', {}).get('identity'))
        if expected_root != binding['root_identity']:
            raise StorageError('STORE_IDENTITY_CHANGED')
    return {'version': 1, 'decision_id': original['decision_id'], 'plan_digest': plan_digest,
            'grant_digest': original['grant_digest'], 'maintenance_digest': original['maintenance_digest'],
            'turnover_policy': {'activation_operation_id': activation_id,
                                'activation_descriptor_digest': receipt_digest, 'binding_digest': _digest(binding)}}


def render_candidate_binding(document, state, action):
    plan = document['plan']
    candidate = plan['turnover']['candidate_path']
    if (plan['operation'] != 'TURNOVER' or candidate != f'.harness-store/retained/roots/{plan["operation_id"]}/candidate'
            or action['target'] != candidate + '/storage-binding.yaml'):
        raise StorageError('STORE_IDENTITY_CHANGED')
    node = state.objects.get(candidate)
    if node is None or node['kind'] != 'directory':
        raise StorageError('STORE_IDENTITY_CHANGED')
    result = {'version': 1, 'kind': 'binding', 'store_id': plan['store_id'], 'workspace_id': plan['workspace_id'],
              'generation_id': plan['candidate_generation_id'], 'root_identity': node['identity'],
              'store_identity': document['store_identity'], 'capabilities': [CAPABILITY],
              'operation_id': plan['operation_id'], 'task_id': plan['turnover']['task_id']}
    validate(result, read_schema('storage-layout.schema.json'))
    return _encoded(result)


def _candidate_documents(root, task_id, title, head, architecture_mode):
    templates, identities = {}, {}
    directory = templates_dir()
    for name in _TEMPLATES:
        path = directory / name
        data = source_access.read_regular_snapshot_beneath(path, directory, max_bytes=1024 * 1024)
        templates[name] = data.content
        identities[name] = {'identity': [data.device, data.inode], 'sha256': hashlib.sha256(data.content).hexdigest()}
    task = yaml.safe_load(templates['current-task.yaml'])
    task['task']['id'], task['task']['title'] = task_id, title
    task['timestamps']['created_at'] = datetime.now(UTC).isoformat()
    task['git'] = workspace.git_baseline(head, root.parent)
    templates['current-task.yaml'] = encode(task)
    gate = yaml.safe_load(templates['gate.yaml'])
    gate['gate']['architecture'] = {'mode': architecture_mode}
    gate['gate']['storage_layout'] = {'version': 1, 'required_capabilities': [CAPABILITY]}
    impact = yaml.safe_load(templates['impact.yaml'])
    if impact['impact']['required_tests']:
        raise StorageError('STORE_READER_UNSUPPORTED')  # No undeclared template test-path authority.
    for artifact in _genesis_artifacts(task, templates['current-task.yaml'], templates['impact.yaml'], gate, []):
        templates[artifact.relative_path] = artifact.content
    return templates, identities


def _build(session, old, task_id, title, kind, head, architecture_mode, reason):
    root, repo = session.harness_root, session.repo_root
    facts, files = _source_snapshot(root, recover=kind == 'RECOVER')
    if yaml.safe_load(files['.harness/current-task.yaml']) != old:
        raise StorageError('STORE_PLAN_STALE')
    documents, template_sources = _candidate_documents(root, task_id, title, head, architecture_mode)
    index = load_history(root)
    index_data = _file(repo / '.harness-store/history/index.yaml', repo)
    operation_id, generation, archive_id = uuid4().hex, uuid4().hex, uuid4().hex
    slot = '.harness-store/retained/roots/' + operation_id
    candidate = slot + '/candidate'
    archive = '.harness-store/history/archives/' + archive_id
    alias = old['task']['id'] + '-' + operation_id
    header, binding = session.layout.identity['header'], session.layout.identity['binding']
    origin = {'workspace_id': header['workspace_id'], 'generation_id': binding['generation_id'],
              'original_workspace_root': str(repo)}
    reserved = sorted(set(index['reserved_task_ids']) | {task_id, old['task']['id']})
    reservation = {'version': 1, 'kind': 'storage_reservation', 'operation_id': operation_id,
                   'workspace_id': header['workspace_id'], 'store_id': header['store_id'], 'task_ids': reserved}
    actions = [_action('reserve_ids', f'.harness-store/history/reservations/{operation_id}.json', content=reservation),
               _action('mkdir', slot), _action('mkdir', archive), _action('mkdir', candidate)]
    dirs = {'.harness/decisions', '.harness/interface-contracts', '.harness/findings', '.harness/evidence'}
    dirs.update(name for name, fact in facts.items() if fact['kind'] == 'directory')
    for name in sorted(dirs, key=lambda value: (len(Path(value).parts), value)):
        relative = Path(name).relative_to('.harness').as_posix()
        actions.append(_action('mkdir', archive + '/' + relative))
    for name, fact in facts.items():
        if fact['kind'] == 'file':
            actions.append(_copy(name, archive + '/' + str(Path(name).relative_to('.harness')), facts))
    members = sorted(str(Path(name).relative_to('.harness')) for name, fact in facts.items() if fact['kind'] == 'file')
    if kind == 'RECOVER':
        audit = encode({'recovered_at': datetime.now(UTC).isoformat(), 'reason': reason,
                        'previous_task_id': old['task']['id'], 'previous_state': old['state'], 'replacement_task_id': task_id})
        actions.append(_write(archive + '/recovery.yaml', audit))
        members.append('recovery.yaml')
    blueprint = {'archive_id': archive_id, 'task_id': old['task']['id'], 'origin': origin,
                 'source_snapshot': {'operation_id': operation_id, 'source_identity': binding['root_identity'],
                                     'manifest_digest': _digest(facts)}, 'members': members}
    actions.append(_action('archive_descriptor', archive + '/archive.yaml', content=blueprint))
    candidate_dirs = {'decisions', 'interface-contracts', 'findings', 'evidence', 'history', '.transactions'}
    inherited_dirs = _POLICY_DIRS | ({'behavior-fixtures'} if kind == 'RECOVER' else set())
    for name, fact in facts.items():
        relative = Path(name).relative_to('.harness')
        if fact['kind'] == 'directory' and relative.parts[0] in inherited_dirs:
            candidate_dirs.add(relative.as_posix())
    for directory_name in sorted(candidate_dirs, key=lambda value: (len(Path(value).parts), value)):
        actions.append(_action('mkdir', candidate + '/' + directory_name))
    for name, data in documents.items():
        actions.append(_write(candidate + '/' + name, data))
    for name, fact in facts.items():
        relative = Path(name).relative_to('.harness')
        if fact['kind'] == 'file' and (relative.parts[0] in inherited_dirs or relative.as_posix() in _POLICY_FILES):
            actions.append(_copy(name, candidate + '/' + relative.as_posix(), facts))
    if '.harness/decisions/index.yaml' not in facts:
        actions.append(_write(candidate + '/decisions/index.yaml', b'decisions: []\n'))
    actions.append(_action('candidate_binding', candidate + '/storage-binding.yaml', content={}))
    overlay = {'base': index, 'base_sha256': hashlib.sha256(index_data.content).hexdigest(),
               'archives': [{'path': archive, 'aliases': [alias]}], 'reserve_ids': reserved}
    actions.extend([_action('history_overlay', slot + '/index-candidate.yaml', content=overlay),
                    _action('move', slot + '/previous', source='.harness', identity=binding['root_identity']),
                    _action('move', '.harness', source=candidate),
                    _action('move', slot + '/index-before.yaml', source='.harness-store/history/index.yaml',
                            identity=[index_data.device, index_data.inode], sha256=hashlib.sha256(index_data.content).hexdigest()),
                    _action('move', '.harness-store/history/index.yaml', source=slot + '/index-candidate.yaml')])
    source_files = {}
    for name in ('current-task.yaml', 'gate.yaml', 'storage-binding.yaml'):
        data = _file(root / name, repo)
        source_files[name] = {'identity': [data.device, data.inode], 'sha256': hashlib.sha256(data.content).hexdigest()}
    data = _file(repo / '.harness-store/store.yaml', repo)
    source_files['store.yaml'] = {'identity': [data.device, data.inode], 'sha256': hashlib.sha256(data.content).hexdigest()}
    product = workspace.snapshot(repo)
    plan = {'version': 1, 'kind': 'storage_plan', 'operation': 'TURNOVER', 'operation_id': operation_id,
            'workspace_root': str(repo), 'workspace_id': header['workspace_id'], 'store_id': header['store_id'],
            'old_generation_id': binding['generation_id'], 'candidate_generation_id': generation,
            'task_id': old['task']['id'], 'head': head, 'scope_digest': _digest({'facts': facts, 'templates': template_sources}),
            'manifest_digest': _digest(facts), 'actions': actions, 'ready': True,
            'turnover': {'kind': kind, 'task_id': task_id, 'candidate_path': candidate, 'archive_id': archive_id,
                         'template_sources': template_sources},
            'qualification': {'workspace_identity': header['workspace_identity'], 'root_identity': binding['root_identity'],
                              'product_fingerprint': product.fingerprint, 'sources': source_files, 'entries': facts,
                              'logical_bytes': sum(fact['size'] for fact in facts.values() if fact['kind'] == 'file'),
                              'scan_complete': True, 'unsafe_nodes': False, 'blocked_reasons': [], 'reader': reader_identity()}}
    plan['plan_digest'] = _digest(plan)
    return plan


def _require_templates(plan):
    try:
        directory = templates_dir()
        for name, expected in plan['turnover']['template_sources'].items():
            data = source_access.read_regular_snapshot_beneath(directory / name, directory, max_bytes=1024 * 1024)
            actual = {'identity': [data.device, data.inode], 'sha256': hashlib.sha256(data.content).hexdigest()}
            if actual != expected:
                raise StorageError('STORE_PLAN_STALE')
    except OSError as error:
        raise StorageError('STORE_PLAN_STALE') from error


def _validate_installed(root, plan):
    task = yaml.safe_load(_file(root / 'current-task.yaml', root.parent).content)
    binding = yaml.safe_load(_file(root / 'storage-binding.yaml', root.parent).content)
    validate(task, read_schema('task.schema.json'))
    validate(binding, read_schema('storage-layout.schema.json'))
    if (task['task']['id'] != plan['turnover']['task_id'] or task['state'] != 'CREATED'
            or binding['generation_id'] != plan['candidate_generation_id']
            or binding['operation_id'] != plan['operation_id'] or binding['task_id'] != task['task']['id']
            or binding['root_identity'] != source_access.node_identity_beneath(root, root.parent, node_kind='directory')['identity']):
        raise StorageError('STORE_IDENTITY_CHANGED')
    load_scope(root)


def replace_bound_task(root, old, task_id, title, kind, head, architecture_mode, reason=''):
    root = Path(root).absolute()
    with admit_storage(root) as session:
        require_available(root, task_id, old)
        plan = _build(session, old, task_id, title, kind, head, architecture_mode, reason)
        authority = _policy(session, plan['plan_digest'])
        _require_templates(plan)
        operation = prepare_turnover(session, {'plan': plan, 'authority': authority})
        for action in plan['actions']:
            if workspace.git_head(root.parent) != head or reader_identity() != plan['qualification']['reader']:
                raise StorageError('STORE_PLAN_STALE')
            operation.advance(action)
        _validate_installed(root, plan)
        previous = root.parent / f'.harness-store/retained/roots/{plan["operation_id"]}/previous'
        facts, _ = _source_snapshot(previous, recover=kind == 'RECOVER', repo=root.parent)
        if facts != plan['qualification']['entries']:
            raise StorageError('STORE_PLAN_STALE')
        _require_templates(plan)
        closing = workspace._storage_operation_snapshot(operation)
        if closing.head != head or closing.fingerprint != plan['qualification']['product_fingerprint']:
            raise StorageError('STORE_PLAN_STALE')
        return operation.commit()
