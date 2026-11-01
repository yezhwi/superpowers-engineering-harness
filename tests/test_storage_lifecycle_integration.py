"""Legacy storage diagnosis is read-only and does not implicitly initialize a store."""
import json
import os
import subprocess
import sys
import yaml
from test_context_builder import harness  # noqa: F401
from storage_factory import ROOT, cli, identity, repository


def apply_cli(root, plan):
    from test_storage_activation import qualified_grant
    from test_storage_cli import fixture_inputs
    decision, maintenance = qualified_grant(root, plan)
    plan_path, maintenance_path = fixture_inputs(root, plan, maintenance)
    result = cli(root.parent, 'storage', 'migrate', '--apply', '--file', str(plan_path),
                 '--decision', decision, '--maintenance-file', str(maintenance_path), '--json', timeout=90)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'COMMITTED'


def test_joint_cli_lifecycle_keeps_original_reference_through_turnover_and_kill(harness):
    from harness.storage import ReferenceOrigin, admit_storage, resolve_archive
    from harness.context.integrity import build_context, validate_context
    from test_storage_turnover_recovery import _SCRIPT

    repo = harness.parent
    assert json.loads(cli(repo, 'storage', 'inspect', '--json').stdout)['mode'] == 'legacy'
    old = harness / 'history/TASK-007-prior'
    old.mkdir(parents=True)
    (old / 'current-task.yaml').write_text('task:\n  id: TASK-007\n')
    member = old / 'proof.yaml'
    member.write_bytes(b'requirements: []\n')
    original = identity(old), identity(member), member.read_bytes()
    proposed = cli(repo, 'storage', 'migrate', '--kind', 'ACTIVATE', '--dry-run', '--json')
    assert proposed.returncode == 0, proposed.stderr
    apply_cli(harness, json.loads(proposed.stdout))
    migrated = cli(repo, 'storage', 'migrate', '--kind', 'M1', '--json')
    assert migrated.returncode == 0, migrated.stderr
    plan = json.loads(migrated.stdout)
    apply_cli(harness, plan)
    origin = ReferenceOrigin(plan['workspace_id'], plan['old_generation_id'], str(repo))
    reference = 'history/TASK-007-prior/proof.yaml'
    with admit_storage(harness) as session:
        handle = resolve_archive(session, reference, origin)
        token = handle.token
        assert handle.read_bytes() == original[2]
        assert token['member_identity'] == original[1]
    task_path = harness / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_bytes())
    task['state'] = 'DONE'  # Fixture input only, never implementation acceptance.
    task_path.write_text(yaml.safe_dump(task))
    new = cli(repo, 'task', 'new', 'TASK-101', timeout=90)
    assert new.returncode == 0, new.stderr
    classified = cli(repo, 'task', 'classify', '--level', 'Q1', '--scope', 'low', '--contract', 'none',
                     '--data', 'none', '--authorization', 'none', '--security', 'none',
                     '--concurrency', 'none', '--deployment', 'none')
    assert classified.returncode == 0, classified.stderr
    impact_path = harness / 'impact.yaml'
    impact = yaml.safe_load(impact_path.read_bytes())
    impact['impact']['contracts'] = [{'kind': 'generic', 'ref': reference,
                                    'storage_origin': token['origin']}]
    impact_path.write_text(yaml.safe_dump(impact))
    context = build_context(harness)
    assert validate_context(harness, context)['traceability'] is True
    root_before = identity(harness)
    killed = subprocess.run([sys.executable, '-B', '-c', _SCRIPT, 'old-root'], cwd=repo,
                            env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                            capture_output=True, text=True, timeout=100)
    assert killed.returncode == 87, killed.stderr
    assert not harness.exists()
    assert cli(repo, 'init').returncode == 2
    pending = next((repo / '.harness-store/operations').iterdir())
    operation_id = json.loads(pending.read_bytes())['plan']['operation_id']
    recovered = cli(repo, 'storage', 'recover', operation_id, timeout=90)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)['status'] == 'ABORTED'
    assert identity(harness) == root_before
    with admit_storage(harness) as session:
        handle = resolve_archive(session, reference, origin)
        assert handle.token == token
        assert handle.read_bytes() == original[2]
    assert validate_context(harness, build_context(harness))['freshness'] is True
    report = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert report.returncode == 0, report.stderr
    assert json.loads(report.stdout)['deletion_authorized'] is False
    refused = cli(repo, 'task', 'prune', '--apply', '--plan-id', 'task-prune-plan/v1:' + '0' * 64)
    assert refused.returncode == 2
    assert 'STORE_AUTHORITY_REQUIRED' in refused.stdout + refused.stderr
    target = repo / '.harness-store/history/archives' / token['archive_id']
    assert identity(target) == original[0]
    assert identity(target / 'proof.yaml') == original[1]


def test_legacy_inspection_does_not_activate_storage(tmp_path):
    repo = repository(tmp_path)
    task = repo / ".harness/current-task.yaml"
    before = task.read_bytes()
    result = cli(repo, "storage", "inspect", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["mode"] == "legacy"
    assert task.read_bytes() == before
    assert not (repo / ".harness-store").exists()
