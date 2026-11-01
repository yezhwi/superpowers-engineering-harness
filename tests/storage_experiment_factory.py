"""Synthetic declared experiment objects, never production manifests."""
import hashlib
import json
import yaml
from storage_archive_factory import encoded, install_archive
from storage_factory import identity


def directory_experiment(repo, depth=55):
    manifest, obj, path = experiment(repo)
    obj.unlink()
    obj.mkdir()
    parent = obj
    for _ in range(depth):
        parent = parent / 'd'
        parent.mkdir()
    (parent / 'binary').write_bytes(b'fixture')
    nodes = {}
    for member in [obj, *obj.rglob('*')]:
        directory = member.is_dir()
        nodes[member.relative_to(obj).as_posix()] = {
            'identity': identity(member), 'kind': 'directory' if directory else 'file',
            'sha256': None if directory else hashlib.sha256(member.read_bytes()).hexdigest(),
            'size': None if directory else member.stat().st_size}
    manifest['objects'][0].update(kind='directory', identity=identity(obj), sha256=hashlib.sha256(encoded(nodes)).hexdigest())
    path.write_text(yaml.safe_dump(manifest))
    return manifest, obj, path


def experiment(repo, *, category='runtime', experiment_id='d' * 32, content=b'fake binary', task_state='DONE'):
    origin, member, reference = install_archive(repo)
    task = member.parent / 'current-task.yaml'
    document = yaml.safe_load((repo / '.harness/current-task.yaml').read_bytes())
    document['task']['id'], document['state'] = 'TASK-7', task_state
    task.write_text(yaml.safe_dump(document))
    descriptor_path = member.parent / 'archive.yaml'
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor['members'][task.name].update(size=task.stat().st_size, sha256=hashlib.sha256(task.read_bytes()).hexdigest())
    descriptor_path.write_bytes(encoded(descriptor))
    index_path = repo / '.harness-store/history/index.yaml'
    index = json.loads(index_path.read_bytes())
    index['archives']['b' * 32]['descriptor_sha256'] = hashlib.sha256(descriptor_path.read_bytes()).hexdigest()
    index_path.write_bytes(encoded(index))
    root = repo / '.harness-store/experiments' / experiment_id
    root.mkdir(mode=0o700)
    obj = root / 'venv'
    obj.write_bytes(content)
    manifest = {'version': 1, 'kind': 'storage_experiment', 'experiment_id': experiment_id,
                'workspace_id': '2' * 32, 'store_id': '1' * 32,
                'source_task': {'id': 'TASK-7', 'ref': reference['ref'].replace('requirements.yaml', 'current-task.yaml'),
                                'origin': origin, 'sha256': hashlib.sha256(task.read_bytes()).hexdigest()},
                'tool_identity': 'a' * 64, 'environment_identity': 'c' * 64,
                'reference_scope': 'declared_only', 'must_keep': [],
                'objects': [{'path': obj.relative_to(repo).as_posix(), 'category': category,
                             'kind': 'file', 'identity': identity(obj), 'sha256': hashlib.sha256(content).hexdigest(),
                             'origin': origin, 'rebuild': {'command': 'fixture-tool rebuild --offline',
                                                         'input_refs': [reference['ref']]}}]}
    path = root / 'manifest.yaml'
    path.write_text(yaml.safe_dump(manifest))
    return manifest, obj, path
