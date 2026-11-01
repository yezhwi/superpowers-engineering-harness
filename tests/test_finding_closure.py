"""Batch closure uses real native receipts; never synthesize aggregate execution."""
import json
import shlex
import subprocess
import sys

import pytest
import yaml
from test_finding_transition import cli


@pytest.fixture
def batch_repo(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    assert cli(tmp_path, 'init').returncode == 0
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_x.py').write_text("import os\ndef test_x():\n assert os.environ.get('BATCH_RED') != '1'\n")
    (tests / 'test_y.py').write_text('def test_y():\n assert True\n')
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base'], cwd=tmp_path, check=True)
    root = tmp_path / '.harness'
    finding = {'id': 'FND-001', 'category': 'adversarial', 'kind': 'invariant_violation', 'target': 'INV-001',
               'scenario': 'two related regression batches', 'severity': 'major', 'status': 'PROPOSED'}
    path = root / 'findings/FND-001.yaml'
    path.write_text(yaml.safe_dump(finding))
    refs = {}
    for name, selector in [('red', 'tests/test_x.py::test_x'), ('green', 'tests/test_x.py::test_x'),
                           ('a', 'tests/test_x.py'), ('b', 'tests/test_y.py')]:
        before = set((root / 'evidence').glob('*.json'))
        command = f'BATCH_RED={int(name == "red")} {shlex.quote(sys.executable)} -B -m pytest -q -p no:cacheprovider {selector}'
        args = ['evidence', 'run', '--type', 'unit_test', '--covered-test', selector, '--command', command]
        if name in {'red', 'green'}:
            args += ['--finding', 'FND-001', '--test', 'tests/test_x.py::test_x', '--phase', name]
        result = cli(tmp_path, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        new = set((root / 'evidence').glob('*.json')) - before
        assert len(new) == 1
        refs[name] = new.pop().name
    finding.update(status='FIXED', confirmed_at='2026-10-31T00:00:00Z', test='tests/test_x.py::test_x',
                   regression_test={'path': 'tests/test_x.py::test_x', 'red_evidence': refs['red'], 'green_evidence': refs['green']})
    path.write_text(yaml.safe_dump(finding))
    impact = {'impact': {'required_tests': ['tests/test_x.py', 'tests/test_y.py']}}
    (root / 'impact.yaml').write_text(yaml.safe_dump(impact))
    return root, finding, refs, impact


def test_native_split_related_receipts_close_without_synthetic_execution(batch_repo):
    root, finding, refs, impact = batch_repo
    before = {p.name: p.read_bytes() for p in (root / 'evidence').glob('*.json')}
    result = cli(root.parent, 'finding', 'transition', 'FND-001', 'VERIFIED',
                 '--evidence', refs['a'], '--evidence', refs['b'])
    assert result.returncode == 0, result.stdout + result.stderr
    updated = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())
    assert updated['status'] == 'VERIFIED' and 'evidence' not in updated
    assert [item['ref'] for item in updated['closure_evidence']['receipts']] == [refs['a'], refs['b']]
    assert {p.name: p.read_bytes() for p in (root / 'evidence').glob('*.json')} == before
    closed = cli(root.parent, 'finding', 'transition', 'FND-001', 'CLOSED')
    assert closed.returncode == 0, closed.stderr
    assert yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())['closure_evidence'] == updated['closure_evidence']


def test_workspace_symlink_alias_accepts_batch_and_preserves_duplicate_and_nofollow_rules(batch_repo):
    from harness.evidence_validator import EvidenceValidationError
    from harness.finding_closure import prepare_closure_proof, publish_batch_closure, validate_persisted_batch_closure
    from harness.transaction_recovery import publication_admission
    from harness.workspace import snapshot
    root, finding, refs, impact = batch_repo
    alias = root.parent.with_name(root.parent.name + '-workspace-alias')
    alias.symlink_to(root.parent, target_is_directory=True)
    alias_root = alias / '.harness'
    current = snapshot(root.parent)
    error = None
    with publication_admission(alias_root):
        try:
            prepared = prepare_closure_proof(alias_root, finding, [refs['a'], refs['b']], impact,
                                             current_head=current.head, current_workspace=current.fingerprint)
        except EvidenceValidationError as caught:
            error = str(caught)
        assert error is None, 'workspace alias wrongly refused: ' + str(error)
        assert set(prepared['sources']) == {'evidence/' + refs['a'], 'evidence/' + refs['b']}
        for duplicate in ['.harness/evidence/' + refs['a'], str(root / 'evidence' / refs['a'])]:
            with pytest.raises(EvidenceValidationError, match='BATCH_EVIDENCE_DUPLICATE'):
                prepare_closure_proof(alias_root, finding, [refs['a'], duplicate], impact,
                                      current_head=current.head, current_workspace=current.fingerprint)
        receipt_link = root / 'evidence/receipt-link.json'
        receipt_link.symlink_to(refs['a'])
        with pytest.raises(EvidenceValidationError):
            prepare_closure_proof(alias_root, finding, ['receipt-link.json', refs['b']], impact,
                                  current_head=current.head, current_workspace=current.fingerprint)
        publish_batch_closure(alias_root, alias_root / 'findings/FND-001.yaml', finding, [refs['a'], refs['b']])
        updated = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())
        assert updated['status'] == 'VERIFIED'
        validate_persisted_batch_closure(alias_root, updated, impact,
                                        current_head=current.head, current_workspace=current.fingerprint)


def test_workspace_alias_cli_can_close_published_batch_without_new_receipts(batch_repo):
    from harness.finding_closure import publish_batch_closure
    from harness.transaction_recovery import publication_admission
    root, finding, refs, impact = batch_repo
    alias = root.parent.with_name(root.parent.name + '-close-alias')
    alias.symlink_to(root.parent, target_is_directory=True)
    alias_root = alias / '.harness'
    with publication_admission(alias_root):
        publish_batch_closure(alias_root, alias_root / 'findings/FND-001.yaml', finding, [refs['a'], refs['b']])
    before = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())['closure_evidence']
    closed = cli(alias, 'finding', 'transition', 'FND-001', 'CLOSED')
    assert closed.returncode == 0, closed.stderr
    updated = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())
    assert updated['status'] == 'CLOSED' and updated['closure_evidence'] == before


def test_alias_snapshot_rejects_same_byte_inode_swap_during_canonical_check(batch_repo, monkeypatch):
    from harness import source_access
    from harness.evidence_validator import EvidenceValidationError
    from harness.finding_closure import prepare_closure_proof
    from harness.workspace import snapshot
    root, finding, refs, impact = batch_repo
    alias = root.parent.with_name(root.parent.name + '-swap-alias')
    alias.symlink_to(root.parent, target_is_directory=True)
    alias_root = alias / '.harness'
    current = snapshot(root.parent)
    read = source_access.read_regular_snapshot_beneath
    swapped = False
    def replace_after_read(path, boundary, **kwargs):
        nonlocal swapped
        result = read(path, boundary, **kwargs)
        if not swapped and path == alias_root / 'evidence' / refs['a']:
            swapped = True
            original = root / 'evidence' / refs['a']
            original.rename(original.with_suffix('.preserved.json'))
            original.write_bytes(result.content)
        return result
    monkeypatch.setattr(source_access, 'read_regular_snapshot_beneath', replace_after_read)
    before = (root / 'findings/FND-001.yaml').read_bytes()
    with pytest.raises(EvidenceValidationError, match='BATCH_EVIDENCE_CHANGED'):
        prepare_closure_proof(alias_root, finding, [refs['a'], refs['b']], impact,
                              current_head=current.head, current_workspace=current.fingerprint)
    assert swapped
    assert (root / 'findings/FND-001.yaml').read_bytes() == before


def test_alias_publication_rejects_workspace_retarget_before_stage(batch_repo, monkeypatch):
    import shutil
    from harness import finding_closure as closure
    from harness.evidence_validator import EvidenceValidationError
    from harness.transaction_recovery import publication_admission
    root, finding, refs, impact = batch_repo
    alias = root.parent.with_name(root.parent.name + '-retarget-alias')
    other = root.parent.with_name(root.parent.name + '-other-workspace')
    shutil.copytree(root.parent, other)
    alias.symlink_to(root.parent, target_is_directory=True)
    alias_root = alias / '.harness'
    prepare = closure.prepare_closure_proof
    before = (root / 'findings/FND-001.yaml').read_bytes()
    def retarget_after_prepare(*args, **kwargs):
        result = prepare(*args, **kwargs)
        alias.unlink()
        alias.symlink_to(other, target_is_directory=True)
        return result
    monkeypatch.setattr(closure, 'prepare_closure_proof', retarget_after_prepare)
    with publication_admission(alias_root), pytest.raises(EvidenceValidationError, match='BATCH_EVIDENCE_CHANGED'):
        closure.publish_batch_closure(alias_root, alias_root / 'findings/FND-001.yaml', finding, [refs['a'], refs['b']])
    assert (root / 'findings/FND-001.yaml').read_bytes() == before
    assert (other / '.harness/findings/FND-001.yaml').read_bytes() == before


def test_cli_single_evidence_cannot_hide_malformed_batch_metadata(batch_repo):
    root, finding, refs, impact = batch_repo
    finding.update(evidence=refs['a'], closure_evidence={'version': 999, 'receipts': []})
    path = root / 'findings/FND-001.yaml'
    path.write_text(yaml.safe_dump(finding))
    (root / 'impact.yaml').write_text(yaml.safe_dump({'impact': {'required_tests': ['tests/test_x.py']}}))
    before = path.read_bytes()
    result = cli(root.parent, 'finding', 'transition', 'FND-001', 'VERIFIED', '--evidence', refs['a'])
    assert result.returncode == 2
    assert path.read_bytes() == before


def test_batch_schema_rejects_mixed_formats_and_old_schema_rejects_new_batch(batch_repo):
    from jsonschema import ValidationError, validate
    from harness.schema_resources import read_schema
    from test_finding_transition import REPO
    root, finding, refs, impact = batch_repo
    result = cli(root.parent, 'finding', 'transition', 'FND-001', 'VERIFIED', '--evidence', refs['a'], '--evidence', refs['b'])
    assert result.returncode == 0, result.stderr
    updated = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())
    old = subprocess.run(['git', 'show', 'dc4cd9d9c72f509287910f7baa3884832a91e51b:src/harness/schemas/adversarial-finding.schema.json'],
                         cwd=REPO, capture_output=True, check=True, text=True)
    old_schema = json.loads(old.stdout)
    for state in ['VERIFIED', 'CLOSED']:
        updated['status'] = state
        validate(updated, read_schema('adversarial-finding.schema.json'))
        with pytest.raises(ValidationError):
            validate(updated, old_schema)
        updated['evidence'] = refs['a']
        with pytest.raises(ValidationError):
            validate(updated, read_schema('adversarial-finding.schema.json'))
        updated.pop('evidence')


@pytest.mark.parametrize('limit', ['single', 'total', 'count', 'symlink', 'alias'])
def test_loader_limits_and_nonfollow_are_batch_only(batch_repo, monkeypatch, limit):
    from harness import finding_closure as closure
    from harness.evidence_validator import EvidenceValidationError
    from harness.workspace import snapshot
    root, finding, refs, impact = batch_repo
    references = [refs['a'], refs['b']]
    a = root / 'evidence' / refs['a']
    b = root / 'evidence' / refs['b']
    if limit == 'single':
        monkeypatch.setattr(closure, '_MAX_RECEIPT', a.stat().st_size - 1)
    elif limit == 'total':
        monkeypatch.setattr(closure, '_MAX_TOTAL', a.stat().st_size + b.stat().st_size - 1)
    elif limit == 'count':
        references = references * 33
    elif limit == 'alias':
        references[1] = '.harness/evidence/' + refs['a']
    else:
        saved = b.with_suffix('.saved.json')
        b.rename(saved)
        b.symlink_to(saved.name)
    current = snapshot(root.parent)
    with pytest.raises(EvidenceValidationError):
        closure.prepare_closure_proof(root, finding, references, impact,
                                      current_head=current.head, current_workspace=current.fingerprint)


def test_exact_caps_are_allowed_by_preparation_and_gate(batch_repo, monkeypatch):
    from harness import finding_closure as closure
    from harness.workspace import snapshot
    root, finding, refs, impact = batch_repo
    sizes = [(root / 'evidence' / refs[key]).stat().st_size for key in ('a', 'b')]
    monkeypatch.setattr(closure, '_MAX_RECEIPT', max(sizes))
    monkeypatch.setattr(closure, '_MAX_TOTAL', sum(sizes))
    current = snapshot(root.parent)
    prepared = closure.prepare_closure_proof(root, finding, [refs['a'], refs['b']], impact,
                                             current_head=current.head, current_workspace=current.fingerprint)
    finding['closure_evidence'] = prepared['proof']
    closure.validate_persisted_batch_closure(root, finding, impact,
                                            current_head=current.head, current_workspace=current.fingerprint)


def test_critical_flag_populates_candidate_before_batch_policy(batch_repo):
    root, finding, refs, impact = batch_repo
    finding['severity'] = 'critical'
    path = root / 'findings/FND-001.yaml'
    path.write_text(yaml.safe_dump(finding))
    assert 'closure' not in finding
    result = cli(root.parent, 'finding', 'transition', 'FND-001', 'VERIFIED', '--evidence', refs['a'],
                 '--evidence', refs['b'], '--critical-related-approved')
    assert result.returncode == 0, result.stderr
    updated = yaml.safe_load(path.read_bytes())
    assert updated['closure']['critical_related_approved'] is True
    from harness.quality_gate import _validate_finding_proofs
    from harness.workspace import snapshot
    current = snapshot(root.parent)
    _validate_finding_proofs(root, [updated], impact, current.head, current.fingerprint)


@pytest.mark.parametrize('damage', ['missing', 'bytes', 'digest', 'mixed', 'version', 'required', 'critical'])
def test_gate_reloads_batch_and_rejects_drift(batch_repo, damage):
    from harness.quality_gate import InvalidHarnessState, _validate_finding_proofs
    from harness.workspace import snapshot
    root, finding, refs, impact = batch_repo
    result = cli(root.parent, 'finding', 'transition', 'FND-001', 'VERIFIED', '--evidence', refs['a'], '--evidence', refs['b'])
    assert result.returncode == 0, result.stderr
    updated = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())
    current = snapshot(root.parent)
    _validate_finding_proofs(root, [updated], impact, current.head, current.fingerprint)
    if damage == 'missing':
        (root / 'evidence' / refs['b']).unlink()
    elif damage == 'bytes':
        with (root / 'evidence' / refs['b']).open('a') as stream:
            stream.write(' ')
    elif damage == 'digest':
        updated['closure_evidence']['receipts'][0]['sha256'] = 'sha256:' + '0' * 64
    elif damage == 'mixed':
        updated['evidence'] = refs['a']
    elif damage == 'version':
        updated['closure_evidence']['version'] = 2
    elif damage == 'required':
        impact['impact']['required_tests'].append('tests/missing.py')
    else:
        updated['severity'] = 'critical'
    for state in ['VERIFIED', 'CLOSED']:
        updated['status'] = state
        with pytest.raises(InvalidHarnessState):
            _validate_finding_proofs(root, [updated], impact, current.head, current.fingerprint)


def test_callback_receipt_drift_rolls_back_finding_without_rewriting_receipt(batch_repo, monkeypatch):
    from harness import transaction
    from harness.evidence_validator import EvidenceValidationError
    from harness.finding_closure import publish_batch_closure
    from harness.transaction_recovery import publication_admission
    root, finding, refs, impact = batch_repo
    path = root / 'findings/FND-001.yaml'
    before = path.read_bytes()
    receipt = root / 'evidence' / refs['b']
    changed = receipt.read_bytes() + b' '
    original = transaction.publish
    def drift(*args, **kwargs):
        receipt.write_bytes(changed)
        return original(*args, **kwargs)
    monkeypatch.setattr(transaction, 'publish', drift)
    with publication_admission(root), pytest.raises(EvidenceValidationError):
        publish_batch_closure(root, path, finding, [refs['a'], refs['b']])
    assert path.read_bytes() == before
    assert receipt.read_bytes() == changed


@pytest.mark.parametrize('damage', ['missing', 'stale', 'unsupported', 'mixed-scope', 'duplicate', 'critical'])
def test_invalid_batch_does_not_change_finding(batch_repo, damage):
    root, finding, refs, impact = batch_repo
    path = root / 'findings/FND-001.yaml'
    selected = [refs['a'], refs['b']]
    if damage == 'missing':
        selected[1] = 'missing.json'
    elif damage == 'duplicate':
        selected[1] = selected[0]
    elif damage == 'critical':
        finding['severity'] = 'critical'
        path.write_text(yaml.safe_dump(finding))
    else:
        evidence = root / 'evidence' / selected[1]
        record = json.loads(evidence.read_bytes())
        if damage == 'stale':
            record['workspace_fingerprint'] = 'sha256:' + '0' * 64
        elif damage == 'unsupported':
            record['type'] = 'custom'
        else:
            record['scope'] = 'full'
        evidence.write_text(json.dumps(record))  # Deliberately corrupted temporary input.
    before = path.read_bytes()
    result = cli(root.parent, 'finding', 'transition', 'FND-001', 'VERIFIED',
                 '--evidence', selected[0], '--evidence', selected[1])
    assert result.returncode != 0
    assert path.read_bytes() == before
