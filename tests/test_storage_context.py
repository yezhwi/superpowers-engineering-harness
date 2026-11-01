"""Saved references must select origin/object, never global same-name fallback."""
import pytest
from test_context_builder import harness  # noqa: F401 -- shared pytest fixture

from storage_archive_factory import install_archive
from storage_factory import fixture_store, repository


def test_generated_context_contains_only_declared_origin_qualified_history_dependency(harness):
    import yaml

    from harness.context.integrity import build_context, validate_context

    repo = harness.parent
    fixture_store(repo)
    origin, _, reference = install_archive(repo)
    path = harness / 'impact.yaml'
    impact = yaml.safe_load(path.read_text())
    impact['impact']['contracts'] = [{'kind': 'generic', 'ref': reference['ref'], 'storage_origin': origin}]
    path.write_text(yaml.safe_dump(impact))
    document = build_context(harness)
    dependencies = [entry for entry in document['references'].values() if entry and 'storage' in entry]
    assert dependencies == [reference]
    assert document['generated_from']['archive_references'] == {'archive:' + reference['storage']['selected_alias_record_digest'] + ':requirements.yaml': reference}
    assert validate_context(harness, document)['traceability'] is True


def _declare_dependency(harness):
    import yaml

    fixture_store(harness.parent)
    origin, member, reference = install_archive(harness.parent)
    path = harness / 'impact.yaml'
    impact = yaml.safe_load(path.read_text())
    impact['impact']['contracts'] = [{'kind': 'generic', 'ref': reference['ref'], 'storage_origin': origin}]
    path.write_text(yaml.safe_dump(impact))
    return member, reference


def test_saved_context_control_dependencies_survive_unrelated_archive_append(harness):
    from harness.context.integrity import build_context, validate_context

    _declare_dependency(harness)
    document = build_context(harness)
    install_archive(harness.parent, archive_id='c' * 32, generation_id='4' * 32,
                    alias='TASK-8-other', task_id='TASK-8')
    assert validate_context(harness, document)['freshness'] is True


def test_context_archive_authority_does_not_include_other_members(harness):
    from harness.context.integrity import build_context
    from harness.context.model import ContextBuildError
    from harness.context.read_scope import context_read_scope
    from harness.source_access import read_bytes

    member, _ = _declare_dependency(harness)
    document = build_context(harness)
    with pytest.raises(ContextBuildError, match='CONTEXT_REFERENCE_BROKEN'):
        with context_read_scope(harness, document['generated_from']):
            read_bytes(member.parent / 'current-task.yaml')


def test_bound_history_contract_without_origin_is_not_silently_unversioned(harness):
    import yaml

    from harness.context.integrity import build_context
    from harness.storage import StorageError

    _, reference = _declare_dependency(harness)
    path = harness / 'impact.yaml'
    impact = yaml.safe_load(path.read_text())
    impact['impact']['contracts'] = [{'kind': 'generic', 'ref': reference['ref']}]
    path.write_text(yaml.safe_dump(impact))
    with pytest.raises(StorageError, match='STORE_REFERENCE_AMBIGUOUS'):
        build_context(harness)


@pytest.mark.parametrize('reference', ['src/security.py', '.env', '../outside', '/foreign/.harness/history/TASK-7/member.yaml'])
def test_storage_origin_cannot_hide_arbitrary_product_contract(reference):
    from harness.impact import ImpactContractError, contract_paths

    value = {'contracts': [{'kind': 'generic', 'ref': reference,
                           'storage_origin': {'workspace_id': '2' * 32, 'generation_id': '3' * 32,
                                              'original_workspace_root': '/owner'}}]}
    with pytest.raises(ImpactContractError, match='IMPACT_CONTRACT_KIND_INVALID'):
        contract_paths(value)


def test_context_resolves_explicit_committed_origin_without_old_shell_path(tmp_path):
    from harness.context.integrity import resolve_reference
    from harness.context.model import ContextBuildError
    from harness.storage import admit_storage

    repo = repository(tmp_path)
    fixture_store(repo)
    _, _, reference = install_archive(repo)
    failure = None
    with admit_storage(repo / '.harness'):
        try:
            resolve_reference(repo, reference)
        except ContextBuildError as error:
            failure = error.code
    assert failure is None, f'committed logical archive reference refused: {failure}'


def test_same_bytes_substituted_member_invalidates_saved_context(tmp_path):
    from harness.context.integrity import resolve_reference
    from harness.context.model import ContextBuildError
    from harness.storage import admit_storage

    repo = repository(tmp_path)
    fixture_store(repo)
    _, member, reference = install_archive(repo)
    raw = member.read_bytes()
    member.rename(member.with_name('parked.yaml'))
    member.write_bytes(raw)
    with admit_storage(repo / '.harness'), pytest.raises(ContextBuildError):
        resolve_reference(repo, reference)


def _archive_scope_paths(repo, member):
    from harness.storage.layout import observation_paths

    return [repo, repo / '.harness', *observation_paths(repo / '.harness'),
            repo / '.harness-store/history/index.yaml', member.parent,
            member.parent / 'archive.yaml', member]


def test_scoped_reference_observes_selected_alias_not_whole_appending_index(tmp_path):
    import os
    import subprocess
    import sys

    from harness.source_access import source_scope
    from harness.storage import ReferenceOrigin, admit_storage, resolve_archive
    from storage_factory import ROOT

    repo = repository(tmp_path)
    fixture_store(repo)
    origin, member, _ = install_archive(repo)
    with admit_storage(repo / '.harness') as session:
        with source_scope(repo, allowed=_archive_scope_paths(repo, member)):
            handle = resolve_archive(session, 'history/TASK-7-snapshot/requirements.yaml', ReferenceOrigin(**origin))
            subprocess.run([sys.executable, '-B', '-c',
                            'from pathlib import Path; from storage_archive_factory import install_archive; '
                            'install_archive(Path.cwd(),archive_id="c"*32,generation_id="4"*32,alias="other",task_id="TASK-8")'],
                           cwd=repo, env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                           check=True, timeout=10)
            assert handle.read_bytes() == b'requirements: []\n'


def test_scope_exit_detects_equal_byte_inode_swap_after_archive_read(tmp_path):
    import os
    import subprocess
    import sys

    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope
    from harness.storage import ReferenceOrigin, admit_storage, resolve_archive
    from storage_factory import ROOT

    repo = repository(tmp_path)
    fixture_store(repo)
    origin, member, _ = install_archive(repo)
    with admit_storage(repo / '.harness') as session:
        with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
            with source_scope(repo, allowed=_archive_scope_paths(repo, member)):
                handle = resolve_archive(session, 'history/TASK-7-snapshot/requirements.yaml', ReferenceOrigin(**origin))
                assert handle.read_bytes() == b'requirements: []\n'
                subprocess.run([sys.executable, '-B', '-c',
                                'from pathlib import Path; import sys; p=Path(sys.argv[1]); '
                                'raw=p.read_bytes(); p.rename(p.with_name("parked")); p.write_bytes(raw)', str(member)],
                               cwd=repo, env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                               check=True, timeout=10)


def test_unrelated_archive_append_keeps_selected_saved_reference_valid(tmp_path):
    from harness.context.integrity import resolve_reference
    from harness.storage import admit_storage

    repo = repository(tmp_path)
    fixture_store(repo)
    _, _, reference = install_archive(repo)
    install_archive(repo, archive_id='c' * 32, generation_id='4' * 32,
                    alias='TASK-8-other', task_id='TASK-8')
    with admit_storage(repo / '.harness'):
        resolve_reference(repo, reference)
