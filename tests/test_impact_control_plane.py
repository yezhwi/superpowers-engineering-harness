"""TASK-010: persisted impact analysis control plane."""

import subprocess, sys
from pathlib import Path

import pytest
import test_context_builder
import yaml

REPO = Path(__file__).resolve().parent.parent
harness = test_context_builder.harness


@pytest.mark.parametrize('protocol', ['v1', 'v2'])
@pytest.mark.parametrize('action,value', [
    ('add-risk', 'anonymous risk note'),
    ('add-contract', 'anonymous generic contract'),
    ('add-dependent', 'src/client.py'),
    ('add-change', 'src/owned.py'),
])
def test_ordinary_impact_refuses_pending_partial_publication(harness, protocol, action, value):
    """Break caught: supported impact writes strand a partial publication's recovery."""
    from harness import publication_journal, transaction_recovery
    from harness.telemetry_lock import telemetry_lock

    task_path, impact_path = harness / 'current-task.yaml', harness / 'impact.yaml'
    original, impact = task_path.read_bytes(), impact_path.read_bytes()
    task = yaml.safe_load(original)
    task['budget']['context_expansions'] = task['budget'].get('context_expansions', 0) + 1
    partial = yaml.safe_dump(task, sort_keys=False).encode()
    with telemetry_lock(harness):
        if protocol == 'v1':
            transaction_recovery.begin(harness, [(task_path, original, partial),
                                                 (impact_path, impact, impact + b'\n')])
            task_path.write_bytes(partial)
        else:
            with publication_journal.prepare(harness, (
                publication_journal.Member('current-task.yaml', original, partial),
                publication_journal.Member('impact.yaml', impact, impact + b'\n'),
            )) as operation:
                operation._save(state='APPLYING')
                operation._step(0, 'forward')
    before = {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()}
    result = cli(harness.parent, 'impact', action, value)
    after = {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()}
    recovery_error = None
    with telemetry_lock(harness):
        try:
            transaction_recovery.recover_pending_publications(harness)
        except OSError as error:
            recovery_error = str(error)
    changed = [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)]
    assert result.returncode == 2, f'pending impact exit={result.returncode}; changed={changed}; recovery={recovery_error}'
    assert 'TRANSACTION_RECOVERY_REQUIRED' in result.stderr and result.stdout == ''
    assert after == before
    assert recovery_error is None
    assert task_path.read_bytes() == original and impact_path.read_bytes() == impact


@pytest.mark.parametrize('action', ['show', 'scope', 'add-risk', 'add-contract', 'add-dependent',
                                  'add-change', 'add-interface', 'adopt-path', 'ignore-user-path'])
def test_ordinary_impact_pending_refuses_before_first_fact(harness, monkeypatch, capsys, action):
    from harness import controlplane, publication_fs, transaction_recovery

    pending = harness / '.transactions'
    pending.mkdir(exist_ok=True)
    (pending / 'pending.json').write_text('{"version":999,"state":"unknown"}')
    before = {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError('impact canonical fact/recovery/probe before pending refusal')

    monkeypatch.setattr(controlplane, '_impact', forbidden)
    monkeypatch.setattr(controlplane, 'load_task', forbidden)
    monkeypatch.setattr(transaction_recovery, 'recover_pending_publications', forbidden)
    monkeypatch.setattr(publication_fs, 'check_capabilities', forbidden)
    assert controlplane.cmd_impact(action, 'anonymous') == 2
    output = capsys.readouterr()
    assert output.out == '' and 'TRANSACTION_RECOVERY_REQUIRED' in output.err
    assert {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('protocol', ['v1', 'v2'])
def test_impact_add_test_still_recovers_before_scope_reads(harness, protocol):
    from harness import publication_journal, transaction_recovery
    from harness.telemetry_lock import telemetry_lock

    target = harness.parent / 'tests/test_local.py'
    target.parent.mkdir(exist_ok=True)
    target.write_text('def test_local():\n    pass\n')
    task_path, impact_path = harness / 'current-task.yaml', harness / 'impact.yaml'
    original, impact = task_path.read_bytes(), impact_path.read_bytes()
    changed = yaml.safe_load(original)
    changed['budget']['context_expansions'] = 1
    partial = yaml.safe_dump(changed, sort_keys=False).encode()
    with telemetry_lock(harness):
        if protocol == 'v1':
            transaction_recovery.begin(harness, [(task_path, original, partial), (impact_path, impact, impact + b'\n')])
            task_path.write_bytes(partial)
        else:
            with publication_journal.prepare(harness, (
                publication_journal.Member('current-task.yaml', original, partial),
                publication_journal.Member('impact.yaml', impact, impact + b'\n'),
            )) as operation:
                operation._save(state='APPLYING')
                operation._step(0, 'forward')
    result = cli(harness.parent, 'impact', 'add-test', 'tests/test_local.py::test_local')
    assert result.returncode == 0, result.stdout + result.stderr
    assert task_path.read_bytes() == original
    assert yaml.safe_load(impact_path.read_text())['impact']['required_tests'] == ['tests/test_local.py::test_local']
    assert not list((harness / '.transactions').iterdir())


def test_ordinary_impact_teardown_failure_remains_bounded(harness, monkeypatch, capsys):
    import fcntl

    from harness import controlplane, transaction

    real_write, real_flock = transaction.atomic_write, fcntl.flock
    persisted = False
    released = []

    def wrote(path, content):
        nonlocal persisted
        real_write(path, content)
        if path.name == 'impact.yaml':
            persisted = True

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN and persisted:
            released.append(True)
            raise OSError('private-impact-cleanup-data')
        return real_flock(fd, operation)

    monkeypatch.setattr(transaction, 'atomic_write', wrote)
    monkeypatch.setattr(fcntl, 'flock', failed_release)
    assert controlplane.cmd_impact('add-risk', 'persisted risk') == 2
    output = capsys.readouterr()
    assert released == [True] and 'PUBLICATION_LOCK_TEARDOWN_FAILED' in output.err
    assert 'private-impact-cleanup-data' not in output.err
    assert 'persisted risk' in yaml.safe_load((harness / 'impact.yaml').read_text())['impact']['risks']


@pytest.mark.parametrize('primary', [OSError('impact-body-io'), KeyboardInterrupt('impact-cancel')])
def test_ordinary_impact_preserves_primary_over_cleanup(harness, monkeypatch, primary):
    import fcntl

    from harness import controlplane

    real_flock = fcntl.flock
    released = []

    def failed_body():
        raise primary

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            released.append(True)
            raise OSError('private-impact-cleanup-data')
        return real_flock(fd, operation)

    monkeypatch.setattr(controlplane, '_impact', failed_body)
    monkeypatch.setattr(fcntl, 'flock', failed_release)
    with pytest.raises(type(primary)) as error:
        controlplane.cmd_impact('add-risk', 'unused')
    assert error.value is primary and released == [True]


def cli(cwd, *a):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *a],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(p):
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    cli(p, "init")


def test_impact_requires_action_and_does_not_write(tmp_path):
    setup(tmp_path)
    path = tmp_path / ".harness/impact.yaml"
    before = path.read_bytes()
    result = cli(tmp_path, "impact")
    assert result.returncode == 2
    assert path.read_bytes() == before


def test_impact_add_change_and_test(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, 'task', 'migrate-id', 'TASK-010').returncode == 0
    target = tmp_path / 'tests/test_x.py'
    target.parent.mkdir()
    target.write_text('def test_x():\n    pass\n')
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'commit', '-qm', 'fixture baseline'], cwd=tmp_path, check=True)
    classified = cli(tmp_path, 'task', 'classify', '--level', 'Q1', '--scope', 'low', '--contract', 'none',
                     '--data', 'none', '--authorization', 'none', '--security', 'none', '--concurrency', 'none', '--deployment', 'none')
    assert classified.returncode == 0, classified.stderr
    assert cli(tmp_path, "impact", "add-change", "src/x.py").returncode == 0
    assert (
        cli(tmp_path, "impact", "add-test", "tests/test_x.py::test_x").returncode == 0
    )
    d = yaml.safe_load((tmp_path / ".harness/impact.yaml").read_text())
    assert d["impact"]["changed"] == ["src/x.py"] and d["impact"]["required_tests"]
    assert yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())[
        "scope"
    ]["owned_paths"] == ["src/x.py"]


def test_scope_migrates_legacy_impact_changed_without_adopting_workspace(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, "impact", "add-change", "src/legacy.py").returncode == 0
    task = yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())
    task.pop("scope", None)
    (tmp_path / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    assert cli(tmp_path, "impact", "scope", "--format", "yaml").returncode == 0
    assert yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())[
        "scope"
    ]["owned_paths"] == ["src/legacy.py"]


def test_impact_adopted_path_enters_scope_but_protected_path_does_not(tmp_path):
    setup(tmp_path)
    task = yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())
    task["scope"] = {"owned_paths": [], "protected_user_paths": ["docs/user.md"]}
    (tmp_path / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    assert cli(tmp_path, "impact", "adopt-path", "src/x.py").returncode == 0
    result = cli(tmp_path, "impact", "scope", "--format", "yaml")
    assert result.returncode == 0
    scope = yaml.safe_load(result.stdout)
    assert scope["owned_paths"] == ["src/x.py"]
    assert "docs/user.md" not in scope["effective_scope"]


def test_impact_adopt_protected_v2_path_updates_scope_and_snapshot(tmp_path):
    setup(tmp_path)
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["scope"] = {"owned_paths": [], "protected_user_paths": ["src/x.py"]}
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": {"scope": "low", "contract": "none", "data": "none", "authorization": "none", "security": "none", "concurrency": "none", "deployment": "none"},
        "escalation_history": [],
        "user_changes": {"version": 2, "paths": ["src/x.py"], "path_fingerprints": {"src/x.py": "sha256:" + "a" * 64}, "fingerprint": "sha256:" + "b" * 64},
    }
    task_path.write_text(yaml.safe_dump(task))

    assert cli(tmp_path, "impact", "adopt-path", "src/x.py").returncode == 0

    adopted = yaml.safe_load(task_path.read_text())
    assert adopted["scope"] == {"owned_paths": ["src/x.py"], "protected_user_paths": []}
    assert adopted["risk"]["user_changes"]["paths"] == []
    assert adopted["risk"]["user_changes"]["path_fingerprints"] == {}


def test_impact_adopt_rejects_stale_v1_snapshot_without_writing(tmp_path):
    setup(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    user_path = tmp_path / "src" / "x.py"
    user_path.parent.mkdir()
    user_path.write_text("value = 1\n")
    subprocess.run(["git", "add", "src/x.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    user_path.write_text("value = 2\n")
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["scope"] = {"owned_paths": [], "protected_user_paths": ["src/x.py"]}
    task["risk"] = {
        "level": "Q1", "profile": "FAST",
        "dimensions": {"scope": "low", "contract": "none", "data": "none", "authorization": "none", "security": "none", "concurrency": "none", "deployment": "none"},
        "escalation_history": [],
        "user_changes": {"paths": ["src/x.py"], "fingerprint": "sha256:" + "0" * 64},
    }
    task_path.write_text(yaml.safe_dump(task))
    before = task_path.read_bytes()

    result = cli(tmp_path, "impact", "adopt-path", "src/x.py")

    assert result.returncode == 1
    assert result.stderr == "USER_CHANGE_BASELINE_STALE\n"
    assert task_path.read_bytes() == before


def test_impact_rejects_removed_full_suite_action(tmp_path):
    setup(tmp_path)
    result = cli(
        tmp_path, "impact", "require-full-suite", "--reason", "state boundary"
    )
    assert result.returncode == 2


def test_q1_external_interface_requires_explicit_escalation(tmp_path):
    setup(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    flags = [
        item
        for pair in {
            "scope": "low",
            "contract": "none",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        }.items()
        for item in (f"--{pair[0]}", pair[1])
    ]
    assert cli(tmp_path, "task", "classify", "--level", "Q1", *flags).returncode == 0
    result = cli(
        tmp_path,
        "impact",
        "add-interface",
        "INT-001",
        "--kind",
        "cli",
        "--consumer",
        "agent",
        "--compatibility",
        "compatible",
    )
    assert result.returncode == 1
    assert "PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED" in result.stderr


def test_owned_path_cannot_be_protected_or_revoked(tmp_path):
    setup(tmp_path)
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["scope"] = {"owned_paths": [], "protected_user_paths": ["src/x.py"]}
    task_path.write_text(yaml.safe_dump(task))

    assert cli(tmp_path, "impact", "add-change", "src/x.py").returncode == 0
    ignored = cli(tmp_path, "impact", "ignore-user-path", "src/x.py")
    assert ignored.returncode == 1
    assert "PROTECTED_PATH_OWNED" in ignored.stderr

    scope = yaml.safe_load(cli(tmp_path, "impact", "scope", "--format", "yaml").stdout)
    assert scope["owned_paths"] == ["src/x.py"]
    assert "src/x.py" not in scope["protected_user_paths"]
    assert scope["effective_scope"] == ["src/x.py"]


def test_project_task_scope_includes_inspected_paths_and_excludes_protected_paths():
    from harness.workspace import project_task_scope

    task = {
        "scope": {
            "owned_paths": ["src/owned.py"],
            "protected_user_paths": ["docs/user.md"],
        }
    }
    impact = {
        "contracts": ["src/contract.py"],
        "direct_dependents": ["src/dependent.py"],
    }
    assert project_task_scope(task, impact, inspected_paths=["src/inspected.py"]) == (
        "src/contract.py",
        "src/dependent.py",
        "src/inspected.py",
        "src/owned.py",
    )


def test_project_task_scope_keeps_owned_and_contract_when_also_protected():
    from harness.workspace import project_task_scope

    task = {
        "scope": {
            "owned_paths": ["src/api.py"],
            "protected_user_paths": ["src/api.py", "src/contract.py"],
        }
    }
    impact = {"contracts": ["src/contract.py"]}
    assert project_task_scope(task, impact) == ("src/api.py", "src/contract.py")


def test_project_typed_scope_separates_contract_labels_from_files():
    from harness.workspace import claimed_scope_sets, project_typed_scope

    task = {"scope": {"owned_paths": ["src/owned.py"], "protected_user_paths": []}}
    impact = {"contracts": ["DEC-001:orders", "src/contract.py", {"ref": "DEC-002", "kind": "permission"}]}
    files, refs = project_typed_scope(task, impact)
    assert files == ("src/contract.py", "src/owned.py")
    assert refs == ("DEC-001:orders", "DEC-002")
    migrated_files, migrated_refs = claimed_scope_sets(
        {"files": ["src/owned.py", "DEC-001:orders", "src/contract.py"]}
    )
    assert migrated_files == files
    assert migrated_refs == ("DEC-001:orders",)
