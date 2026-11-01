"""Legacy prune permission never expands to a bound store."""
from storage_factory import cli, fixture_store, identity, repository
from storage_archive_factory import install_archive


def test_bound_preview_reports_canonical_objects_without_mutating(tmp_path):
    import json
    from harness.task_prune import preview

    repo = repository(tmp_path)
    fixture_store(repo)
    origin, member, _ = install_archive(repo)
    before = identity(member), member.read_bytes()
    report = preview(repo / '.harness')
    assert report['layout'] == 'bound'
    assert report['mutation_started'] is False
    assert report['deletion_authorized'] is False
    assert report['archives'][0]['origin'] == origin
    assert report['archives'][0]['archive_id'] == 'b' * 32
    assert report['archives'][0]['status'] == 'protected'
    assert (identity(member), member.read_bytes()) == before
    result = cli(repo, 'task', 'prune')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['layout'] == 'bound'


def test_bound_preview_does_not_hide_unindexed_or_special_archive_nodes(tmp_path):
    import os
    from harness.task_prune import preview

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    install_archive(repo)
    directory = store / 'history/archives'
    (directory / ('c' * 32)).mkdir()
    os.mkfifo(directory / 'never-read')
    (directory / 'never-follow').symlink_to('/not-followed')
    report = preview(repo / '.harness')
    assert {entry['name'] for entry in report.get('unknown_objects', [])} == {'c' * 32, 'never-read', 'never-follow'}
    assert report['counts']['skipped_groups'] == 3
    assert report['deletion_authorized'] is False


def test_bound_preview_reports_exact_origin_qualified_reference(tmp_path):
    import yaml
    from harness.task_prune import preview

    repo = repository(tmp_path)
    fixture_store(repo)
    origin, _, reference = install_archive(repo)
    path = repo / '.harness/impact.yaml'
    impact = yaml.safe_load(path.read_bytes())
    impact['impact']['contracts'] = [{'kind': 'generic', 'ref': reference['ref'], 'storage_origin': origin}]
    path.write_text(yaml.safe_dump(impact))
    report = preview(repo / '.harness')
    assert report['archives'][0]['references'] == [reference['ref']]
    assert report['reference_scope'] == 'current_task_declared_contracts_only'
    assert report['deletion_authorized'] is False


def test_bound_preview_reports_same_byte_member_replacement_as_unknown(tmp_path):
    from harness.task_prune import preview

    repo = repository(tmp_path)
    fixture_store(repo)
    _, member, _ = install_archive(repo)
    other = member.with_suffix('.replacement')
    other.write_bytes(member.read_bytes())
    other.replace(member)
    report = preview(repo / '.harness')
    assert report['archives'][0]['status'] == 'unknown'
    assert report['archives'][0]['reason'] == 'STORE_IDENTITY_CHANGED'
    assert report['deletion_authorized'] is False


def test_bound_destructive_history_prune_is_refused(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    result = cli(repo, "task", "prune", "--apply", "--plan-id", "task-prune-plan/v1:" + "0" * 64)
    assert result.returncode != 0
    assert "STORE_" in result.stdout + result.stderr
