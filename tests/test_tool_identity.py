"""PF-08..11: independent bounded tool facts, never package/version guesses."""
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def tools():
    return importlib.import_module('harness.tool_identity')


@pytest.fixture
def installed(tmp_path, monkeypatch):
    site = tmp_path / 'site'
    meta = site / 'superpowers_engineering_harness-0.3.2.dist-info'
    meta.mkdir(parents=True)
    (meta / 'METADATA').write_text('Metadata-Version: 2.1\nName: superpowers-engineering-harness\nVersion: 0.3.2\n')
    files = ['superpowers_engineering_harness-0.3.2.dist-info/METADATA']
    for name in ('harness', 'harness.cli', 'harness.evidence_plan', 'harness.execution_capture'):
        module = importlib.import_module(name)
        relative = 'harness/__init__.py' if name == 'harness' else name.replace('.', '/') + '.py'
        path = site / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text('# declared module\n')
        monkeypatch.setattr(module, '__file__', str(path))
        files.append(relative)
    (meta / 'RECORD').write_text(''.join(f'{name},,\n' for name in files))
    distribution = SimpleNamespace(files=[Path(name) for name in files],
                                   locate_file=lambda name: site / name,
                                   _path=meta)
    monkeypatch.setattr(importlib.metadata, 'distribution', lambda name: distribution)
    manifest = tmp_path / 'package.json'
    manifest.write_text(json.dumps({'name': 'superpowers-engineering-harness', 'version': '0.3.2'}))
    return site, meta, manifest, distribution


def test_installed_identity_exact_version_and_schema_hash(installed):
    from harness.schema_resources import schema_versions
    _, _, manifest, _ = installed
    report = tools().finish_tool_identity(tools().begin_tool_identity(manifest))
    assert report['cli_identity']['status'] == 'VERIFIED'
    assert report['cli_identity']['verified_version'] == '0.3.2'
    assert report['skills_identity']['status'] == 'MATCH'
    mapping = schema_versions()
    encoded = json.dumps(mapping, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    assert report['schema_identity']['versions'] == mapping
    assert report['schema_identity']['sha256'] == 'sha256:' + hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize('value,status', [
    ({'name': 'wrong', 'version': '0.3.2'}, 'INVALID'),
    ({'name': 'superpowers-engineering-harness'}, 'INVALID'),
    ({'name': 'superpowers-engineering-harness', 'version': ''}, 'INVALID'),
    ({'name': 'superpowers-engineering-harness', 'version': ' 0.3.2'}, 'INVALID'),
    ({'name': 'superpowers-engineering-harness', 'version': 'v0.3.2'}, 'MISMATCH'),
    ({'name': 'superpowers-engineering-harness', 'version': '0.3.1'}, 'MISMATCH'),
])
def test_manifest_predicates_are_not_version_normalization(installed, value, status):
    _, _, manifest, _ = installed
    manifest.write_text(json.dumps(value))
    report = tools().finish_tool_identity(tools().begin_tool_identity(manifest))
    assert report['skills_identity']['status'] == status


@pytest.mark.parametrize('kind,status', [('absent','NOT_PROVIDED'), ('missing','MISSING'),
                                          ('invalid_json','INVALID'), ('duplicate','INVALID'),
                                          ('symlink','INVALID'), ('oversized','INVALID')])
def test_manifest_failures_and_optional_absence(installed, tmp_path, kind, status):
    _, _, manifest, _ = installed
    if kind == 'absent':
        manifest = None
    elif kind == 'missing':
        manifest.unlink()
    elif kind == 'invalid_json':
        manifest.write_text('broken')
    elif kind == 'duplicate':
        manifest.write_text('{"name":"superpowers-engineering-harness","version":"0.3.2","version":"0.3.2"}')
    elif kind == 'symlink':
        actual = tmp_path / 'actual.json'
        manifest.rename(actual)
        manifest.symlink_to(actual)
    elif kind == 'oversized':
        manifest.write_bytes(b' ' * (16 * 1024 * 1024 + 1))
    report = tools().finish_tool_identity(tools().begin_tool_identity(manifest))
    assert report['skills_identity']['status'] == status


@pytest.mark.parametrize('kind', ['bytes', 'inode'])
def test_manifest_revalidation_rejects_changed_bytes_or_identity(installed, kind):
    _, _, manifest, _ = installed
    snapshot = tools().begin_tool_identity(manifest)
    if kind == 'bytes':
        manifest.write_text('{"name":"superpowers-engineering-harness","version":"9.9.9"}')
    else:
        data = manifest.read_bytes()
        manifest.unlink()
        manifest.write_bytes(data)
    report = tools().finish_tool_identity(snapshot)
    assert report['skills_identity']['status'] == 'CHANGED'
    assert report['skills_identity']['sha256'] is None


def test_package_not_found_is_missing_not_invalid(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata, 'distribution', missing)
    report = tools().finish_tool_identity(tools().begin_tool_identity(None))
    assert report['cli_identity']['status'] == 'MISSING'
    assert report['cli_identity']['verified_version'] is None


@pytest.mark.parametrize('kind', ['editable', 'egg_info', 'no_files', 'module_mismatch'])
def test_source_ambiguity_never_certifies_candidate_version(installed, kind):
    site, meta, manifest, distribution = installed
    if kind == 'editable':
        (meta / 'direct_url.json').write_text('{"url":"https://credential:secret@example.com","dir_info":{"editable":true}}')
    elif kind == 'egg_info':
        distribution._path = site / 'something.egg-info'
    elif kind == 'no_files':
        (meta / 'RECORD').unlink()
    else:
        distribution.locate_file = lambda name: site / 'wrong' / name
    report = tools().finish_tool_identity(tools().begin_tool_identity(manifest))
    assert report['cli_identity']['status'] == 'SOURCE_AMBIGUOUS'
    assert report['cli_identity']['verified_version'] is None
    assert report['skills_identity']['status'] == 'UNVERIFIABLE'
    assert 'credential' not in json.dumps(report)
    assert 'secret' not in json.dumps(report)


@pytest.mark.parametrize('content', [b'Name: wrong\nVersion: 0.3.2\n',
                                      b'Name: superpowers-engineering-harness\n',
                                      b'Name: superpowers-engineering-harness\nVersion: 0.3.2\nVersion: 0.3.2\n'])
def test_invalid_cli_metadata_never_has_verified_version(installed, content):
    _, meta, manifest, _ = installed
    (meta / 'METADATA').write_bytes(content)
    report = tools().finish_tool_identity(tools().begin_tool_identity(manifest))
    assert report['cli_identity']['status'] == 'INVALID'
    assert report['cli_identity']['verified_version'] is None


def test_unreadable_manifest_is_not_reported_as_invalid_json(installed, monkeypatch):
    import errno
    _, _, manifest, _ = installed
    module = tools()
    original = module.read_regular_snapshot_beneath
    def unreadable(path, *args, **kwargs):
        if path == manifest:
            raise OSError(errno.EIO, 'injected I/O failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(module, 'read_regular_snapshot_beneath', unreadable)
    report = module.finish_tool_identity(module.begin_tool_identity(manifest))
    assert report['skills_identity']['status'] == 'UNREADABLE'


@pytest.mark.parametrize('document', [
    {'dir_info': {'editable': 'true'}}, {'dir_info': {'editable': 1}},
    {'dir_info': {'editable': None}},
])
def test_malformed_editable_marker_cannot_certify_distribution(installed, document):
    _, meta, manifest, _ = installed
    (meta / 'direct_url.json').write_text(json.dumps(document))
    report = tools().finish_tool_identity(tools().begin_tool_identity(manifest))
    assert report['cli_identity']['status'] == 'INVALID'
    assert report['cli_identity']['verified_version'] is None
    assert report['skills_identity']['status'] == 'UNVERIFIABLE'


def test_invalid_schema_is_reported_without_product_loading(installed, monkeypatch):
    _, _, manifest, _ = installed
    module = tools()
    def broken(*args, **kwargs):
        raise ValueError('invalid schema JSON')
    monkeypatch.setattr(module, 'read_schema', broken)
    report = module.finish_tool_identity(module.begin_tool_identity(manifest))
    assert report['schema_identity']['status'] == 'INVALID'
    assert report['schema_identity']['versions'] is None


def test_schema_change_invalidates_tool_snapshot(installed, monkeypatch):
    _, _, manifest, _ = installed
    module = tools()
    snapshot = module.begin_tool_identity(manifest)
    original = module.schema_versions
    monkeypatch.setattr(module, 'schema_versions', lambda: {**original(), 'task.schema.json': 'sha256:' + '0' * 64})
    report = module.finish_tool_identity(snapshot)
    assert report['schema_identity']['status'] == 'CHANGED'
