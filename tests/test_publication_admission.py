"""Pending publications are not valid input for supported state transitions."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml

from harness import (
    controlplane,
    publication_fs,
    publication_journal,
    quality_gate,
    source_access,
    transaction_recovery,
)
from harness.telemetry_lock import telemetry_lock

harness = test_context_builder.harness


def test_task_prune_refuses_pending_publication_without_recovery(harness):
    pending = harness / '.transactions' / 'fixture.json'
    pending.parent.mkdir(exist_ok=True)
    pending.write_text('{}')
    before = pending.read_bytes()

    result = controlplane.cmd_task_prune(apply=False, plan_id=None)

    assert result == 2
    assert pending.read_bytes() == before


@pytest.mark.parametrize('entry', ['validate', 'resolve', 'check', 'summary', 'publish_noop', 'scope_noop'])
@pytest.mark.parametrize('boundary', ['cli', 'domain'])
def test_architecture_refuses_pending_native_alignment_revision(harness, entry, boundary):
    """Break caught: Architecture consumes an uncommitted native revise prefix."""
    from test_context_builder import enable_required_architecture
    from test_test_scope import (
        assert_restored_with_retention,
        file_identities,
        tree_bytes,
    )

    from harness import architecture_store
    from harness.architecture import ArchitectureError

    enable_required_architecture(harness)
    task_path = harness / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_text())
    task['state'] = 'SPECIFYING'
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    candidate = harness.parent / 'src' / 'architecture-candidate.yaml'
    candidate.write_bytes((harness / 'architecture.yaml').read_bytes())
    arguments = {
        'validate': ['validate', '--json'],
        'resolve': ['resolve', 'src/app.py', '--json'],
        'check': ['check', '--json'],
        'summary': ['summary', '--json'],
        'publish_noop': ['publish', '--file', str(candidate)],
        'scope_noop': ['scope', 'add', 'app'],
    }
    actions = {
        'validate': lambda: architecture_store.validate_architecture(harness),
        'resolve': lambda: architecture_store.resolve_architecture_path(harness, 'src/app.py'),
        'check': lambda: architecture_store.check_architecture(harness),
        'summary': lambda: architecture_store.summary_architecture(harness),
        'publish_noop': lambda: architecture_store.publish_architecture(harness, candidate),
        'scope_noop': lambda: architecture_store.mutate_architecture_scope(harness, 'add', 'app'),
    }
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}

    def invoke():
        if boundary == 'cli':
            return subprocess.run(
                [sys.executable, '-m', 'harness.cli', 'architecture', *arguments[entry]],
                cwd=harness.parent, env=environment, capture_output=True, text=True,
                check=False, timeout=30,
            )
        return actions[entry]()

    def assert_healthy():
        value = invoke()
        if boundary == 'cli':
            assert value.returncode == 0, value.stdout + value.stderr
            if entry in {'publish_noop', 'scope_noop'}:
                assert value.stdout.strip() == {
                    'publish_noop': 'ARCHITECTURE_UNCHANGED',
                    'scope_noop': 'ARCHITECTURE_SCOPE_UNCHANGED',
                }[entry]
                return
            value = json.loads(value.stdout)
        if entry in {'publish_noop', 'scope_noop'}:
            assert value is False
        elif entry in {'validate', 'check'}:
            assert value['status'] == 'valid', value
        elif entry == 'resolve':
            assert value['status'] == 'resolved' and tuple(value['modules']) == ('app',)
        else:
            assert value['status'] == 'current' and value['declared_modules'] == ['app']

    assert_healthy()
    before, identities = tree_bytes(harness), file_identities(harness)
    script = '''
import os
from pathlib import Path
from harness import controlplane, publication_fs
root = Path('.harness').stat()
original = publication_fs.move_noreplace
def die_after_seal_move(*args):
    result = original(*args)
    held = os.fstat(args[0])
    if args[1] == 'alignment-freeze.yaml' and (held.st_dev, held.st_ino) == (root.st_dev, root.st_ino):
        os._exit(87)
    return result
publication_fs.move_noreplace = die_after_seal_move
raise SystemExit(controlplane.cmd_align('revise', reason='fixture native interrupted revision'))
'''
    died = subprocess.run([sys.executable, '-c', script], cwd=harness.parent, env=environment,
                          capture_output=True, text=True, check=False, timeout=30)
    assert died.returncode == 87, died.stdout + died.stderr
    pending = list((harness / '.transactions').glob('*.json'))
    assert len(pending) == 1 and json.loads(pending[0].read_bytes())['version'] == 2
    assert not (harness / 'alignment-freeze.yaml').exists()
    assert (harness / 'alignment.yaml').read_bytes() == before['alignment.yaml']
    assert task_path.read_bytes() == before['current-task.yaml']
    assert (harness / 'architecture.yaml').read_bytes() == before['architecture.yaml']
    partial = tree_bytes(harness)
    failure = None
    observed = None
    try:
        observed = invoke()
    except (OSError, ArchitectureError) as exc:
        failure = exc
    finally:
        after = tree_bytes(harness)
        with telemetry_lock(harness):
            transaction_recovery.recover_pending_publications(harness)
    assert after == partial, 'admission refusal must not repair or modify pending bytes'
    assert_restored_with_retention(harness, before, identities)
    assert_healthy()
    if boundary == 'cli':
        assert observed.returncode == 2, f'pending {entry} returned {observed.returncode}: {observed.stdout} {observed.stderr}'
        assert observed.stdout == '' and 'TRANSACTION_RECOVERY_REQUIRED' in observed.stderr, (
            f'pending {entry} wrong refusal: {observed.stdout} {observed.stderr}'
        )
    else:
        assert isinstance(failure, OSError) and 'TRANSACTION_RECOVERY_REQUIRED' in str(failure), (
            f'pending {entry} consumed canonical facts: value={observed!r}, error={failure!r}'
        )


def architecture_fixture_entry(root, entry, boundary):
    from types import SimpleNamespace

    from harness import architecture_store

    source = root / 'architecture.yaml'
    if boundary == 'cli':
        return controlplane.cmd_architecture(SimpleNamespace(
            architecture_command={'publish_noop': 'publish', 'scope_noop': 'scope'}.get(entry, entry),
            source_file=str(source), architecture_scope_action='add', module_id='app',
            architecture_json=True, path='src/app.py',
        ))
    return {
        'validate': lambda: architecture_store.validate_architecture(root),
        'resolve': lambda: architecture_store.resolve_architecture_path(root, 'src/app.py'),
        'check': lambda: architecture_store.check_architecture(root),
        'summary': lambda: architecture_store.summary_architecture(root),
        'publish_noop': lambda: architecture_store.publish_architecture(root, source),
        'scope_noop': lambda: architecture_store.mutate_architecture_scope(root, 'add', 'app'),
    }[entry]()


@pytest.mark.parametrize('entry', ['validate', 'resolve', 'check', 'summary', 'publish_noop', 'scope_noop'])
@pytest.mark.parametrize('boundary', ['cli', 'domain'])
def test_architecture_pending_precedes_first_fact(harness, monkeypatch, capsys, entry, boundary):
    from harness import architecture_store

    directory = harness / '.transactions'
    directory.mkdir(exist_ok=True)
    (directory / 'opaque.json').write_bytes(b'unknown owner')
    before = tree(harness)

    def forbidden(*args, **kwargs):
        raise AssertionError('Architecture fact/recovery/probe before pending refusal')

    monkeypatch.setattr(architecture_store, '_load_task', forbidden)
    monkeypatch.setattr(architecture_store, 'load_architecture', forbidden)
    monkeypatch.setattr(source_access, 'read_bytes', forbidden)
    monkeypatch.setattr(transaction_recovery, 'recover_pending_publications', forbidden)
    monkeypatch.setattr(publication_fs, 'check_capabilities', forbidden)
    if boundary == 'cli':
        assert architecture_fixture_entry(harness, entry, boundary) == 2
        output = capsys.readouterr()
        assert output.out == '' and 'TRANSACTION_RECOVERY_REQUIRED' in output.err
    else:
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_REQUIRED'):
            architecture_fixture_entry(harness, entry, boundary)
    assert tree(harness) == before


@pytest.mark.parametrize('entry', ['validate', 'resolve', 'check', 'summary', 'publish_noop', 'scope_noop',
                                   'publish_change', 'scope_change'])
def test_architecture_owner_covers_reads_and_projection(harness, monkeypatch, entry):
    from test_context_builder import enable_required_architecture

    from harness import architecture_store

    enable_required_architecture(harness)
    task_path = harness / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_text())
    task['state'] = 'SPECIFYING'
    task_path.write_text(yaml.safe_dump(task))
    probes = []

    def assert_locked():
        script = '''
import fcntl,hashlib,os,sys,tempfile
from pathlib import Path
key=str(Path(sys.argv[1]).resolve())
p=Path(tempfile.gettempdir())/('harness-telemetry-'+hashlib.sha256(os.fsencode(key)).hexdigest()+'.lock')
with p.open('r+b') as stream:
    try:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(0)
raise SystemExit(9)
'''
        result = subprocess.run([sys.executable, '-c', script, str(harness)],
                                capture_output=True, text=True, check=False, timeout=15)
        assert result.returncode == 0, result.stderr
        probes.append(True)

    def wrap(name):
        original = getattr(architecture_store, name)

        def checked(*args, **kwargs):
            assert_locked()
            result = original(*args, **kwargs)
            assert_locked()
            return result

        monkeypatch.setattr(architecture_store, name, checked)

    for name in ['_load_task', 'load_architecture', 'architecture_fingerprint',
                 'resolve_ownership', 'architecture_context_summary', 'asdict']:
        wrap(name)
    if entry in {'publish_change', 'scope_change'}:
        original_publish = architecture_store.transaction.publish

        def publish(*args, **kwargs):
            assert_locked()
            result = original_publish(*args, **kwargs)
            assert_locked()
            return result

        monkeypatch.setattr(architecture_store.transaction, 'publish', publish)
        if entry == 'scope_change':
            assert architecture_store.mutate_architecture_scope(harness, 'remove', 'app') is True
        else:
            document = yaml.safe_load((harness / 'architecture.yaml').read_text())
            document['modules'][0]['responsibility'] = 'Changed fixture behavior.'
            source = harness.parent / 'src' / 'candidate.yaml'
            source.write_text(yaml.safe_dump(document))
            assert architecture_store.publish_architecture(harness, source) is True
    else:
        architecture_fixture_entry(harness, entry, 'domain')
    assert len(probes) >= 2


def review_import_fixture(root, family):
    from dataclasses import replace

    from test_cli_complexity import audit_checks
    from test_interface_contract import contract

    from harness import (
        complexity,
        diagnosability,
        interface_contract,
        interface_review,
        workspace,
    )

    task_path = root / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_text())
    task['state'] = 'VERIFYING'
    task['task']['type'] = 'feature'
    task_path.write_text(yaml.safe_dump(task))
    source_file = root.parent / 'src/local.py'
    source_file.parent.mkdir(exist_ok=True)
    source_file.write_text('def test_local():\n    pass\n')
    (root / 'observability.yaml').write_text(yaml.safe_dump({
        'version': 1, 'required': False,
        'applicability': {'reasons': ['not_assessed'], 'inspected_paths': ['src/local.py']},
    }))
    documents = {
        'complexity': {'task': 'TASK-028', 'checks': audit_checks(), 'findings': []},
        'diagnosability': {
            'task': 'TASK-028', 'contract_required': False, 'finding_ids': [], 'direct_dependencies': [],
            'review_scope': {'files': ['src/local.py']},
            'checks': {name: 'not_applicable' for name in diagnosability.CHECK_NAMES},
        },
        'interface': {
            'task': 'TASK-028', 'contracts': ['INT-001'],
            'checks': {name: 'pass' for name in interface_review.CHECKS}, 'proposals': [],
        },
    }
    if family == 'interface':
        interface_contract.declare(root, contract())
    document = documents[family]
    source = root / 'review-input.yaml'
    source.write_text(yaml.safe_dump(document))
    scope = replace(workspace.review_scope('HEAD'), files=('src/local.py',), contract_refs=())
    if family == 'complexity':
        module, writer = complexity, 'write_complexity_review'
        def direct():
            return complexity.write_complexity_review(root, document, scope)
    elif family == 'diagnosability':
        module, writer = diagnosability, 'write_review'
        parsed = diagnosability.load_review_input(source, task_id='TASK-028')
        def direct():
            return diagnosability.write_review(root, parsed, base_ref='HEAD', task_type='feature')
    else:
        module, writer = interface_review, 'write_review'
        def direct():
            return interface_review.write_review(root, source, task_id='TASK-028', base_ref='HEAD')
    command = getattr(controlplane, 'cmd_review_' + family)
    return source, lambda: command(source, 'HEAD'), direct, module, writer


def assert_review_owner(root):
    script = '''
import fcntl,hashlib,os,sys,tempfile
from pathlib import Path
key=str(Path(sys.argv[1]).resolve())
p=Path(tempfile.gettempdir())/('harness-telemetry-'+hashlib.sha256(os.fsencode(key)).hexdigest()+'.lock')
with p.open('r+b') as stream:
    try:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(7)
raise SystemExit(0)
'''
    result = subprocess.run([sys.executable, '-c', script, str(root)],
                            capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode == 7, f'review owner released: exit={result.returncode}, stderr={result.stderr}'


@pytest.mark.parametrize('family', ['complexity', 'diagnosability', 'interface'])
@pytest.mark.parametrize('boundary', ['cli', 'domain'])
def test_review_import_owner_covers_complete_use(harness, monkeypatch, capsys, family, boundary):
    """Break caught: review ownership ends before first fact, publication, or CLI render."""
    import builtins

    _, command, direct, module, _ = review_import_fixture(harness, family)
    phases = []
    name = {'complexity': 'snapshot', 'diagnosability': 'load_contract', 'interface': 'load_interface_contract'}[family]
    first_fact = getattr(module, name)
    original_publish = module.publish

    def first(*args, **kwargs):
        assert_review_owner(harness)
        phases.append('first')
        return first_fact(*args, **kwargs)

    def publish(*args, **kwargs):
        assert_review_owner(harness)
        phases.append('before')
        result = original_publish(*args, **kwargs)
        assert_review_owner(harness)
        phases.append('after')
        return result

    def render(*args, **kwargs):
        if args and 'review written:' in str(args[0]):
            assert_review_owner(harness)
            phases.append('render')
        return builtins.print(*args, **kwargs)

    monkeypatch.setattr(module, name, first)
    monkeypatch.setattr(module, 'publish', publish)
    monkeypatch.setattr(controlplane, 'print', render, raising=False)
    if boundary == 'cli':
        assert command() == 0, capsys.readouterr().err
    else:
        direct()
    assert phases == ['first', 'before', 'after'] + (['render'] if boundary == 'cli' else [])


@pytest.mark.parametrize('family', ['complexity', 'diagnosability', 'interface'])
@pytest.mark.parametrize('attack', ['pending_cli', 'pending_domain', 'eligibility_gap'])
def test_review_import_refuses_unowned_facts(harness, monkeypatch, capsys, family, attack):
    """Break caught: review facts/eligibility survive a publication ownership gap."""
    from test_test_scope import (
        assert_restored_with_retention,
        file_identities,
        tree_bytes,
    )

    _, command, direct, module, writer = review_import_fixture(harness, family)
    assert command() == 0, capsys.readouterr().err
    direct()
    capsys.readouterr()
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    if attack == 'eligibility_gap':
        original = getattr(module, writer)
        observations = []

        def compete(*args, **kwargs):
            script = '''
import fcntl,hashlib,os,sys,tempfile
from pathlib import Path
key=str(Path(sys.argv[1]).resolve())
p=Path(tempfile.gettempdir())/('harness-telemetry-'+hashlib.sha256(os.fsencode(key)).hexdigest()+'.lock')
with p.open('r+b') as stream:
    try:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(7)
raise SystemExit(0)
'''
            probe = subprocess.run([sys.executable, '-c', script, str(harness)],
                                   capture_output=True, text=True, check=False, timeout=15)
            assert probe.returncode in {0, 7}, probe.stderr
            if probe.returncode == 0:
                transition = subprocess.run([sys.executable, '-m', 'harness.cli', 'transition', 'IMPLEMENTING'],
                                            cwd=harness.parent, env=environment, capture_output=True,
                                            text=True, check=False, timeout=30)
                assert transition.returncode == 0, transition.stdout + transition.stderr
                assert yaml.safe_load((harness / 'current-task.yaml').read_text())['state'] == 'IMPLEMENTING'
            observations.append(probe.returncode)
            return original(*args, **kwargs)

        monkeypatch.setattr(module, writer, compete)
        result = command()
        output = capsys.readouterr()
        assert result == 0, output.err
        evidence = harness / 'evidence' / (family + '-review.json')
        assert json.loads(evidence.read_text())['exit_code'] == 0
        assert observations == [7], f'unowned review eligibility: family={family}, importer published after supported state transition'
        return

    before, identities = tree_bytes(harness), file_identities(harness)
    script = '''
import os
from pathlib import Path
from harness import publication_fs
from harness.test_scope import add_required_test
root=Path('.harness').stat()
original=publication_fs.exchange
def die_after_impact(*args):
    result=original(*args)
    held=os.fstat(args[0])
    if args[1]=='impact.yaml' and (held.st_dev,held.st_ino)==(root.st_dev,root.st_ino):
        os._exit(87)
    return result
publication_fs.exchange=die_after_impact
add_required_test(Path('.harness'),'src/local.py::test_local')
'''
    child = subprocess.run([sys.executable, '-c', script], cwd=harness.parent, env=environment,
                           capture_output=True, text=True, check=False, timeout=40)
    assert child.returncode == 87, child.stdout + child.stderr
    assert len(list((harness / '.transactions').glob('*.json'))) == 1
    assert yaml.safe_load((harness / 'impact.yaml').read_text())['impact']['required_tests'] == ['src/local.py::test_local']
    assert (harness / 'current-task.yaml').read_bytes() == before['current-task.yaml']
    reads = []
    if attack == 'pending_cli':
        target, name = controlplane, 'load_task'
    else:
        name = {'complexity': 'snapshot', 'diagnosability': 'load_contract', 'interface': 'load_interface_contract'}[family]
        target = module
    original = getattr(target, name)

    def read(*args, **kwargs):
        reads.append(name)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, read)
    failure = None
    result = None
    try:
        result = command() if attack == 'pending_cli' else direct()
    except OSError as exc:
        failure = exc
    finally:
        output = capsys.readouterr()
        monkeypatch.setattr(target, name, original)
        with telemetry_lock(harness):
            transaction_recovery.recover_pending_publications(harness)
    assert_restored_with_retention(harness, before, identities)
    assert command() == 0, capsys.readouterr().err
    if attack == 'pending_cli':
        assert result == 2 and 'TRANSACTION_RECOVERY_REQUIRED' in output.err
    else:
        assert isinstance(failure, OSError) and 'TRANSACTION_RECOVERY_REQUIRED' in str(failure)
    assert reads == [], f'pending review consumed facts before admission: family={family}, boundary={attack}, reads={reads}'


REMAINING_COMMANDS = (
    'decision-propose', 'decision-accept', 'decision-reject', 'decision-supersede',
    'decision-reindex', 'decision-list', 'decision-show',
    'align-init', 'align-freeze', 'align-revise', 'align-status', 'align-check', 'align-diff',
    'interface-declare', 'interface-verify', 'interface-approve-breaking', 'interface-list', 'interface-show',
    'minimal', 'plan-status', 'plan-sync', 'task-new', 'task-recover', 'task-verify-existing',
    'authorize', 'requirement', 'invariant', 'attach', 'telemetry-report', 'telemetry-show',
    'finding-list', 'finding-show',
)
REMAINING_DOMAINS = (
    'decision-propose', 'decision-accept', 'decision-reject', 'decision-supersede', 'decision-reindex',
    'interface-declare', 'interface-verify', 'interface-approve-breaking',
    'minimal', 'plan-sync', 'telemetry-report',
)


def remaining_command_fixture(root, operation, capsys):
    from types import SimpleNamespace

    from test_alignment import complete_alignment
    from test_cli_complexity import minimal_decision
    from test_decision import proposal
    from test_interface_contract import contract

    from harness import (
        collect_evidence,
        complexity,
        decision,
        interface_contract,
        plan_markdown,
        telemetry,
    )
    from harness.plan_reconciliation import plan_fingerprint

    task_path = root / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_text())
    if operation == 'task-new':
        task['state'] = 'DONE'
    elif operation == 'task-recover':
        task['state'] = 'IMPLEMENTING'
    if operation.startswith('plan-'):
        task['risk']['level'] = 'Q2'
        task['risk']['profile'] = 'STANDARD'
        task['plan_reconciliation'] = {'enabled': True, 'mode': 'final'}
        plan = {'version': 1, 'items': [{'id': 'P-001', 'intent': 'fixture', 'surfaces': ['src/local.py']}]}
        (root / 'plan.yaml').write_text(yaml.safe_dump(plan))
        (root / 'plan-execution.yaml').write_text(yaml.safe_dump({
            'version': 1, 'plan': {'path': '.harness/plan.yaml', 'fingerprint': plan_fingerprint(plan)}, 'items': {},
        }))
        docs = root.parent / 'docs'
        docs.mkdir(exist_ok=True)
        (docs / 'plan.md').write_text('- [x] P-001 fixture\n')
    task_path.write_text(yaml.safe_dump(task))
    (root.parent / 'src').mkdir(exist_ok=True)
    (root.parent / 'src/local.py').write_text('def test_local():\n    assert True\n')
    (root.parent / '.gitignore').write_text('__pycache__/\n.pytest_cache/\n')
    inputs = root / '.test-inputs'
    inputs.mkdir()
    document = proposal()
    (inputs / 'proposal.yaml').write_text(yaml.safe_dump(document))
    if operation.startswith('decision-'):
        decision.propose(root, document)
        if operation == 'decision-supersede':
            decision.accept(root, 'DEC-001', 'redis', 'accepted_recommendation')
    contract_document = contract()
    if operation == 'interface-approve-breaking':
        contract_document['compatibility'] = {'classification': 'breaking', 'rationale': 'fixture', 'migration': 'fixture'}
    if operation.startswith('interface-'):
        interface_contract.declare(root, contract_document)
    if operation.startswith('align-') and operation != 'align-init':
        alignment = complete_alignment()
        alignment.update({'task_id': 'TASK-028', 'decision_ids': [], 'interface_contract_ids': []})
        (root / 'alignment.yaml').write_text(yaml.safe_dump(alignment))
        if operation != 'align-freeze':
            assert controlplane.cmd_align('freeze') == 0, capsys.readouterr().err
    minimal = minimal_decision()
    minimal['task'] = 'TASK-028'
    (inputs / 'minimal.yaml').write_text(yaml.safe_dump(minimal))
    usage = {'task_id': 'TASK-028', 'usage': {'total_tokens': 123, 'source': 'runtime', 'tool_calls': 7}}
    (inputs / 'usage.yaml').write_text(yaml.safe_dump(usage))
    if operation == 'telemetry-show':
        telemetry.report_usage(root, usage)
    if operation.startswith('finding-'):
        (root / 'findings/FND-777.yaml').write_text(yaml.safe_dump({
            'id': 'FND-777', 'category': 'adversarial', 'kind': 'invariant_violation', 'target': 'INV-001',
            'scenario': 'private valid diagnostic fixture', 'severity': 'minor', 'status': 'PROPOSED',
        }))
    if operation == 'requirement':
        (root / 'requirements.yaml').write_text(yaml.safe_dump({'requirements': [{
            'id': 'REQ-001', 'statement': 'fixture', 'priority': 'must', 'status': 'pending', 'evidence': [],
        }]}))
    if operation == 'invariant':
        (root / 'invariants.yaml').write_text(yaml.safe_dump({'invariants': [{
            'id': 'INV-001', 'statement': 'fixture', 'category': 'correctness', 'severity': 'critical',
            'status': 'pending', 'verification': [],
        }]}))
    lint_command = f'''{sys.executable} -c "import ast; ast.parse(open('src/local.py').read())"'''
    if operation in {'interface-verify', 'requirement', 'invariant', 'attach', 'task-verify-existing'}:
        evidence = collect_evidence._collect('lint', collect_evidence._TrustedLocalCommand(lint_command))
        assert evidence['exit_code'] == 0
        (root / 'evidence/sample-lint.json').write_text(json.dumps(evidence))
        external = {
            'task': 'TASK-028', 'command': lint_command, 'exit_code': evidence['exit_code'],
            'started_at': evidence['timestamp'], 'finished_at': evidence['timestamp'],
            'git_head': evidence['commit'], 'workspace_fingerprint': evidence['workspace_fingerprint'],
            'stdout_digest': '', 'stderr_digest': '',
            'provenance': {'kind': 'external', 'command': lint_command, 'exit_code': evidence['exit_code'],
                           'git_head': evidence['commit'], 'workspace_fingerprint': evidence['workspace_fingerprint'],
                           'reference': 'fixture-actual-local-source-parse'},
        }
        (inputs / 'external.json').write_text(json.dumps(external))
    if operation == 'task-verify-existing':
        build_command = f'''{sys.executable} -c "import py_compile; py_compile.compile('src/local.py',cfile='.harness/.test-inputs/local.pyc',doraise=True)"'''
        build = collect_evidence._collect('build', collect_evidence._TrustedLocalCommand(build_command))
        unit = collect_evidence._collect('unit_test', collect_evidence._TrustedLocalCommand(f'{sys.executable} -m pytest src/local.py -q'), covered_tests=('src/local.py',))
        assert build['exit_code'] == unit['exit_code'] == 0
        (root / 'evidence/build.json').write_text(json.dumps(build))
        (root / 'evidence/unit-test.json').write_text(json.dumps(unit))
    capsys.readouterr()

    def invoke(current_root, boundary):
        if operation.startswith('decision-'):
            action = operation.removeprefix('decision-')
            if boundary == 'cli':
                return controlplane.cmd_decision(SimpleNamespace(
                    decision_command=action, id='DEC-001',
                    option=None if action in {'propose', 'supersede'} else 'redis', source=None,
                    reason=None if action in {'propose', 'supersede'} else 'fixture',
                    source_file=str(current_root / '.test-inputs/proposal.yaml'),
                ))
            if action == 'propose':
                return decision.propose(current_root, document)
            if action == 'accept':
                return decision.accept(current_root, 'DEC-001', 'redis', 'accepted_recommendation')
            if action == 'reject':
                return decision.reject(current_root, 'DEC-001', 'fixture')
            if action == 'supersede':
                return decision.supersede(current_root, 'DEC-001', document)
            return decision.reindex(current_root)
        if operation.startswith('align-'):
            return controlplane.cmd_align(operation.removeprefix('align-'), reason='fixture')
        if operation.startswith('interface-'):
            action = operation.removeprefix('interface-')
            if boundary == 'cli':
                return controlplane.cmd_interface(SimpleNamespace(
                    interface_command=action, id='INT-001', evidence='sample-lint.json', reason='fixture',
                    name=contract_document['name'], kind='cli', consumer=['agent-worker'], input='arguments',
                    output='result', error='stable code', compatibility=contract_document['compatibility']['classification'],
                    rationale='fixture', migration=contract_document['compatibility']['migration'], decision_ref=[],
                ))
            if action == 'declare':
                return interface_contract.declare(current_root, contract_document)
            if action == 'verify':
                return interface_contract.verify(current_root, 'INT-001', 'sample-lint.json')
            return interface_contract.approve_breaking(current_root, 'INT-001', 'fixture')
        if operation == 'minimal':
            return (controlplane.cmd_check_minimal(current_root / '.test-inputs/minimal.yaml') if boundary == 'cli'
                    else complexity.write_minimal_decision(current_root, minimal))
        if operation == 'plan-status':
            return controlplane.cmd_plan_status(True)
        if operation == 'plan-sync':
            return (controlplane.cmd_plan_sync_markdown('docs/plan.md') if boundary == 'cli'
                    else plan_markdown.sync_plan_markdown(current_root, current_root.parent, task, 'docs/plan.md'))
        if operation == 'task-new':
            return controlplane.cmd_task_new('TASK-029', 'fixture')
        if operation == 'task-recover':
            return controlplane.cmd_task_recover('TASK-029', 'fixture', 'fixture')
        if operation == 'task-verify-existing':
            return controlplane.cmd_task_verify_existing('HEAD', 'fixture', 'already_satisfied', untraceable_reason='fixture source not tracked')
        if operation == 'authorize':
            return controlplane.cmd_authorize('commit', True)
        if operation == 'requirement':
            return controlplane.cmd_requirement_verify('REQ-001', 'sample-lint.json')
        if operation == 'invariant':
            return controlplane.cmd_invariant_verify('INV-001', 'sample-lint.json')
        if operation == 'attach':
            return controlplane.cmd_evidence_attach('lint', lint_command, 'related', current_root / '.test-inputs/external.json')
        if operation == 'telemetry-report':
            return (controlplane.cmd_telemetry_report(current_root / '.test-inputs/usage.yaml') if boundary == 'cli'
                    else telemetry.report_usage(current_root, usage))
        if operation == 'telemetry-show':
            return controlplane.cmd_telemetry_show()
        if operation == 'finding-list':
            return controlplane.cmd_finding_list()
        assert operation == 'finding-show'
        return controlplane.cmd_finding_show('FND-777')

    return invoke


@pytest.mark.parametrize(('boundary', 'operation'),
                         [('cli', item) for item in REMAINING_COMMANDS] + [('domain', item) for item in REMAINING_DOMAINS])
def test_remaining_canonical_commands_refuse_pending_before_facts(harness, tmp_path, monkeypatch, capsys, boundary, operation):
    """Break caught: ordinary entry reads/writes canonical facts before pending admission."""
    import shutil

    from test_test_scope import (
        assert_restored_with_retention,
        file_identities,
        tree_bytes,
    )

    invoke = remaining_command_fixture(harness, operation, capsys)
    healthy = tmp_path.with_name(tmp_path.name + '-healthy')
    shutil.copytree(harness.parent, healthy)
    with monkeypatch.context() as context:
        context.chdir(healthy)
        result = invoke(healthy / '.harness', boundary)
        if boundary == 'cli':
            assert result == 0, capsys.readouterr().err
    capsys.readouterr()
    before, identities = tree_bytes(harness), file_identities(harness)
    script = '''
import os
from pathlib import Path
from harness import publication_fs
from harness.transaction import StagedArtifact,publish,stage
root=Path('.harness');identity=root.stat();original=publication_fs.exchange
artifacts=tuple(StagedArtifact(name,(root/name).read_bytes()) for name in ('gate.yaml','impact.yaml'))
def die_after_gate(*args):
    result=original(*args);held=os.fstat(args[0])
    if args[1]=='gate.yaml' and (held.st_dev,held.st_ino)==(identity.st_dev,identity.st_ino):
        os._exit(87)
    return result
publication_fs.exchange=die_after_gate
publish(root,stage(root,artifacts),replace_paths=frozenset(a.relative_path for a in artifacts),durable=True,
        expected_sources={a.relative_path:a.content for a in artifacts},expected_artifacts=artifacts)
'''
    child = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                           env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
                           capture_output=True, text=True, check=False, timeout=30)
    assert child.returncode == 87, child.stdout + child.stderr
    assert len(list((harness / '.transactions').glob('*.json'))) == 1
    assert (harness / 'gate.yaml').read_bytes() == before['gate.yaml']
    assert (harness / 'gate.yaml').stat().st_ino != identities['gate.yaml'][1]
    accesses = []

    class UnownedCanonicalAccess(OSError):
        pass

    def observed(original):
        def access(path, *args, **kwargs):
            try:
                parts = Path(path).absolute().relative_to(harness.absolute()).parts
            except (ValueError, TypeError):
                parts = ()
            if parts and not parts[0].startswith('.'):
                accesses.append(str(Path(*parts)))
                raise UnownedCanonicalAccess('TEST_UNOWNED_CANONICAL_ACCESS')
            return original(path, *args, **kwargs)
        return access

    failure = None
    with monkeypatch.context() as context:
        for name in ('read_text', 'read_bytes', 'exists', 'is_file', 'is_dir', 'members'):
            context.setattr(source_access, name, observed(getattr(source_access, name)))
        for name in ('open', 'exists', 'is_file', 'is_dir'):
            context.setattr(Path, name, observed(getattr(Path, name)))
        try:
            result = invoke(harness, boundary)
        except (OSError, ValueError) as exc:
            failure = exc
        finally:
            output = capsys.readouterr()
    with telemetry_lock(harness):
        transaction_recovery.recover_pending_publications(harness)
    assert_restored_with_retention(harness, before, identities)
    assert accesses == [], f'unowned canonical access: {boundary}/{operation}: {accesses}'
    if boundary == 'cli':
        assert result == 2 and 'TRANSACTION_RECOVERY_REQUIRED' in output.err
    else:
        assert isinstance(failure, OSError) and 'TRANSACTION_RECOVERY_REQUIRED' in str(failure)


@pytest.mark.parametrize(('boundary', 'operation'),
                         [('cli', item) for item in REMAINING_COMMANDS] + [('domain', item) for item in REMAINING_DOMAINS])
def test_remaining_commands_owner_covers_complete_use(harness, monkeypatch, capsys, boundary, operation):
    """Break caught: ordinary-entry owner ends before actual writes or CLI rendering."""
    import builtins

    from harness import decision, plan_markdown, telemetry, transaction

    invoke = remaining_command_fixture(harness, operation, capsys)
    phases = []

    def canonical(path, *, write=False):
        path = Path(path).absolute()
        if write and (path == harness.absolute() or path == harness.parent / 'docs/plan.md'):
            return True
        try:
            parts = path.relative_to(harness.absolute()).parts
        except ValueError:
            return False
        return bool(parts and not parts[0].startswith('.'))

    def reader(original):
        def call(path, *args, **kwargs):
            if 'first' not in phases and canonical(path):
                assert_review_owner(harness)
                phases.append('first')
            return original(path, *args, **kwargs)
        return call

    def writer(original):
        def call(path, *args, **kwargs):
            matched = canonical(path, write=True)
            if matched:
                assert_review_owner(harness)
                phases.append('before')
            result = original(path, *args, **kwargs)
            if matched:
                assert_review_owner(harness)
                phases.append('after')
            return result
        return call

    replace_path = Path.replace

    def replace(path, target):
        matched = canonical(path, write=True) or canonical(target, write=True)
        if matched:
            assert_review_owner(harness)
            phases.append('before')
        result = replace_path(path, target)
        if matched:
            assert_review_owner(harness)
            phases.append('after')
        return result

    def render(*args, **kwargs):
        assert_review_owner(harness)
        phases.append('render')
        return builtins.print(*args, **kwargs)

    for name in ('read_text', 'read_bytes', 'exists', 'is_file', 'is_dir', 'members'):
        monkeypatch.setattr(source_access, name, reader(getattr(source_access, name)))
    for name in ('open', 'exists', 'is_file', 'is_dir'):
        monkeypatch.setattr(Path, name, reader(getattr(Path, name)))
    for module, name in ((transaction, 'publish'), (transaction, 'atomic_write'),
                         (decision, 'publish'), (plan_markdown, 'atomic_write'), (telemetry, 'atomic_write')):
        monkeypatch.setattr(module, name, writer(getattr(module, name)))
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(controlplane, 'print', render, raising=False)
    result = invoke(harness, boundary)
    if boundary == 'cli':
        assert result == 0, capsys.readouterr().err
        if operation != 'authorize':  # Successful authorization intentionally emits nothing.
            assert 'render' in phases
    assert 'first' in phases
    read_only = {'decision-list', 'decision-show', 'interface-list', 'interface-show',
                 'align-status', 'align-check', 'align-diff', 'plan-status', 'telemetry-show',
                 'finding-list', 'finding-show'}
    if operation not in read_only:
        assert 'before' in phases and phases.count('before') == phases.count('after')
    assert not list((harness / '.transactions').glob('*.json'))


def test_transition_refuses_pending_partial_task_publication(harness):
    task_path = harness / 'current-task.yaml'
    original = task_path.read_bytes()
    task = yaml.safe_load(original)
    task['budget']['context_expansions'] = task['budget'].get('context_expansions', 0) + 1
    partial = yaml.safe_dump(task, sort_keys=False).encode()
    impact = harness / 'impact.yaml'
    before_impact = impact.read_bytes()
    with telemetry_lock(harness):
        transaction_recovery.begin(harness, [(task_path, original, partial),
                                             (impact, before_impact, before_impact + b'\n')])
        task_path.write_bytes(partial)  # Death after first member, before second.
    result = subprocess.run(
        [sys.executable, '-m', 'harness.cli', 'transition', 'IMPLEMENTING'],
        cwd=harness.parent, env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
        capture_output=True, text=True, check=False, timeout=25,
    )
    assert result.returncode != 0, f'pending task was consumed: {result.stdout} {result.stderr}'
    assert 'TRANSACTION_RECOVERY_' in result.stderr, f'wrong refusal: {result.stdout} {result.stderr}'
    assert task_path.read_bytes() == partial, 'refusal must not strand recovery by rewriting task'
    with telemetry_lock(harness):
        transaction_recovery.recover_pending_publications(harness)
    assert task_path.read_bytes() == original
    assert impact.read_bytes() == before_impact


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def call_entry(root, entry):
    from types import SimpleNamespace

    if entry == 'assess':
        return quality_gate.assess_gate(root, allow_preflight=True)
    if entry == 'run':
        return quality_gate.run_gate(root, allow_preflight=True)
    if entry == 'write_back':
        return quality_gate.write_back(root, None)
    actions = {
        'transition': lambda: controlplane.cmd_transition('IMPLEMENTING'),
        'gate': controlplane.cmd_gate,
        'preflight': controlplane.cmd_gate_preflight,
        'resume': controlplane.cmd_resume,
        'review': lambda: controlplane.cmd_review_outcome('PASS', 'REVIEW_COMPLETE', []),
        'finding': lambda: controlplane.cmd_finding_transition('FND-001', 'FIXING'),
        'finding_resume': lambda: controlplane.cmd_finding_resume_review('FND-001'),
        'classify': lambda: controlplane.cmd_task_classify('Q1', {}),
        'escalate': lambda: controlplane.cmd_task_escalate('Q2', 'scope'),
        'impact': lambda: controlplane.cmd_impact('add-risk', 'anonymous'),
        'plan': lambda: controlplane.cmd_plan_mutation(SimpleNamespace(plan_command='upgrade-execution')),
    }
    return actions[entry]()


@pytest.mark.parametrize('state', ['PREPARED', 'APPLYING', 'VALIDATING', 'ABORTING', 'BLOCKED', 'unknown_version'])
@pytest.mark.parametrize('entry', ['assess', 'run', 'write_back', 'transition', 'gate', 'preflight',
                                   'resume', 'review', 'finding', 'finding_resume', 'classify', 'escalate', 'impact', 'plan'])
def test_pending_refusal_precedes_any_canonical_fact_read(harness, monkeypatch, capsys, state, entry):
    # Opaque descriptors: admission cannot trust even a valid-looking state.
    directory = harness / '.transactions'
    directory.mkdir(exist_ok=True)
    (directory / 'pending.json').write_text(json.dumps({'version': 999 if state == 'unknown_version' else 2,
                                                       'state': state}))
    before = tree(harness)

    def forbidden(*args, **kwargs):
        raise AssertionError('canonical facts/recovery/probes accessed before pending refusal')

    monkeypatch.setattr(controlplane, 'load_task', forbidden)
    monkeypatch.setattr(controlplane, '_findings', forbidden)
    monkeypatch.setattr(controlplane, '_impact', forbidden)
    monkeypatch.setattr(quality_gate, '_load_yaml', forbidden)
    monkeypatch.setattr(source_access, 'read_text', forbidden)
    monkeypatch.setattr(transaction_recovery, 'recover_pending_publications', forbidden)
    monkeypatch.setattr(publication_fs, 'check_capabilities', forbidden)
    if entry in {'assess', 'run', 'write_back'}:
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_'):
            call_entry(harness, entry)
    else:
        assert call_entry(harness, entry) == 2
        error = capsys.readouterr().err
        assert 'TRANSACTION_RECOVERY_' in error
        assert 'Traceback' not in error
    assert tree(harness) == before


@pytest.mark.parametrize('storage', ['symlink', 'non_directory', 'unknown_member', 'multiple'])
def test_unknown_recovery_storage_refuses_without_canonical_reads(harness, monkeypatch, storage):
    directory = harness / '.transactions'
    if directory.exists():
        directory.rmdir()  # Fixture directory is empty; never remove data.
    if storage == 'symlink':
        outside = harness.parent / 'outside'
        outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
    elif storage == 'non_directory':
        directory.write_bytes(b'unknown owner')
    else:
        directory.mkdir()
        (directory / ('a.tmp' if storage == 'unknown_member' else 'a.json')).write_bytes(b'unknown owner')
        if storage == 'multiple':
            (directory / 'b.json').write_bytes(b'other owner')
    before = tree(harness)

    def forbidden(*args, **kwargs):
        raise AssertionError('task facts read through unknown recovery state')

    monkeypatch.setattr(quality_gate, '_load_yaml', forbidden)
    with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        quality_gate.assess_gate(harness, allow_preflight=True)
    assert tree(harness) == before


def test_native_v2_partial_task_publication_refuses_and_recovers(harness):
    task = harness / 'current-task.yaml'
    impact = harness / 'impact.yaml'
    original, original_impact = task.read_bytes(), impact.read_bytes()
    changed = yaml.safe_load(original)
    changed['budget']['context_expansions'] = 1
    payload = yaml.safe_dump(changed, sort_keys=False).encode()
    with (telemetry_lock(harness),
          publication_journal.prepare(harness, (publication_journal.Member('current-task.yaml', original, payload),
                                               publication_journal.Member('impact.yaml', original_impact, original_impact + b'\n'))) as operation):
        operation._save(state='APPLYING')
        operation._step(0, 'forward')
    before = tree(harness)
    result = subprocess.run([sys.executable, '-m', 'harness.cli', 'transition', 'IMPLEMENTING'], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'TRANSACTION_RECOVERY_REQUIRED' in result.stderr
    assert tree(harness) == before
    with telemetry_lock(harness):
        transaction_recovery.recover_pending_publications(harness)
    assert task.read_bytes() == original
    assert impact.read_bytes() == original_impact


@pytest.mark.parametrize('entry', ['assess', 'transition'])
def test_committed_retention_is_not_pending_authority(harness, entry):
    path = harness / 'impact.yaml'
    original = path.read_bytes()
    with (telemetry_lock(harness),
          publication_journal.prepare(harness, (publication_journal.Member('impact.yaml', original, original + b'\n'),)) as operation):
        operation.apply()
        operation.commit()
    assert list((harness / '.publication-retained').iterdir())
    assert not list((harness / '.transactions').iterdir())
    result = call_entry(harness, entry)
    if entry == 'transition':
        assert result == 0
    else:
        assert result.status in {'PASS', 'BLOCKED'}


def interrupt_context_task_publication(harness, version):
    task = harness / 'current-task.yaml'
    original = task.read_bytes()
    value = yaml.safe_load(original)
    value['budget']['context_expansions'] = 1
    changed = yaml.safe_dump(value, sort_keys=False).encode()
    with telemetry_lock(harness):
        if version == 1:
            transaction_recovery.begin(harness, [(task, original, changed)])
            task.write_bytes(changed)
        else:
            with publication_journal.prepare(harness, (
                publication_journal.Member('current-task.yaml', original, changed),
            )) as operation:
                operation._save(state='APPLYING')
                operation._step(0, 'forward')
    assert task.read_bytes() == changed
    pending = list((harness / '.transactions').glob('*.json'))
    assert len(pending) == 1
    assert json.loads(pending[0].read_bytes())['version'] == version
    return original


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('entry', ['validate', 'explain', 'load'])
def test_readonly_context_refuses_pending_without_recovery(harness, version, entry):
    """Break caught: Context diagnostics silently roll back canonical task facts."""
    from harness.context.store import generate_context, load_context

    generate_context(harness)
    original = interrupt_context_task_publication(harness, version)
    before = tree(harness)
    if entry == 'load':
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_REQUIRED'):
            load_context(harness)
    else:
        result = subprocess.run(
            [sys.executable, '-m', 'harness.cli', 'context', entry, '--json'],
            cwd=harness.parent,
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert result.stdout == ''
        assert 'TRANSACTION_RECOVERY_REQUIRED' in result.stderr
    assert tree(harness) == before, 'read-only refusal must preserve canonical and recovery bytes'
    with telemetry_lock(harness):
        transaction_recovery.recover_pending_publications(harness)
    assert (harness / 'current-task.yaml').read_bytes() == original
    assert load_context(harness)[1]['freshness']


@pytest.mark.parametrize('storage', ['non_directory', 'unknown_member', 'multiple'])
def test_readonly_context_refuses_unknown_storage_before_bundle_reads(harness, monkeypatch, storage):
    """Break caught: bypassing admission reads Context through unsafe recovery storage."""
    from harness.context import store

    directory = harness / '.transactions'
    if storage == 'non_directory':
        directory.rmdir()
        directory.write_bytes(b'unknown storage')
    else:
        (directory / ('unknown.tmp' if storage == 'unknown_member' else 'a.json')).write_bytes(b'unknown')
        if storage == 'multiple':
            (directory / 'b.json').write_bytes(b'other owner')
    before = tree(harness)

    def forbidden(*args, **kwargs):
        raise AssertionError('Context facts read before publication admission')

    monkeypatch.setattr(store, '_require_task', forbidden)
    with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        store.load_context(harness)
    assert tree(harness) == before


@pytest.mark.parametrize('version', [1, 2])
def test_explicit_context_recovery_restores_before_read(harness, version):
    from harness.context.store import generate_context

    original = interrupt_context_task_publication(harness, version)
    document = generate_context(harness)
    assert document['control']['task']['id'] == 'TASK-028'
    assert (harness / 'current-task.yaml').read_bytes() == original
    assert not list((harness / '.transactions').iterdir())


@pytest.mark.parametrize('entry', ['assess', 'transition', 'nested_gate', 'status_load', 'status_render', 'impact_read', 'impact_write', 'plan_task', 'plan_artifact', 'plan_write'])
def test_supported_publisher_cannot_enter_admission_to_read_gap(harness, entry):
    if entry.startswith('plan_'):
        from test_plan_mutation_cli import mutation_repo

        plan_repo = harness.parent / 'plan-fixture'
        plan_repo.mkdir()
        harness = mutation_repo(plan_repo)
        path = harness / 'plan-execution.yaml'
        execution = yaml.safe_load(path.read_text())
        path.write_text(yaml.safe_dump({'version': 1, 'plan': execution['plan'], 'items': {}}))
    if entry == 'nested_gate':
        task = yaml.safe_load((harness / 'current-task.yaml').read_text())
        task['state'] = 'GATING'
        (harness / 'current-task.yaml').write_text(yaml.safe_dump(task, sort_keys=False))
    signals = harness.parent / 'signals'
    signals.mkdir()
    reader_script = r'''
import json, os, time
from pathlib import Path
from harness import controlplane, harness_status, plan_reconciliation, quality_gate, transaction
from harness.telemetry_lock import _HELD
root = Path(os.environ['FIXTURE_ROOT'])
signals = Path(os.environ['SIGNALS'])
entry = os.environ['ENTRY']
real = (controlplane.save_task if entry == 'nested_gate' else
        controlplane._impact if entry == 'impact_read' else
        transaction.atomic_write if entry == 'impact_write' else
        plan_reconciliation.load_plan_artifacts if entry == 'plan_artifact' else
        plan_reconciliation.atomic_write if entry == 'plan_write' else
        harness_status._load if entry == 'status_load' else
        harness_status._render if entry == 'status_render' else
        quality_gate._load_yaml if entry == 'assess' else controlplane.load_task)
nested_completed = False
real_assess = quality_gate.assess_gate
def nested_assess(*args, **kwargs):
    global nested_completed
    result = real_assess(*args, **kwargs)
    nested_completed = True
    return result
first = True
def paused(*args, **kwargs):
    global first
    rendered = real(*args, **kwargs) if entry in {'status_render', 'impact_write', 'plan_write'} else None
    if first:
        first = False
        if entry in {'nested_gate', 'status_render'}:
            assert nested_completed, 'pause must follow actual nested assessment before completion'
        (signals / 'reader-entered').write_text(json.dumps({'held': str(root.resolve()) in getattr(_HELD, 'paths', set())}))
        deadline = time.monotonic() + 25
        while not (signals / 'release').exists():
            if time.monotonic() > deadline:
                raise AssertionError('reader release deadline exceeded')
            time.sleep(.01)
    return rendered if entry in {'status_render', 'impact_write', 'plan_write'} else real(*args, **kwargs)
if entry == 'assess':
    quality_gate._load_yaml = paused
    quality_gate.assess_gate(root, allow_preflight=True)
elif entry == 'nested_gate':
    quality_gate.assess_gate = nested_assess
    controlplane.save_task = paused
    assert controlplane.cmd_gate() == 0
elif entry in {'status_load', 'status_render'}:
    quality_gate.assess_gate = nested_assess
    if entry == 'status_load':
        harness_status._load = paused
    else:
        harness_status._render = paused
    assert harness_status.main(['--harness-dir', str(root)]) == 0
elif entry in {'impact_read', 'impact_write'}:
    if entry == 'impact_read':
        controlplane._impact = paused
    else:
        transaction.atomic_write = paused
    assert controlplane.cmd_impact('add-risk', 'reader risk') == 0
elif entry.startswith('plan_'):
    from types import SimpleNamespace
    import yaml
    if entry == 'plan_task':
        controlplane.load_task = paused
    elif entry == 'plan_write':
        plan_reconciliation.atomic_write = paused
    else:
        plan_reconciliation.load_plan_artifacts = paused
    if entry == 'plan_artifact':
        task = yaml.safe_load((root / 'current-task.yaml').read_text())
        assert plan_reconciliation.mutate_plan_execution(root, task, plan_reconciliation.PlanMutationRequest(action='UPGRADE_EXECUTION'))
    else:
        assert controlplane.cmd_plan_mutation(SimpleNamespace(plan_command='upgrade-execution')) == 0
else:
    controlplane.load_task = paused
    assert controlplane.cmd_transition('IMPLEMENTING') == 0
'''
    writer_script = r'''
import fcntl, os, yaml
from pathlib import Path
from harness import transaction
from harness.telemetry_lock import telemetry_lock
root = Path(os.environ['FIXTURE_ROOT'])
signals = Path(os.environ['SIGNALS'])
real_flock = fcntl.flock
def acknowledged_flock(fd, operation):
    if operation == fcntl.LOCK_EX:
        try:
            return real_flock(fd, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            (signals / 'writer-blocked').write_text('actual nonblocking acquisition refused')
    return real_flock(fd, operation)
fcntl.flock = acknowledged_flock
(signals / 'writer-started').write_text('started')
with telemetry_lock(root):
    (signals / 'writer-acquired').write_text('acquired')
    old = (root / 'current-task.yaml').read_bytes()
    task = yaml.safe_load(old)
    task['task']['title'] = 'after reader'
    payload = yaml.safe_dump(task, sort_keys=False).encode()
    artifacts = (transaction.StagedArtifact('current-task.yaml', payload),)
    staged = transaction.stage(root, artifacts)
    transaction.publish(root, staged, expected_sources={'current-task.yaml': old},
                        expected_artifacts=artifacts, replace_paths=frozenset({'current-task.yaml'}))
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
           'FIXTURE_ROOT': str(harness), 'SIGNALS': str(signals), 'ENTRY': entry}
    reader = subprocess.Popen([sys.executable, '-c', reader_script], cwd=harness.parent, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    writer = None
    try:
        wait_for(signals / 'reader-entered')
        assert json.loads((signals / 'reader-entered').read_text()) == {'held': True}
        writer = subprocess.Popen([sys.executable, '-c', writer_script], cwd=harness.parent, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        wait_for(signals / 'writer-started')
        wait_for(signals / 'writer-blocked')
        assert not (signals / 'writer-acquired').exists(), 'publisher entered between admission and first task read'
    finally:
        (signals / 'release').write_text('release')
        out, error = reader.communicate(timeout=35)
        if writer is not None:
            writer_out, writer_error = writer.communicate(timeout=35)
    assert reader.returncode == 0, out + error
    assert writer is not None and writer.returncode == 0, writer_out + writer_error
    task = yaml.safe_load((harness / 'current-task.yaml').read_text())
    assert task['task']['title'] == 'after reader'
    if entry == 'nested_gate':
        assert task['state'] in {'CONVERGED', 'BLOCKED', 'ESCALATED'}
    else:
        assert task['state'] == ('IMPLEMENTING' if entry == 'transition' or entry.startswith('plan_') else 'CLASSIFIED')


def test_pending_inspection_io_failure_is_bounded_and_releases_lock(harness, monkeypatch, capsys):
    from harness.telemetry_lock import _HELD

    before = tree(harness)
    held_before = set(getattr(_HELD, 'paths', set()))

    def unreadable(*args):
        raise PermissionError('sensitive-path-or-payload-must-not-leak')

    monkeypatch.setattr(transaction_recovery, 'require_no_pending_publications', unreadable)
    assert controlplane.cmd_transition('IMPLEMENTING') == 2
    error = capsys.readouterr().err
    assert 'TRANSACTION_RECOVERY_BLOCKED: cannot inspect recovery state' in error
    assert 'sensitive-path-or-payload' not in error
    assert set(getattr(_HELD, 'paths', set())) == held_before
    assert tree(harness) == before


@pytest.mark.parametrize('entry', ['assess', 'transition'])
def test_lock_acquisition_failure_refuses_before_facts_with_bounded_error(harness, monkeypatch, capsys, entry):
    from contextlib import contextmanager
    from importlib import import_module

    locking = import_module('harness.telemetry_lock')
    before = tree(harness)

    @contextmanager
    def unavailable(*args):
        raise PermissionError('sensitive-lock-path-must-not-leak')
        yield

    monkeypatch.setattr(locking, 'telemetry_lock', unavailable)
    if entry == 'assess':
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED: cannot inspect recovery state'):
            call_entry(harness, entry)
    else:
        assert call_entry(harness, entry) == 2
        error = capsys.readouterr().err
        assert 'TRANSACTION_RECOVERY_BLOCKED' in error
        assert 'sensitive-lock-path' not in error
    assert tree(harness) == before


def test_admission_does_not_relabel_body_io_failure(harness, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError('actual business-side io failure')

    monkeypatch.setattr(quality_gate, '_evaluate_gate', failed)
    with pytest.raises(OSError, match='actual business-side io failure') as caught:
        quality_gate.assess_gate(harness, allow_preflight=True)
    assert not isinstance(caught.value, transaction_recovery.PublicationAdmissionError)


def test_outer_lock_release_failure_preserves_committed_gate_decision(tmp_path, monkeypatch, capsys):
    import fcntl

    from test_autonomous_convergence import make_repo

    root = make_repo(tmp_path, state='GATING', trusted_scope=True)
    monkeypatch.chdir(tmp_path)
    real = fcntl.flock
    releases = []

    def fail_owner_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            committed_state = yaml.safe_load((root / 'current-task.yaml').read_text())['state']
            assert committed_state in {'CONVERGED', 'BLOCKED', 'ESCALATED'}
            releases.append((fd, committed_state))
            raise OSError('outer unlock failed')
        return real(fd, operation)

    monkeypatch.setattr(fcntl, 'flock', fail_owner_release)
    assert controlplane.cmd_gate() == 0
    captured = capsys.readouterr()
    assert len(releases) == 1, 'must inject actual outer release, not a fake nested lock'
    committed_state = releases[0][1]
    assert committed_state == 'CONVERGED'
    assert 'DECISION: CONVERGED' in captured.out
    assert 'TELEMETRY_UPDATE_FAILED' in captured.err
    assert yaml.safe_load((root / 'current-task.yaml').read_text())['state'] == committed_state


@pytest.mark.parametrize('mode', ['body_io', 'uncommitted_unlock'])
def test_gate_does_not_tolerate_uncommitted_io_as_success(harness, monkeypatch, capsys, mode):
    before = tree(harness)
    if mode == 'body_io':
        def failed():
            raise OSError('body failure, no commit')
        monkeypatch.setattr(controlplane, '_cmd_gate_convergence', failed)
    else:
        import fcntl

        real = fcntl.flock

        def fail_release(fd, operation):
            if operation == fcntl.LOCK_UN:
                raise OSError('uncommitted unlock failure')
            return real(fd, operation)
        monkeypatch.setattr(fcntl, 'flock', fail_release)
    assert controlplane.cmd_gate() == 2
    captured = capsys.readouterr()
    assert 'GATE_IO_FAILED' in captured.err
    assert 'DECISION:' not in captured.out
    assert 'TELEMETRY_UPDATE_FAILED' not in captured.err
    assert tree(harness) == before


@pytest.mark.parametrize('flow', ['classify', 'escalate'])
def test_classification_owner_release_failure_is_bounded(tmp_path, monkeypatch, capsys, flow):
    import fcntl

    from test_cli_task_recovery import make_repo, run_cli
    from test_quality_gate import SAFE_DIMENSIONS

    make_repo(tmp_path)
    subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'anonymous fixture'], cwd=tmp_path, check=True)
    bound = run_cli(tmp_path, 'task', 'migrate-id', 'TASK-001')
    assert bound.returncode == 0, bound.stdout + bound.stderr
    monkeypatch.chdir(tmp_path)
    root = tmp_path / '.harness'
    if flow == 'escalate':
        assert controlplane.cmd_task_classify('Q1', SAFE_DIMENSIONS) == 0
        capsys.readouterr()
    real = fcntl.flock
    releases = []
    owner = None

    def fail_release(fd, operation):
        nonlocal owner
        if operation == fcntl.LOCK_EX and owner is None:
            owner = fd
        if operation == fcntl.LOCK_UN and fd == owner:
            committed = yaml.safe_load((root / 'current-task.yaml').read_text())
            assert committed['state'] == 'CLASSIFIED'
            assert committed['risk']['level'] == ('Q1' if flow == 'classify' else 'Q2')
            releases.append(fd)
            raise OSError(f'{flow} owner unlock failed')
        return real(fd, operation)

    monkeypatch.setattr(fcntl, 'flock', fail_release)
    result = (controlplane.cmd_task_classify('Q1', SAFE_DIMENSIONS) if flow == 'classify' else
              controlplane.cmd_task_escalate('Q2', 'conservative fixture escalation'))
    assert result == 2
    captured = capsys.readouterr()
    assert len(releases) == 1
    code = 'RISK_CLASSIFICATION_INVALID' if flow == 'classify' else 'RISK_ESCALATION_INVALID'
    assert code in captured.err
    assert 'OK:' not in captured.out
    assert yaml.safe_load((root / 'current-task.yaml').read_text())['state'] == 'CLASSIFIED'


@pytest.mark.parametrize('flow', ['classify', 'escalate'])
def test_classification_body_io_is_not_relabelled_as_teardown(harness, monkeypatch, capsys, flow):
    error = OSError('classification body failure')

    def failed(*args):
        raise error

    monkeypatch.setattr(controlplane, f'_cmd_task_{flow}_locked', failed)
    with pytest.raises(OSError) as caught:
        if flow == 'classify':
            controlplane.cmd_task_classify('Q1', {})
        else:
            controlplane.cmd_task_escalate('Q2', 'fixture')
    assert caught.value is error
    assert 'RISK_' not in capsys.readouterr().err


@pytest.mark.parametrize('flow', ['classify', 'escalate'])
def test_classification_success_output_follows_owner_release(tmp_path, monkeypatch, capsys, flow):
    from test_cli_task_recovery import make_repo, run_cli
    from test_quality_gate import SAFE_DIMENSIONS

    from harness.telemetry_lock import _HELD

    make_repo(tmp_path)
    subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'anonymous fixture'], cwd=tmp_path, check=True)
    assert run_cli(tmp_path, 'task', 'migrate-id', 'TASK-001').returncode == 0
    monkeypatch.chdir(tmp_path)
    if flow == 'escalate':
        assert controlplane.cmd_task_classify('Q1', SAFE_DIMENSIONS) == 0
        capsys.readouterr()
    real_print = print
    observed = []

    def checked_print(*args, **kwargs):
        if args and str(args[0]).startswith('OK:'):
            assert str((tmp_path / '.harness').resolve()) not in getattr(_HELD, 'paths', set())
            observed.append(True)
        return real_print(*args, **kwargs)

    monkeypatch.setattr('builtins.print', checked_print)
    result = (controlplane.cmd_task_classify('Q1', SAFE_DIMENSIONS) if flow == 'classify' else
              controlplane.cmd_task_escalate('Q2', 'conservative fixture escalation'))
    assert result == 0
    assert observed == [True]
    expected = 'OK: classified Q1/FAST' if flow == 'classify' else 'OK: escalated to Q2/STANDARD'
    assert expected in capsys.readouterr().out


def test_ordinary_entry_teardown_is_bounded_without_relabelling_body(harness, monkeypatch, capsys):
    import fcntl

    real = fcntl.flock
    injected = []

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            assert yaml.safe_load((harness / 'current-task.yaml').read_text())['state'] == 'IMPLEMENTING'
            injected.append(fd)
            raise OSError('sensitive teardown detail')
        return real(fd, operation)

    monkeypatch.setattr(fcntl, 'flock', failed_release)
    # Transition already committed: teardown is a warning, not a retryable failure.
    assert controlplane.cmd_transition('IMPLEMENTING') == 0
    captured = capsys.readouterr()
    assert len(injected) == 1
    assert 'PUBLICATION_LOCK_TEARDOWN_FAILED' in captured.err
    assert 'sensitive teardown detail' not in captured.err


def test_ordinary_entry_preserves_body_io_error(harness, monkeypatch):
    error = OSError('ordinary body failure')

    def failed(*args):
        raise error

    monkeypatch.setattr(controlplane, 'load_task', failed)
    with pytest.raises(OSError) as caught:
        controlplane.cmd_transition('IMPLEMENTING')
    assert caught.value is error


@pytest.mark.parametrize('case', ['pending', 'body', 'cancellation'])
def test_primary_failure_survives_owner_cleanup_failure(harness, monkeypatch, capsys, case):
    import fcntl

    class Cancelled(BaseException):
        pass

    primary = Cancelled('cancelled') if case == 'cancellation' else OSError('original body failure')
    if case == 'pending':
        directory = harness / '.transactions'
        directory.mkdir(exist_ok=True)
        (directory / 'pending.json').write_bytes(b'unknown owner')
    before = tree(harness)
    real = fcntl.flock
    releases = []

    def fail_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            releases.append(fd)
            raise OSError('sensitive-secondary-cleanup-detail')
        return real(fd, operation)

    def failed_body(*args, **kwargs):
        if case == 'pending':
            raise AssertionError('pending refusal must precede body reads')
        raise primary

    monkeypatch.setattr(fcntl, 'flock', fail_release)
    monkeypatch.setattr(controlplane, 'load_task', failed_body)
    monkeypatch.setattr(quality_gate, '_evaluate_gate', failed_body)
    if case == 'pending':
        assert controlplane.cmd_transition('IMPLEMENTING') == 2
    else:
        with pytest.raises(type(primary)) as caught:
            quality_gate.assess_gate(harness, allow_preflight=True)
        assert caught.value is primary
    assert len(releases) == 1
    error = capsys.readouterr().err
    if case == 'pending':
        assert 'TRANSACTION_RECOVERY_REQUIRED' in error
    assert 'sensitive-secondary-cleanup-detail' not in error
    assert tree(harness) == before


def test_cleanup_warning_io_cannot_mask_primary_error(harness, monkeypatch):
    import fcntl

    primary = OSError('original body error')
    real_flock = fcntl.flock
    real_print = print
    warned = []

    def body(*args, **kwargs):
        raise primary

    def release(fd, operation):
        if operation == fcntl.LOCK_UN:
            raise OSError('secondary release error')
        return real_flock(fd, operation)

    def broken_warning(*args, **kwargs):
        if args and str(args[0]).startswith('PUBLICATION_LOCK_TEARDOWN_FAILED'):
            warned.append(True)
            raise OSError('secondary warning write error')
        return real_print(*args, **kwargs)

    monkeypatch.setattr(quality_gate, '_evaluate_gate', body)
    monkeypatch.setattr(fcntl, 'flock', release)
    monkeypatch.setattr('builtins.print', broken_warning)
    with pytest.raises(OSError) as caught:
        quality_gate.assess_gate(harness, allow_preflight=True)
    assert caught.value is primary
    assert warned == [True]


def wait_for(path):
    import time

    deadline = time.monotonic() + 15
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f'subprocess signal missing: {path.name}')
        time.sleep(.01)


def legacy_maintenance_fixture(tmp_path, monkeypatch, entry):
    """Pre-scope compatibility fixture; never delete a new origin."""
    from harness.init import REQUIRED_DIRS, REQUIRED_FILES
    from harness.templates import templates_dir

    repo = tmp_path / 'legacy'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True, capture_output=True)
    root = repo / '.harness'
    root.mkdir()
    for name in REQUIRED_DIRS:
        (root / name).mkdir()
    for name in REQUIRED_FILES:
        (root / name).write_bytes((templates_dir() / name).read_bytes())
    task = yaml.safe_load((root / 'current-task.yaml').read_text())
    task['task']['id'] = 'TASK-001'
    (root / 'current-task.yaml').write_text(yaml.safe_dump(task))
    (root / 'decisions/index.yaml').write_text('decisions: []\n')
    monkeypatch.chdir(repo)
    if entry == 'init-members':
        from test_decision import proposal

        from harness import decision

        assert decision.propose(root, proposal())['id'] == 'DEC-001'
    if entry == 'init-template':
        (root / 'observability.yaml').unlink()
    elif entry.startswith('init-'):
        (root / 'decisions/index.yaml').unlink()
    return root


def invoke_legacy_maintenance(root, entry):
    from harness.init import init_harness

    before = (root / 'current-task.yaml').read_bytes()
    if entry == 'migrate':
        assert controlplane.cmd_task_migrate_id('TASK-002') == 0
        assert yaml.safe_load((root / 'current-task.yaml').read_text())['task']['id'] == 'TASK-002'
    else:
        result = init_harness(root.parent)
        expected = 'observability.yaml' if entry == 'init-template' else 'index.yaml'
        assert [p.name for p in result.created] == [expected]
        assert (root / 'current-task.yaml').read_bytes() == before
        if entry == 'init-members':
            from harness.decision import load_decision_index

            assert [r['id'] for r in load_decision_index(root)] == ['DEC-001']


@pytest.mark.parametrize('entry,phase', [
    (entry, phase)
    for entry in ('migrate', 'init-template', 'init-empty', 'init-members')
    for phase in ('fact', 'effect')
] + [('migrate', 'pending')])
def test_legacy_maintenance_recovery_owner_covers_use(tmp_path, monkeypatch, capsys, entry, phase):
    """Break caught: legacy branch releases recovery owner before canonical use."""
    import builtins
    import shutil

    from test_test_scope import (
        assert_restored_with_retention,
        file_identities,
        tree_bytes,
    )

    from harness import decision
    from harness._scope_replay import SCOPE_FILES

    root = legacy_maintenance_fixture(tmp_path, monkeypatch, entry)
    healthy = tmp_path / 'healthy'
    shutil.copytree(root.parent, healthy)
    monkeypatch.chdir(healthy)
    invoke_legacy_maintenance(healthy / '.harness', entry)
    assert not any((healthy / '.harness' / name).exists() for name in SCOPE_FILES)
    capsys.readouterr()
    monkeypatch.chdir(root.parent)
    with telemetry_lock(root):
        assert_review_owner(root)
    if phase == 'pending':
        before, identities = tree_bytes(root), file_identities(root)
        script = '''
import os
from pathlib import Path
from harness import publication_fs
from harness.transaction import StagedArtifact,publish,stage
root=Path('.harness');identity=root.stat();original=publication_fs.exchange
artifacts=tuple(StagedArtifact(name,(root/name).read_bytes()) for name in ('gate.yaml','impact.yaml'))
def die_after_gate(*args):
    result=original(*args);held=os.fstat(args[0])
    if args[1]=='gate.yaml' and (held.st_dev,held.st_ino)==(identity.st_dev,identity.st_ino):
        os._exit(87)
    return result
publication_fs.exchange=die_after_gate
publish(root,stage(root,artifacts),replace_paths=frozenset(a.relative_path for a in artifacts),durable=True,
        expected_sources={a.relative_path:a.content for a in artifacts},expected_artifacts=artifacts)
'''
        child = subprocess.run([sys.executable, '-c', script], cwd=root.parent,
                               env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
                               capture_output=True, text=True, check=False, timeout=30)
        assert child.returncode == 87, child.stdout + child.stderr
        journals = list((root / '.transactions').glob('*.json'))
        assert len(journals) == 1 and json.loads(journals[0].read_text())['version'] == 2
        assert (root / 'gate.yaml').read_bytes() == before['gate.yaml']
        assert (root / 'gate.yaml').stat().st_ino != identities['gate.yaml'][1]
        try:
            invoke_legacy_maintenance(root, entry)
            pending_after = list((root / '.transactions').glob('*.json'))
            identity_after = (root / 'gate.yaml').stat().st_ino
        finally:
            with telemetry_lock(root):
                transaction_recovery.recover_pending_publications(root)
        # Identity/telemetry are legitimate command outputs, not journal members.
        # Recovery proof remains exact for gate/impact and every other prior file.
        for name in ('current-task.yaml', 'telemetry.json'):
            path = root / name
            before[name] = path.read_bytes()
            identities[name] = (path.stat().st_dev, path.stat().st_ino)
        assert_restored_with_retention(root, before, identities)
        assert not pending_after and identity_after == identities['gate.yaml'][1], 'legacy migration consumed pending native publication without recovery'
        assert not any((root / name).exists() for name in SCOPE_FILES)
        return

    observed = []
    original_exists, original_write = Path.exists, Path.write_text
    original_save, original_reindex, original_print = controlplane.save_task, decision.reindex, builtins.print

    def owned(label):
        assert_review_owner(root)
        observed.append(label)

    def exists(path):
        if path.absolute().parent == root and path.name in (*SCOPE_FILES, 'current-task.yaml'):
            owned('fact')
        return original_exists(path)

    def write(path, *args, **kwargs):
        if path.absolute() in {root / 'observability.yaml', root / 'decisions/index.yaml'}:
            owned('before-effect')
            value = original_write(path, *args, **kwargs)
            owned('after-effect')
            return value
        return original_write(path, *args, **kwargs)

    def effect(original):
        def call(*args, **kwargs):
            owned('before-effect')
            value = original(*args, **kwargs)
            owned('after-effect')
            return value
        return call

    def render(*args, **kwargs):
        if args and str(args[0]).startswith('OK: task id ->'):
            owned('render')
        return original_print(*args, **kwargs)

    with monkeypatch.context() as hooks:
        if phase == 'fact':
            hooks.setattr(Path, 'exists', exists)
        else:
            hooks.setattr(Path, 'write_text', write)
            hooks.setattr(controlplane, 'save_task', effect(original_save))
            hooks.setattr(decision, 'reindex', effect(original_reindex))
            hooks.setattr(builtins, 'print', render)
        invoke_legacy_maintenance(root, entry)
    assert not any((root / name).exists() for name in SCOPE_FILES)
    assert observed
    if phase == 'effect':
        assert 'before-effect' in observed and 'after-effect' in observed
        if entry == 'migrate':
            assert 'render' in observed


@pytest.mark.parametrize('entry', ['migrate', 'init-template'])
@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('broken_warning', [False, True])
def test_legacy_body_failure_survives_owner_cleanup(tmp_path, monkeypatch, entry, cancel, broken_warning):
    """New owner must not replace primary command error with unlock error."""
    import builtins
    import fcntl

    root = legacy_maintenance_fixture(tmp_path, monkeypatch, entry)
    primary = KeyboardInterrupt() if cancel else OSError('LEGACY_BODY_TEST_FAILURE')
    original_print = builtins.print

    def warning(*args, **kwargs):
        if broken_warning and args and str(args[0]).startswith('PUBLICATION_LOCK_TEARDOWN_FAILED'):
            raise OSError('LEGACY_WARNING_TEST_FAILURE')
        return original_print(*args, **kwargs)

    monkeypatch.setattr(builtins, 'print', warning)
    original_write, original_flock = Path.write_text, fcntl.flock

    def unlock(fd, operation):
        result = original_flock(fd, operation)
        if operation == fcntl.LOCK_UN:
            raise OSError('LEGACY_CLEANUP_TEST_FAILURE')
        return result

    def fail_save(*args, **kwargs):
        raise primary

    def write(path, *args, **kwargs):
        if path == root / 'observability.yaml':
            raise primary
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(fcntl, 'flock', unlock)
    monkeypatch.setattr(controlplane, 'save_task', fail_save)
    monkeypatch.setattr(Path, 'write_text', write)
    with pytest.raises(type(primary)) as raised:
        invoke_legacy_maintenance(root, entry)
    assert raised.value is primary


@pytest.mark.parametrize('entry', ['migrate', 'init-template'])
def test_legacy_recovery_refuses_unknown_private_storage(tmp_path, monkeypatch, capsys, entry):
    from test_test_scope import tree_bytes

    root = legacy_maintenance_fixture(tmp_path, monkeypatch, entry)
    pending = root / '.transactions'
    pending.mkdir()
    (pending / 'unknown-member').write_bytes(b'unknown private object')
    before = tree_bytes(root)
    if entry == 'migrate':
        assert controlplane.cmd_task_migrate_id('TASK-002') == 2
        assert 'TRANSACTION_RECOVERY_BLOCKED' in capsys.readouterr().err
    else:
        from harness.init import init_harness

        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            init_harness(root.parent)
    assert tree_bytes(root) == before


@pytest.mark.parametrize('failure', ['acquire', 'recover', 'binding', 'success'])
def test_legacy_migrate_owner_failure_policy(tmp_path, monkeypatch, capsys, failure):
    """New owner failure exits2; preserve recovery/binding reason over cleanup."""
    import fcntl
    from contextlib import contextmanager
    from importlib import import_module

    root = legacy_maintenance_fixture(tmp_path, monkeypatch, 'migrate')
    original_flock = fcntl.flock
    if failure == 'acquire':
        @contextmanager
        def unavailable(_root):
            raise OSError('LEGACY_ACQUIRE_TEST_FAILURE')
            yield
        monkeypatch.setattr(import_module('harness.telemetry_lock'), 'telemetry_lock', unavailable)
    else:
        if failure == 'recover':
            def blocked(_root):
                raise OSError('TRANSACTION_RECOVERY_BLOCKED: legacy test')
            monkeypatch.setattr(transaction_recovery, 'recover_pending_publications', blocked)
        elif failure == 'binding':
            # Real scope presence chooses audited path, rejected without origin repair.
            (root / 'test-scope-baseline.yaml').write_text('invalid fixture origin\n')

        def unlock(fd, operation):
            value = original_flock(fd, operation)
            if operation == fcntl.LOCK_UN:
                raise OSError('LEGACY_CLEANUP_TEST_FAILURE')
            return value
        monkeypatch.setattr(fcntl, 'flock', unlock)
    assert controlplane.cmd_task_migrate_id('TASK-002') == 2
    output = capsys.readouterr()
    if failure == 'success':
        assert 'PUBLICATION_LOCK_TEARDOWN_FAILED' in output.err
        assert yaml.safe_load((root / 'current-task.yaml').read_text())['task']['id'] == 'TASK-002'
    else:
        assert 'PUBLICATION_LOCK_TEARDOWN_FAILED: command completed' not in output.err
        assert yaml.safe_load((root / 'current-task.yaml').read_text())['task']['id'] == 'TASK-001'
        assert {'acquire': 'LEGACY_ACQUIRE_TEST_FAILURE', 'recover': 'TRANSACTION_RECOVERY_BLOCKED', 'binding': 'test-scope-audit.yaml'}[failure] in output.err
