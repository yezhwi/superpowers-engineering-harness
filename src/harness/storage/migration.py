"""Read-only migration inventory and exact selected-user authorization.

No directory apply is enabled until the activation/turnover consumer set is
qualified together. Planning never installs a store or creates a Decision.
"""
import base64
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import stat
from uuid import uuid4

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.decision import DecisionError, load_decision, load_decision_index
from harness.schema_resources import read_schema
from harness.workspace import WorkspaceError, snapshot
from .layout import CAPABILITY, StorageError, admit_storage

@dataclass(frozen=True)
class StorageRequest:
    kind: str
    max_nodes: int = 8192
    max_bytes: int = 64 * 1024 * 1024
    sources: tuple[dict, ...] = ()


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _identity(path, repo):
    return source_access.node_identity_beneath(path, repo, node_kind="directory")["identity"]


def _file(path, repo):
    return source_access.read_regular_snapshot_beneath(path, repo, max_bytes=16 * 1024 * 1024)


def _inventory(repo, request):
    """Canonical M1 history, or explicitly selected M2 objects only."""
    if request.kind == 'M2':
        return _m2_inventory(repo, request)
    return _inventory_tree(repo, request, '.harness/history')


def _inventory_tree(repo, request, relative):
    entries, total, complete, unsafe = {}, 0, True, False
    root = repo / relative
    if not source_access.exists(root) and not source_access.is_symlink(root):
        return entries, total, complete, unsafe
    descriptor = source_access._open_beneath(root, repo)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise StorageError("STORE_UNSAFE_NODE")
        root_identity = [info.st_dev, info.st_ino]
        entries[relative] = {"identity": root_identity, "kind": "directory", "size": info.st_size}
        if info.st_dev != _identity(repo, repo)[0]:
            return entries, total, False, True
    finally:
        os.close(descriptor)
    pending = [(relative, root_identity)]
    while pending:
        prefix, expected = pending.pop()
        directory = source_access._open_beneath(repo / prefix, repo)
        try:
            held = os.fstat(directory)
            if [held.st_dev, held.st_ino] != expected or held.st_dev != root_identity[0]:
                raise StorageError("STORE_PLAN_STALE")
            # Bound membership allocation too; never list an unbounded tree.
            with os.scandir(directory) as children:
                for child in children:
                    if len(entries) >= request.max_nodes:
                        complete = False
                        break
                    name = prefix + "/" + child.name
                    info = os.stat(child.name, dir_fd=directory, follow_symlinks=False)
                    entry = {"identity": [info.st_dev, info.st_ino], "size": info.st_size}
                    entries[name] = entry
                    if stat.S_ISDIR(info.st_mode):
                        entry["kind"] = "directory"
                        if info.st_dev != os.fstat(directory).st_dev:
                            unsafe = True
                            continue
                        pending.append((name, entry["identity"]))
                    elif stat.S_ISREG(info.st_mode):
                        entry["kind"] = "file"
                        total += info.st_size
                        if info.st_nlink != 1:
                            unsafe = True
                        if total > request.max_bytes or info.st_size > 16 * 1024 * 1024:
                            complete = False
                            break
                        data = _file(repo / name, repo)
                        if [data.device, data.inode] != entry["identity"]:
                            raise StorageError("STORE_PLAN_STALE")
                        entry["sha256"] = hashlib.sha256(data.content).hexdigest()
                    else:
                        entry["kind"] = "opaque"
                        unsafe = True  # No FIFO/device read, symlink traversal or adoption.
        finally:
            os.close(directory)
        if not complete:
            break
    return dict(sorted(entries.items())), total, complete, unsafe


def _m2_selections(request, operation_id):
    from .archive import validate_origin
    from .journal import _relative

    if not isinstance(request.sources, tuple) or not 0 < len(request.sources) <= 64:
        raise StorageError('STORE_UNSAFE_NODE')
    selections, paths = [], []
    for item in request.sources:
        required = {'source', 'role', 'origin', 'logical_path'}
        if (not isinstance(item, dict) or not required <= set(item) or set(item) - required - {'alias'}
                or item['role'] not in {'retained_root', 'history', 'experiment'}):
            raise StorageError('STORE_UNSAFE_NODE')
        path = _relative(item['source'])
        logical = _relative(item['logical_path'])
        if (len(path.parts) < 3 or path.parts[:2] not in {
                ('.harness', '.publication-retained'), ('.harness', '.staging'),
                ('.harness', 'history'), ('.harness', 'experiments')}
                or not logical.parts or logical.parts[0] != '.harness'
                or any(path == old or path.is_relative_to(old) or old.is_relative_to(path) for old in paths)):
            raise StorageError('STORE_UNSAFE_NODE')
        validate_origin(item['origin'])
        alias = item.get('alias')
        if isinstance(alias, str):
            _relative(alias)
        if ((item['role'] == 'history' and (not isinstance(alias, str) or not alias or '/' in alias or '\\' in alias))
                or (item['role'] != 'history' and alias is not None)):
            raise StorageError('STORE_REFERENCE_AMBIGUOUS')
        object_id = _digest({'operation_id': operation_id, 'source': item['source']})[:32]
        target = ('.harness-store/history/archives/' + object_id if item['role'] == 'history' else
                  '.harness-store/experiments/' + object_id if item['role'] == 'experiment' else
                  f'.harness-store/retained/roots/{operation_id}/object-{object_id}')
        selections.append({**deepcopy(item), 'object_id': object_id, 'target': target})
        paths.append(path)
    return selections


def _m2_inventory(repo, request):
    entries, total, complete, unsafe = {}, 0, True, False
    for item in _m2_selections(request, '0' * 32):
        path = repo / item['source']
        identity = _identity(path, repo)  # Open directory only; never FIFO or symlink.
        if identity[0] != _identity(repo, repo)[0]:
            raise StorageError('STORE_UNSAFE_NODE')
        if item['role'] == 'history':
            facts, size, done, special = _inventory_tree(repo, request, item['source'])
            entries.update(facts)
            total += size
            complete, unsafe = complete and done, unsafe or special
        else:
            # Containing legacy package is opaque: moving it is NOT fixture recovery.
            entries[item['source']] = {'identity': identity, 'kind': 'directory'}
        if len(entries) > request.max_nodes or total > request.max_bytes:
            complete = False
            break
    return dict(sorted(entries.items())), total, complete, unsafe


def plan_operation(repo_root, request):
    try:
        return _plan_operation(repo_root, request)
    except StorageError:
        raise
    except WorkspaceError as error:
        raise StorageError("STORE_PLAN_STALE") from error
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError) as error:
        raise StorageError("STORE_UNSAFE_NODE") from error


def _plan_operation(repo_root, request):
    repo = Path(repo_root).absolute()
    if (not isinstance(request, StorageRequest) or request.kind not in {"ACTIVATE", "M1", "M2"}
            or type(request.max_nodes) is not int or not 0 < request.max_nodes <= 100000
            or type(request.max_bytes) is not int or not 0 < request.max_bytes <= 1024 * 1024 * 1024):
        raise StorageError("STORE_UNSAFE_NODE")
    with admit_storage(repo / ".harness") as session:
        if (request.kind == "ACTIVATE") != (session.layout.mode == "legacy"):
            raise StorageError("STORE_PLAN_STALE")
        task = yaml.safe_load(_file(repo / ".harness/current-task.yaml", repo).content)
        task_body = task.get('task') if isinstance(task, dict) else None
        if not isinstance(task_body, dict):
            raise StorageError('STORE_UNSAFE_NODE')
        task_id = task_body.get('id')
        current = snapshot(repo)
        entries, logical_bytes, complete, unsafe = _inventory(repo, request)
        source_facts = {}
        names = ['current-task.yaml', 'gate.yaml']
        if session.layout.mode == 'bound':
            names.extend(['storage-binding.yaml', 'store.yaml'])
        for name in names:
            data = _file(_source_path(repo, name), repo)
            source_facts[name] = {"identity": [data.device, data.inode],
                                  "sha256": hashlib.sha256(data.content).hexdigest()}
        header = session.layout.identity["header"] if session.layout.mode == "bound" else None
        binding = session.layout.identity["binding"] if header else None
        operation_id = uuid4().hex
        result = {"version": 1, "kind": "storage_plan", "operation": request.kind,
                  "operation_id": operation_id, "workspace_root": str(repo),
                  "workspace_id": header["workspace_id"] if header else uuid4().hex,
                  "store_id": header["store_id"] if header else uuid4().hex,
                  "old_generation_id": binding["generation_id"] if binding else None,
                  "candidate_generation_id": None, "task_id": task_id, "head": current.head,
                  "scope_digest": _digest({"entries": entries, "sources": source_facts}),
                  "manifest_digest": _digest(entries), "actions": [], "ready": False,
                  "qualification": {"workspace_identity": _identity(repo, repo),
                                    "root_identity": _identity(repo / ".harness", repo),
                                    "product_fingerprint": current.fingerprint, "sources": source_facts,
                                    "entries": entries, "logical_bytes": logical_bytes,
                                    "scan_complete": complete, "unsafe_nodes": unsafe,
                                    "blocked_reasons": [],
                                    "limits": {"max_nodes": request.max_nodes, "max_bytes": request.max_bytes},
                                    "reader": reader_identity()}}
        if request.kind == 'M2':
            result['relocations'] = _m2_selections(request, operation_id)
            result['qualification']['logical_bytes_complete'] = all(
                item['role'] == 'history' for item in result['relocations'])
            if any(item['origin']['workspace_id'] != result['workspace_id'] for item in result['relocations']):
                raise StorageError('STORE_REFERENCE_AMBIGUOUS')
            result['scope_digest'] = _digest({'entries': entries, 'sources': source_facts,
                                              'relocations': result['relocations']})
        if task_id is None:
            result["qualification"]["blocked_reasons"].append("STORE_READER_UNSUPPORTED")
        if not complete:
            result["qualification"]["blocked_reasons"].append("STORE_PLAN_STALE")
        if unsafe:
            result["qualification"]["blocked_reasons"].append("STORE_UNSAFE_NODE")
        if not result["qualification"]["blocked_reasons"]:
            result["candidate_generation_id"] = uuid4().hex if request.kind == "ACTIVATE" else None
            try:
                result["actions"] = _migration_actions(repo, result)
                result["ready"] = True
            except StorageError:
                raise
            except (ValueError, KeyError, TypeError, ValidationError) as error:
                raise StorageError("STORE_UNSAFE_NODE") from error
        result["plan_digest"] = _digest(result)
        _require_plan(result)
        return result


def reader_identity():
    """Actual local reader bytes/identities, not a release or writer attestation."""
    from harness.schema_resources import schema_versions

    package = Path(__file__).resolve().parents[1]
    modules = {}
    for name in ('storage/__init__.py', 'storage/layout.py', 'storage/journal.py', 'storage/archive.py',
                 'storage/migration.py', 'storage/turnover.py', 'storage/experiments.py', '_scope_replay.py', 'controlplane.py',
                 'init.py', 'templates.py', 'source_access.py', 'publication_fs.py', 'transaction_recovery.py',
                 'task_replacement.py', 'task_identity.py', 'task_prune.py', 'decision.py', 'schema_resources.py',
                 'workspace.py', 'git_query.py', 'cli.py', 'context/source.py', 'context/read_scope.py',
                 'context/freshness.py', 'context/integrity.py', 'tool_identity.py', 'preflight.py',
                 'telemetry_lock.py', 'repository.py', 'publication_journal.py'):
        path = package / name
        data = source_access.read_regular_snapshot_beneath(path, Path(path.anchor), max_bytes=1024 * 1024)
        modules[name] = {'path': str(path), 'identity': [data.device, data.inode],
                         'sha256': hashlib.sha256(data.content).hexdigest()}
    return {'version': 1, 'capability': CAPABILITY, 'schemas': schema_versions(), 'modules': modules}


def _action(kind, target, *, source=None, identity=None, sha256=None, content=None):
    return {"kind": kind, "source": source, "target": target, "identity": identity,
            "sha256": sha256, "content": None if content is None else base64.b64encode(_encoded(content)).decode()}


def _migration_actions(repo, plan):
    operation_id = plan["operation_id"]
    slot = f'.harness-store/retained/roots/{operation_id}'
    if plan["operation"] == "ACTIVATE":
        private = '.harness-store-prepare-' + operation_id
        actions = [_action('mkdir', private)]
        for name in ('operations', 'history', 'history/archives', 'history/reservations',
                     'retained', 'retained/roots', 'experiments', 'receipts', 'quarantine'):
            actions.append(_action('mkdir', private + '/' + name))
        actions.extend([
            _action('layout_metadata', private + '/store.yaml', content={'role': 'header', 'format': 2}),
            _action('layout_metadata', private + '/history/index.yaml', content={'role': 'index'}),
            _action('move', '.harness-store', source=private), _action('mkdir', slot)])
        gate = plan['qualification']['sources']['gate.yaml']
        gate_value = yaml.safe_load(_file(repo / '.harness/gate.yaml', repo).content)
        actions.extend([
            _action('move', slot + '/gate-before.yaml', source='.harness/gate.yaml',
                    identity=gate['identity'], sha256=gate['sha256']),
            _action('layout_metadata', '.harness/gate.yaml', content={'role': 'gate', 'gate': gate_value}),
            _action('layout_metadata', '.harness/storage-binding.yaml', content={'role': 'binding', 'format': 2})])
        return actions
    from .archive import load_history

    base = load_history(repo / '.harness')
    index_path = repo / '.harness-store/history/index.yaml'
    raw = _file(index_path, repo)
    plan['qualification']['index_before'] = base
    plan['qualification']['index_sha256'] = hashlib.sha256(raw.content).hexdigest()
    entries = plan['qualification']['entries']
    relocations = {item['source']: item for item in plan.get('relocations', [])}
    roots = ([(name, entries[name]) for name in relocations] if plan['operation'] == 'M2' else
             [(name, fact) for name, fact in entries.items() if Path(name).parent == Path('.harness/history')])
    additions, archive_actions, reserved = [], [], set(base['reserved_task_ids'])
    for source, fact in roots:
        if fact['kind'] != 'directory':
            raise StorageError('STORE_UNSAFE_NODE')
        selected = relocations.get(source)
        archive_id = _digest({'operation_id': operation_id, 'source': source})[:32]
        target = selected['target'] if selected else '.harness-store/history/archives/' + archive_id
        if selected and selected['role'] != 'history':
            archive_actions.append(_action('move', target, source=source, identity=fact['identity']))
            continue
        members = {str(Path(name).relative_to(source)): node for name, node in entries.items()
                   if Path(name).is_relative_to(source) and node['kind'] == 'file'}
        if 'current-task.yaml' not in members or 'archive.yaml' in members:
            raise StorageError('STORE_UNSAFE_NODE')
        task = yaml.safe_load(_file(repo / source / 'current-task.yaml', repo).content)
        task_body = task.get('task') if isinstance(task, dict) else None
        if not isinstance(task_body, dict):
            raise StorageError('STORE_UNSAFE_NODE')
        task_id = task_body.get('id')
        if not isinstance(task_id, str) or not re.fullmatch(r'TASK-[0-9]+', task_id):
            raise StorageError('STORE_UNSAFE_NODE')
        reserved.add(task_id)
        alias = selected['alias'] if selected else Path(source).name
        named = re.match(r'^(TASK-[0-9]+)(?:-|$)', alias)
        if named:
            reserved.add(named[1])
        origin = selected['origin'] if selected else {
            'workspace_id': plan['workspace_id'], 'generation_id': plan['old_generation_id'],
            'original_workspace_root': str(repo)}
        blueprint = {'archive_id': archive_id, 'task_id': task_id, 'origin': origin,
                     'source_snapshot': {'operation_id': operation_id, 'source_identity': fact['identity'],
                                         'manifest_digest': _digest(members)}, 'members': sorted(members)}
        archive_actions.extend([
            _action('move', target, source=source, identity=fact['identity']),
            _action('archive_descriptor', target + '/archive.yaml', content=blueprint)])
        additions.append({'path': target, 'aliases': [alias]})
    reservation = {'version': 1, 'kind': 'storage_reservation', 'operation_id': operation_id,
                   'workspace_id': plan['workspace_id'], 'store_id': plan['store_id'],
                   'task_ids': sorted(reserved | {plan['task_id']})}
    actions = [_action('reserve_ids', f'.harness-store/history/reservations/{operation_id}.json', content=reservation),
               _action('mkdir', slot), *archive_actions]
    overlay = {'base': base, 'base_sha256': plan['qualification']['index_sha256'],
               'archives': additions, 'reserve_ids': reservation['task_ids']}
    actions.extend([
        _action('history_overlay', slot + '/index-candidate.yaml', content=overlay),
        _action('move', slot + '/index-before.yaml', source='.harness-store/history/index.yaml',
                identity=[raw.device, raw.inode], sha256=hashlib.sha256(raw.content).hexdigest()),
        _action('move', '.harness-store/history/index.yaml', source=slot + '/index-candidate.yaml')])
    return actions


def render_layout_metadata(document, state, action):
    value = json.loads(base64.b64decode(action['content'], validate=True))
    plan = document['plan']
    role = value.get('role')
    private = '.harness-store-prepare-' + plan['operation_id']
    expected = {'header': private + '/store.yaml', 'index': private + '/history/index.yaml',
                'gate': '.harness/gate.yaml', 'binding': '.harness/storage-binding.yaml'}
    if plan['operation'] != 'ACTIVATE' or action['target'] != expected.get(role):
        raise StorageError('STORE_IDENTITY_CHANGED')
    expected_fields = {'role', 'gate'} if role == 'gate' else {'role'}
    if role in {'header', 'binding'} and 'format' in value:
        if type(value['format']) is not int or value['format'] != 2:
            raise StorageError('STORE_READER_UNSUPPORTED')
        expected_fields.add('format')
    if set(value) != expected_fields:
        raise StorageError('STORE_IDENTITY_CHANGED')
    if role == 'header':
        result = {'version': 1, 'kind': 'store', 'store_id': plan['store_id'], 'workspace_id': plan['workspace_id'],
                  'workspace_root': plan['workspace_root'], 'workspace_identity': document['repo_identity'],
                  'store_identity': state.objects[private]['identity'], 'capabilities': [CAPABILITY]}
        if value.get('format') == 2:
            result['activation_operation_id'] = plan['operation_id']
        validate(result, read_schema('storage-layout.schema.json'))
    elif role == 'binding':
        result = {'version': 1, 'kind': 'binding', 'store_id': plan['store_id'], 'workspace_id': plan['workspace_id'],
                  'generation_id': plan['candidate_generation_id'], 'root_identity': document['root_identity'],
                  'store_identity': state.objects['.harness-store']['identity'], 'capabilities': [CAPABILITY]}
        if value.get('format') == 2:
            result.update(operation_id=plan['operation_id'], task_id=plan['task_id'])
        validate(result, read_schema('storage-layout.schema.json'))
    elif role == 'index':
        result = {'version': 1, 'kind': 'storage_history', 'store_id': plan['store_id'],
                  'workspace_id': plan['workspace_id'], 'archives': {}, 'aliases': [],
                  'reserved_task_ids': [plan['task_id']]}
        validate(result, read_schema('storage-history.schema.json'))
    else:
        result = value['gate']
        validate(result, read_schema('gate.schema.json'))
        result['gate']['storage_layout'] = {'version': 1, 'required_capabilities': [CAPABILITY]}
        validate(result, read_schema('gate.schema.json'))
    return _encoded(result)


def _require_plan(plan):
    try:
        validate(plan, read_schema("storage-operation.schema.json"))
        if plan.get("kind") != "storage_plan" or plan.get("plan_digest") != _digest({
                key: value for key, value in plan.items() if key != "plan_digest"}):
            raise StorageError("STORE_PLAN_STALE")
    except (ValidationError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise StorageError("STORE_PLAN_STALE") from error


def verify_authority(harness_root, plan, decision_id, maintenance):
    """Exact accepted selected option only; strings/hashes never grant apply."""
    _require_plan(plan)
    try:
        record = load_decision(harness_root, decision_id)
        raw_record = _file(harness_root / 'decisions' / (decision_id + '.yaml'), harness_root.parent)
        raw_index = _file(harness_root / 'decisions/index.yaml', harness_root.parent)
        index_records = load_decision_index(harness_root)
        metadata = next(item for item in index_records if item['id'] == decision_id)
        if (record['id'] != decision_id or metadata['sha256'] != 'sha256:' + hashlib.sha256(raw_record.content).hexdigest()
                or any(metadata[key] != record[key] for key in ('task_id', 'status', 'supersedes', 'superseded_by'))):
            raise StorageError('STORE_AUTHORITY_REQUIRED')
        index_document = yaml.safe_load(raw_index.content)
        if (yaml.safe_load(raw_record.content) != record or not isinstance(index_document, dict)
                or index_document.get('decisions') != index_records):
            raise StorageError('STORE_AUTHORITY_REQUIRED')
        selected = record["selected"]
        option = next(item for item in record["options"] if item["id"] == selected["option"])
        expected = {"version": 1, "task_id": plan["task_id"], "workspace_id": plan["workspace_id"],
                    "store_id": None if plan["operation"] == "ACTIVATE" else plan["store_id"],
                    "operation": plan["operation"], "plan_digest": "sha256:" + plan["plan_digest"],
                    "scope_digest": "sha256:" + plan["scope_digest"]}
        current = yaml.safe_load(_file(harness_root / "current-task.yaml", harness_root.parent).content)
        if (record["status"] != "ACCEPTED" or record["superseded_by"] is not None
                or selected["decided_by"] != "user" or record["task_id"] != plan["task_id"]
                or current["task"]["id"] != plan["task_id"] or option.get("storage_authorization") != expected):
            raise StorageError("STORE_AUTHORITY_REQUIRED")
        required = {"version", "workspace_id", "operation", "plan_digest", "participants",
                    "participants_complete", "operator_confirmation"}
        if (not isinstance(maintenance, dict) or set(maintenance) != required
                or type(maintenance["version"]) is not int or maintenance["version"] != 1
                or maintenance["workspace_id"] != plan["workspace_id"]
                or maintenance["operation"] != plan["operation"]
                or maintenance["plan_digest"] != "sha256:" + plan["plan_digest"]
                or maintenance["participants_complete"] is not True
                or maintenance["operator_confirmation"] is not True
                or not isinstance(maintenance["participants"], list) or not maintenance["participants"]):
            raise StorageError("STORE_AUTHORITY_REQUIRED")
        names = set()
        for participant in maintenance["participants"]:
            if (not isinstance(participant, dict) or set(participant) != {"name", "role", "disposition", "capabilities"}
                    or not isinstance(participant["name"], str) or not participant["name"].strip()
                    or participant["name"] in names
                    or participant["role"] not in {"cli", "agent", "ci", "test", "build", "editor", "external_writer"}
                    or participant["disposition"] not in {"stopped", "upgraded"}
                    or not isinstance(participant["capabilities"], list)
                    or any(not isinstance(item, str) for item in participant["capabilities"])
                    or (participant["disposition"] == "upgraded" and CAPABILITY not in participant["capabilities"])):
                raise StorageError("STORE_AUTHORITY_REQUIRED")
            names.add(participant["name"])
        return {"version": 1, "decision_id": decision_id, "plan_digest": plan["plan_digest"],
                "grant_digest": _digest(record), "maintenance_digest": _digest(maintenance),
                "maintenance_snapshot": deepcopy(maintenance),
                "sources": {name: {'identity': [value.device, value.inode],
                                   'sha256': hashlib.sha256(value.content).hexdigest()}
                            for name, value in ((f'decisions/{decision_id}.yaml', raw_record),
                                                ('decisions/index.yaml', raw_index))}}
    except StorageError:
        raise
    except (DecisionError, OSError, ValueError, TypeError, KeyError, StopIteration) as error:
        raise StorageError("STORE_AUTHORITY_REQUIRED") from error


def apply_operation(repo_root, plan, decision_id, maintenance):
    from harness.publication_fs import PublicationUnsupported

    try:
        return _apply_operation(repo_root, plan, decision_id, maintenance)
    except StorageError:
        raise
    except PublicationUnsupported as error:
        raise StorageError('STORE_READER_UNSUPPORTED') from error
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ValidationError, yaml.YAMLError) as error:
        raise StorageError('STORE_IDENTITY_CHANGED') from error


def _apply_operation(repo_root, plan, decision_id, maintenance):
    repo = Path(repo_root).absolute()
    from .journal import prepare_activation, prepare_turnover

    with admit_storage(repo / '.harness') as session:
        authority = verify_authority(repo / '.harness', plan, decision_id, maintenance)
        existing = _existing_receipt(repo, plan, authority)
        if existing is not None:
            return existing
        _require_fresh(repo, plan)
        if not plan['ready'] or plan['operation'] not in {'ACTIVATE', 'M1', 'M2'}:
            raise StorageError('STORE_READER_UNSUPPORTED')
        operation = (prepare_activation(repo / '.harness', plan, authority) if plan['operation'] == 'ACTIVATE'
                     else prepare_turnover(session, {'plan': plan, 'authority': authority}))
        for action in plan['actions']:
            _require_reader_head(repo, plan)
            operation.advance(action)
        _require_reader_head(repo, plan)
        from harness.workspace import _storage_operation_snapshot

        closing = _storage_operation_snapshot(operation)
        if closing.head != plan['head'] or closing.fingerprint != plan['qualification']['product_fingerprint']:
            raise StorageError('STORE_PLAN_STALE')
        _require_reader_head(repo, plan)
        return operation.commit()


def _existing_receipt(repo, plan, authority):
    from .journal import DirectoryOperation, _resources

    operation_id = plan['operation_id']
    for base in ('.harness-store/receipts', '.harness/.publication-retained'):
        path = repo / base / ('storage-' + operation_id) / 'descriptor.json'
        if not source_access.is_symlink(path) and not source_access.exists(path):
            continue
        with _resources() as resources:
            _, location, _, document, _, state, frames = DirectoryOperation(repo, operation_id)._load(resources)
            if document['plan'] != plan:
                raise StorageError('STORE_PLAN_STALE')
            if ({key: value for key, value in document['authority'].items() if key != 'sources'}
                    != {key: value for key, value in authority.items() if key != 'sources'}):
                raise StorageError('STORE_AUTHORITY_REQUIRED')
            if location.name != 'descriptor.json' or state.phase not in {'COMMITTED', 'ABORTED'}:
                raise StorageError('STORE_RECOVERY_REQUIRED')
            return {'operation_id': operation_id, 'status': state.phase,
                    'receipt': (frames / 'descriptor.json').as_posix()}
    return None


def _source_path(repo, name):
    if name in {'current-task.yaml', 'gate.yaml', 'storage-binding.yaml'}:
        return repo / '.harness' / name
    if name == 'store.yaml':
        return repo / '.harness-store/store.yaml'
    raise StorageError('STORE_PLAN_STALE')


def _require_reader_head(repo, plan):
    from harness.workspace import git_head

    if (git_head(repo) != plan['head']
            or reader_identity() != plan['qualification']['reader']):
        raise StorageError('STORE_PLAN_STALE')


def _require_fresh(repo, plan):
    _require_reader_head(repo, plan)
    qualification = plan.get('qualification', {})
    current = snapshot(repo)
    if (current.head != plan['head'] or current.fingerprint != qualification['product_fingerprint']
            or _identity(repo, repo) != qualification['workspace_identity']
            or _identity(repo / '.harness', repo) != qualification['root_identity']):
        raise StorageError('STORE_PLAN_STALE')
    names = {'current-task.yaml', 'gate.yaml'}
    if plan['operation'] != 'ACTIVATE':
        names.update({'storage-binding.yaml', 'store.yaml'})
    if set(qualification['sources']) != names:
        raise StorageError('STORE_PLAN_STALE')
    limits = qualification['limits']
    selections = tuple({key: item[key] for key in ('source', 'role', 'origin', 'logical_path', 'alias') if key in item}
                       for item in plan.get('relocations', []))
    request = StorageRequest(plan['operation'], sources=selections, **limits)
    if plan['operation'] == 'M2':
        if (_m2_selections(request, plan['operation_id']) != plan['relocations']
                or qualification.get('logical_bytes_complete') is not all(
                    item['role'] == 'history' for item in plan['relocations'])):
            raise StorageError('STORE_PLAN_STALE')
    entries, _, complete, unsafe = _inventory(repo, request)
    if not complete or unsafe or entries != qualification['entries']:
        raise StorageError('STORE_PLAN_STALE')
    for name, fact in qualification['sources'].items():
        data = _file(_source_path(repo, name), repo)
        if [data.device, data.inode] != fact['identity'] or hashlib.sha256(data.content).hexdigest() != fact['sha256']:
            raise StorageError('STORE_PLAN_STALE')
    scope = {'entries': entries, 'sources': qualification['sources']}
    if plan['operation'] == 'M2':
        scope['relocations'] = plan['relocations']
    if (plan['manifest_digest'] != _digest(entries) or plan['scope_digest'] != _digest(scope)):
        raise StorageError('STORE_PLAN_STALE')
    expected = deepcopy(plan)
    if _migration_actions(repo, expected) != plan['actions'] or expected['qualification'] != qualification:
        raise StorageError('STORE_PLAN_STALE')
