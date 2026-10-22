"""EF-T06/07: restart recovery survives staging cleanup and never reverts user bytes."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import publication_fs, transaction
from harness.telemetry_lock import telemetry_lock


@pytest.mark.parametrize('members', [
    ('current-task.yaml', 'context/expansions.yaml'),
    ('impact.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml'),
    ('context/current.yaml', 'context/manifest.yaml', 'context/evidence.yaml'),
])
def test_recovery_after_process_kill_survives_staging_cleanup(tmp_path, members):
    root = tmp_path / '.harness'
    root.mkdir()
    for name in members:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'old')
    repo = Path(__file__).resolve().parents[1]
    # Kill at real native member publication; stage retirement cannot affect journal.
    script = '''
import os
from pathlib import Path
from harness import publication_fs, transaction
from harness.telemetry_lock import telemetry_lock
root = Path(ROOT)
members = MEMBERS
staged = transaction.stage(root, [transaction.StagedArtifact(n, b'new') for n in members])
original = publication_fs.exchange
def killed(*args):
    result = original(*args)
    if args[1] == Path(members[0]).name:
        os._exit(91)
    return result
publication_fs.exchange = killed
with telemetry_lock(root):
    transaction.publish(root, staged, replace_paths=frozenset(members), durable=True)
'''.replace('ROOT', repr(str(root))).replace('MEMBERS', repr(members))
    result = subprocess.run([sys.executable, '-c', script], env={**os.environ, 'PYTHONPATH': str(repo / 'src')}, capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode == 91, result.stderr
    assert any((root / '.transactions').iterdir())
    transaction.cleanup_stale_staging(root)
    with telemetry_lock(root):
        transaction.recover_pending_publications(root)
    assert [(root / name).read_bytes() for name in members] == [b'old'] * len(members)
    assert not list((root / '.transactions').iterdir())


@pytest.mark.parametrize('durable', [False, True])
def test_post_check_external_edit_is_not_destroyed_by_replace(tmp_path, monkeypatch, durable):
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'current-task.yaml'
    target.write_bytes(b'original task')
    staged = transaction.stage(root, [transaction.StagedArtifact('current-task.yaml', b'published task')])
    replace = Path.replace
    exchange = publication_fs.exchange
    inode = target.stat().st_ino
    injected = False

    def operator_edit_at_replace(path, destination):
        nonlocal injected
        if Path(destination) == target and not injected:
            injected = True
            target.write_bytes(b'unmanaged operator task')
        return replace(path, destination)

    def operator_edit_at_exchange(*args):
        nonlocal injected
        if 'current-task.yaml' in args and not injected:
            injected = True
            target.write_bytes(b'unmanaged operator task')
        return exchange(*args)

    monkeypatch.setattr(Path, 'replace', operator_edit_at_replace)
    monkeypatch.setattr(publication_fs, 'exchange', operator_edit_at_exchange)
    error = None
    with telemetry_lock(root):
        try:
            transaction.publish(root, staged, replace_paths=frozenset({'current-task.yaml'}),
                                expected_sources={'current-task.yaml': b'original task'}, durable=durable)
        except OSError as exc:
            error = exc
    assert injected, 'race injection must execute at actual replacement boundary'
    kept = [path for path in root.rglob('*') if path.is_file()
            and path.stat().st_ino == inode and path.read_bytes() == b'unmanaged operator task']
    assert len(kept) == 1, 'unmanaged actual inode must survive canonically or at retained location'
    assert error is not None, 'unmanaged race must halt publication, not report success'


@pytest.mark.parametrize('durable', [False, True])
def test_failure_rollback_does_not_overwrite_unmanaged_edit(tmp_path, durable):
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'old')
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'ours')])
    def user_edit_then_fail():
        target.write_bytes(b'user bytes')
        raise OSError('publication failed')
    with telemetry_lock(root), pytest.raises(OSError):
        transaction.publish(root, staged, replace_paths=frozenset({'impact.yaml'}), after_publish=user_edit_then_fail, durable=durable)
    assert target.read_bytes() == b'user bytes'
    if durable:
        with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            transaction.recover_pending_publications(root)
        assert target.read_bytes() == b'user bytes'


def test_rollback_restores_owned_sibling_without_following_user_symlink(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    task = root / 'current-task.yaml'
    log = root / 'expansions.yaml'
    task.write_bytes(b'old task')
    log.write_bytes(b'old log')
    user = tmp_path / 'user'
    user.write_bytes(b'user bytes')
    staged = transaction.stage(root, [transaction.StagedArtifact('current-task.yaml', b'new task'),
                                      transaction.StagedArtifact('expansions.yaml', b'new log')])
    def user_symlink():
        task.unlink()
        task.symlink_to(user)
        raise OSError('publication failed')
    with telemetry_lock(root), pytest.raises(OSError):
        transaction.publish(root, staged, replace_paths=frozenset({'current-task.yaml', 'expansions.yaml'}), after_publish=user_symlink, durable=True)
    assert user.read_bytes() == b'user bytes'
    assert task.is_symlink()
    assert log.read_bytes() == b'old log'
    assert list((root / '.transactions').iterdir())


def test_keyboardinterrupt_rolls_back_owned_members(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'old')
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'ours')])
    def interrupt():
        raise KeyboardInterrupt
    with telemetry_lock(root), pytest.raises(KeyboardInterrupt):
        transaction.publish(root, staged, replace_paths=frozenset({'impact.yaml'}), after_publish=interrupt, durable=True)
    assert target.read_bytes() == b'old'
    assert not list((root / '.transactions').iterdir())


def test_committed_publication_recovery_is_idempotent(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'new')])
    with telemetry_lock(root):
        transaction.publish(root, staged, durable=True)
        transaction.recover_pending_publications(root)
        transaction.recover_pending_publications(root)
    assert (root / 'impact.yaml').read_bytes() == b'new'


@pytest.mark.parametrize('attack', ['symlink', 'invalid_json', 'unknown_member'])
def test_invalid_journal_stops_without_cleaning_user_bytes(tmp_path, attack):
    root = tmp_path / '.harness'
    root.mkdir()
    directory = root / '.transactions'
    directory.mkdir()
    target = directory / 'operation.json'
    if attack == 'symlink':
        outside = tmp_path / 'user'
        outside.write_bytes(b'user bytes')
        target.symlink_to(outside)
    elif attack == 'invalid_json':
        target.write_bytes(b'{broken')
    else:
        target.write_bytes(b'{"version":1,"state":"PREPARED","members":[{"path":"../escape"}]}')
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction.recover_pending_publications(root)
    assert target.exists()
    if attack == 'symlink':
        assert outside.read_bytes() == b'user bytes'
def _prepared_candidate_intent(tmp_path, monkeypatch, *, gate_bound=False):
    """Trusted historical Gate metadata for isolated journal tests, NOT a CLI E2E."""
    import base64
    import hashlib
    import json
    import yaml
    from harness.candidate_commit import prepare
    from harness.git_mutation import commit_tree, repository_policy

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
    def digest(raw):
        return "sha256:" + hashlib.sha256(raw).hexdigest()
    def encoded(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.com")
    (repo / "a.py").write_text("value = 1\n")
    git("add", "a.py")
    git("commit", "-qm", "base")
    parent = git("rev-parse", "HEAD")
    (repo / "a.py").write_text("value = 2\n")
    git("add", "a.py")
    root = repo / ".harness"
    root.mkdir()
    task = {"task": {"id": "TASK-1", "type": "feature"}, "state": "IMPLEMENTING",
            "scope": {"owned_paths": ["a.py"], "protected_user_paths": []},
            "gate": {}, "authorizations": {"commit": {"granted": False}}}
    (root / "current-task.yaml").write_text(yaml.safe_dump(task))
    (root / "gate.yaml").write_text(yaml.safe_dump({"gate": {"candidate_commit": {
        "format": "candidate-commit/v1", "capability_version": 1, "minimum_reader": "0.3.2"}}}))
    prepared = prepare(repo, ["a.py"])
    candidate = json.loads((repo / prepared["record"]).read_text())
    acceptance = {"schema": "candidate-acceptance/v1", "domain": "harness:candidate-acceptance:v1",
                  "assessment_domain": "harness:candidate-assessment:v1", "candidate_id": prepared["candidate"],
                  "parent_commit": parent, "candidate_tree": candidate["candidate_tree"],
                  "export_fingerprint": "sha256:" + "2" * 64, "proof_ids": ["sha256:" + "3" * 64],
                  "review_ids": ["sha256:" + str(n) * 64 for n in (4, 5, 6)],
                  "evidence_refs": [f".harness/evidence/candidate-proof/{'3' * 64}.json"] +
                                   [f".harness/evidence/candidate-review/{str(n) * 64}.json" for n in (4, 5, 6)],
                  "semantic_sources": candidate["semantic_sources"], "gate": "PASS", "gate_blockers": []}
    for reference in acceptance["evidence_refs"]:
        source = repo / reference
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('{"fixture":"trusted prior Gate input"}')
    if gate_bound:
        from harness.candidate_commit import _gate_sources
        acceptance["gate_sources"] = _gate_sources(repo, acceptance["evidence_refs"])
    acceptance_id = digest(b"harness:candidate-acceptance:v1\0" + encoded(acceptance))
    acceptance["acceptance_id"] = acceptance_id
    acceptance_path = root / "evidence/candidate-acceptance" / (acceptance_id[7:] + ".json")
    acceptance_path.parent.mkdir()
    acceptance_path.write_bytes(encoded(acceptance))
    message = b"candidate\n"
    identity = {f"GIT_{role}_{key}": value for role in ("AUTHOR", "COMMITTER")
                for key, value in (("NAME", "Fixture"), ("EMAIL", "fixture@example.com"),
                                   ("DATE", "2026-01-01T00:00:00+00:00"))}
    proposed = commit_tree(repo, candidate["candidate_tree"], parent, message, identity)
    payload = {"task_id": "TASK-1", "candidate_id": prepared["candidate"], "acceptance_id": acceptance_id,
               "parent": parent, "tree": candidate["candidate_tree"], "full_ref": "refs/heads/main",
               "proposed": proposed, "identity": identity, "message_base64": base64.b64encode(message).decode(),
               "message_sha256": digest(message), "git_policy": repository_policy(repo),
               "grant_receipt": digest(b"fixture historical explicit grant"),
               "accepted_sources": {str(path.relative_to(root)): digest(path.read_bytes())
                                    for path in (repo / prepared["record"], acceptance_path,
                                                 *(repo / reference for reference in acceptance['evidence_refs']))}}
    identifier = digest(b"harness:candidate-operation:v1\0" + encoded(payload))
    operation = {"schema": "candidate-operation/v1", "domain": "harness:candidate-operation:v1",
                 "operation_id": identifier, "payload": payload, "phase": "REF_CAS_STARTED",
                 "mutation_started": True, "grant_consumed": True}
    directory = root / ".candidate-operations"
    directory.mkdir(mode=0o700)
    path = directory / (identifier[7:] + ".json")
    path.write_bytes(encoded(operation))
    path.chmod(0o600)
    task["state"] = "DONE"
    task["gate"] = {"status": "PASS"}
    (root / "current-task.yaml").write_text(yaml.safe_dump(task))
    return repo, operation, path, task


@pytest.mark.parametrize('field,value', [
    ('domain', 'foreign-domain/v1'), ('acceptance_id', 'sha256:' + 'f' * 64),
    ('parent', 'f' * 40), ('unknown', True), ('postcheck_input_consistent', 'yes'),
])
def test_terminal_candidate_trace_requires_full_schema_and_captured_identity(tmp_path, monkeypatch, field, value):
    import json
    from harness.candidate_commit import CandidateRefusal, recover, status
    from harness.git_mutation import update_ref
    from harness.transaction_recovery import candidate_operations

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    payload = operation['payload']
    update_ref(repo, payload['full_ref'], payload['proposed'], payload['parent'])
    result = recover(repo, operation['operation_id'])
    trace_path = repo / result['trace']
    trace = json.loads(trace_path.read_text())
    trace[field] = value
    trace_path.write_text(json.dumps(trace))
    operation_bytes = path.read_bytes()
    with pytest.raises(OSError, match='candidate record invalid'):
        candidate_operations(repo / '.harness')
    with pytest.raises(CandidateRefusal, match='RECOVERY_UNSUPPORTED'):
        status(repo, payload['candidate_id'])
    assert path.read_bytes() == operation_bytes
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip() == payload['proposed']


def test_candidate_recovery_finishes_trace_without_grant_or_second_cas(tmp_path, monkeypatch):
    import json
    from harness import git_mutation
    from harness.candidate_commit import recover

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    payload = operation["payload"]
    git_mutation.update_ref(repo, payload["full_ref"], payload["proposed"], payload["parent"])
    (repo / "a.py").write_text("later legitimate user edit\n")
    def forbidden_cas(*args):
        pytest.fail("published ref must not be mutated again")
    monkeypatch.setattr(git_mutation, "update_ref", forbidden_cas)
    try:
        first = recover(repo, operation["operation_id"])
    except (KeyError, ValueError) as exc:
        pytest.fail(f"durable candidate protocol is not supported: {type(exc).__name__}")
    assert first["status"] == "RECOVERED"
    trace_path = repo / ".harness/evidence/candidate-trace" / (operation["operation_id"][7:] + ".json")
    trace = trace_path.read_bytes()
    assert json.loads(trace)["historical_acceptance"] is True
    assert json.loads(path.read_text())["phase"] == "TRACE_PUBLISHED"
    assert recover(repo, operation["operation_id"])["proposed"] == payload["proposed"]
    assert trace_path.read_bytes() == trace
    assert (repo / "a.py").read_text() == "later legitimate user edit\n"
    assert task["authorizations"]["commit"]["granted"] is False


def test_candidate_acceptance_binds_scope_baseline_even_when_initially_absent(tmp_path, monkeypatch):
    import json
    from harness.candidate_commit import CandidateRefusal, _commit_acceptance

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch, gate_bound=True)
    identifier = operation['payload']['candidate_id']
    candidate_path = repo / '.harness/evidence/candidate-prepared' / (identifier[7:] + '.json')
    candidate = json.loads(candidate_path.read_text())
    _commit_acceptance(repo, candidate)
    (repo / '.harness/test-scope-baseline.yaml').write_text('version: 1\nchanged: true\n')
    with pytest.raises(CandidateRefusal, match='CANDIDATE_GATE_BLOCKED'):
        _commit_acceptance(repo, candidate)


def test_candidate_commit_requires_captured_gate_sources_before_any_git_mutation(tmp_path, monkeypatch):
    import yaml
    from harness.candidate_commit import CandidateRefusal, controlled_commit

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    path.unlink()  # This unit tests initial operation creation, not retry.
    task["authorizations"]["commit"] = {"granted": True, "source": "user", "granted_at": "2026-01-01T00:00:00+00:00"}
    (repo / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    message = tmp_path / "message.txt"
    message.write_text("candidate\n")
    index = (repo / ".git/index").read_bytes()
    with pytest.raises(CandidateRefusal, match="CANDIDATE_GATE_BLOCKED"):
        controlled_commit(repo, operation["payload"]["candidate_id"], message)
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() == operation["payload"]["parent"]
    assert (repo / ".git/index").read_bytes() == index
    assert not list(path.parent.iterdir())


@pytest.mark.parametrize('source', [None, 'agent', 'imported'])
def test_candidate_ref_old_recovery_requires_user_authority_source(tmp_path, monkeypatch, source):
    import yaml
    from harness.candidate_commit import CandidateRefusal, recover

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch, gate_bound=True)
    task['authorizations']['commit'] = {'granted': True, 'source': source,
                                      'granted_at': '2026-01-01T00:00:00+00:00'}
    (repo / '.harness/current-task.yaml').write_text(yaml.safe_dump(task))
    before = path.read_bytes()
    index = (repo / '.git/index').read_bytes()
    with pytest.raises(CandidateRefusal, match='USER_AUTHORITY_REQUIRED'):
        recover(repo, operation['operation_id'])
    assert path.read_bytes() == before
    assert (repo / '.git/index').read_bytes() == index
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip() == operation['payload']['parent']


def test_candidate_recovery_pre_cas_requires_regrant_and_preserves_foreign_ref(tmp_path, monkeypatch):
    from harness.candidate_commit import CandidateRefusal, recover

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    with pytest.raises(CandidateRefusal, match="USER_AUTHORITY_REQUIRED"):
        recover(repo, operation["operation_id"])
    original = path.read_bytes()
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "foreign"], cwd=repo, check=True)
    foreign = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    with pytest.raises(CandidateRefusal, match="RECOVERY_UNSUPPORTED"):
        recover(repo, operation["operation_id"])
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() == foreign
    assert path.read_bytes() == original


def test_pending_candidate_allows_only_same_task_commit_authority_metadata(tmp_path, monkeypatch):
    import yaml
    from harness import controlplane

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo)
    assert controlplane.cmd_authorize("commit", True) == 0
    current = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert current["authorizations"]["commit"]["granted"] is True
    assert controlplane.cmd_authorize("push", True) == 2
    assert controlplane.cmd_authorize("commit", False) == 0
    current = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert current["authorizations"]["commit"]["granted"] is False
    assert current["authorizations"]["push"]["granted"] is False
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo) == before
    assert path.exists()


def test_candidate_commit_is_one_fixed_payload_and_never_writes_index(tmp_path, monkeypatch):
    import json
    import yaml
    from harness.candidate_commit import CandidateRefusal, controlled_commit

    repo, historical, path, task = _prepared_candidate_intent(tmp_path, monkeypatch, gate_bound=True)
    path.unlink()
    task["authorizations"]["commit"] = {"granted": True, "source": "user", "granted_at": "2026-01-01T00:00:00+00:00"}
    (repo / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    message = tmp_path / "message.txt"
    message.write_text("real controlled candidate\n")
    index = (repo / ".git/index").read_bytes()
    result = controlled_commit(repo, historical["payload"]["candidate_id"], message)
    assert result["status"] == "COMMITTED"
    assert (repo / ".git/index").read_bytes() == index
    commit = subprocess.check_output(["git", "show", "-s", "--format=%an <%ae>", result["proposed"]], cwd=repo, text=True).strip()
    assert commit == "Fixture <fixture@example.com>"
    operation = json.loads((path.parent / (result["operation"][7:] + ".json")).read_text())
    assert operation["phase"] == "TRACE_PUBLISHED"
    assert operation["grant_consumed"] is True
    assert yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["authorizations"]["commit"]["granted"] is False
    assert controlled_commit(repo, historical["payload"]["candidate_id"], message)["proposed"] == result["proposed"]
    message.write_text("different message\n")
    with pytest.raises(CandidateRefusal, match="CANDIDATE_RECORD_CONFLICT"):
        controlled_commit(repo, historical["payload"]["candidate_id"], message)


def test_candidate_post_cas_publication_failure_reports_truth_without_rollback(tmp_path, monkeypatch):
    from harness import candidate_commit, git_mutation
    from harness.candidate_commit import CandidateRefusal, recover

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    payload = operation["payload"]
    git_mutation.update_ref(repo, payload["full_ref"], payload["proposed"], payload["parent"])
    original = candidate_commit._publish_documents
    def failed_trace(*args):
        raise OSError("secret /private/operator-path token=PRIVATE")
    monkeypatch.setattr(candidate_commit, "_publish_documents", failed_trace)
    with pytest.raises(CandidateRefusal, match="^REF_PUBLISHED_POSTCHECK_FAILED$"):
        recover(repo, operation["operation_id"])
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() == payload["proposed"]
    monkeypatch.setattr(candidate_commit, "_publish_documents", original)
    assert recover(repo, operation["operation_id"])["proposed"] == payload["proposed"]


@pytest.mark.parametrize("corruption", ["phase_flags", "missing_trace"])
def test_candidate_admission_rejects_inconsistent_terminal_record(tmp_path, monkeypatch, corruption):
    import json
    from harness.transaction_recovery import publication_admission

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    if corruption == "phase_flags":
        operation["mutation_started"] = False
    else:
        operation["phase"] = "TRACE_PUBLISHED"
    path.write_text(json.dumps(operation))
    with pytest.raises(OSError, match="TRANSACTION_RECOVERY_BLOCKED"):
        with publication_admission(repo / ".harness"):
            pytest.fail("corrupt candidate operation admitted")


def test_task_replacement_archives_terminal_candidate_with_its_task(tmp_path, monkeypatch):
    from harness import controlplane
    from harness.candidate_commit import recover
    from harness.git_mutation import update_ref

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    payload = operation["payload"]
    update_ref(repo, payload["full_ref"], payload["proposed"], payload["parent"])
    result = recover(repo, operation["operation_id"])
    original = path.read_bytes()
    monkeypatch.chdir(repo)
    assert controlplane.cmd_task_new("TASK-2", "next") == 0
    archives = list((repo / ".harness/history").glob("TASK-1-*"))
    assert len(archives) == 1
    archived = archives[0] / ".candidate-operations" / path.name
    assert archived.read_bytes() == original
    assert (archives[0] / result["trace"].removeprefix(".harness/")).is_file()
    assert not list((repo / ".harness/.candidate-operations").glob("*.json"))


def test_candidate_status_uses_known_operation_not_trace_presence_and_is_read_only(tmp_path, monkeypatch):
    import json
    import hashlib
    from harness.candidate_commit import status

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    trace = repo / ".harness/evidence/candidate-trace/fake.json"
    trace.parent.mkdir()
    trace.write_text(json.dumps({"candidate_id": operation["payload"]["candidate_id"],
                                 "proposed": operation["payload"]["parent"]}))
    def metadata():
        return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (repo / ".harness").rglob("*") if p.is_file()}
    before = metadata()
    result = status(repo, operation["payload"]["candidate_id"])
    assert result["historically_committed"] is False
    assert result["live_proposed"] is False
    assert metadata() == before


def test_candidate_recovery_never_blesses_unqualified_matching_ref(tmp_path):
    import json
    from harness.candidate_commit import CandidateRefusal, recover

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "base"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    identifier = "sha256:" + "1" * 64
    directory = tmp_path / ".harness/.candidate-operations"
    directory.mkdir(parents=True)
    (directory / (identifier[7:] + ".json")).write_text(json.dumps({
        "operation_id": identifier, "full_ref": "refs/heads/main", "parent": head,
        "proposed": head, "phase": "REF_CAS_STARTED",
    }))
    with pytest.raises(CandidateRefusal, match="RECOVERY_UNSUPPORTED"):
        recover(tmp_path, identifier)
    assert not (tmp_path / ".harness/evidence/candidate-trace").exists()


@pytest.mark.parametrize("entry", ["unknown", "invalid_json", "symlink", "fifo"])
def test_candidate_pending_admission_blocks_mutators_and_legacy_recovery(tmp_path, entry):
    from harness.transaction_recovery import publication_admission, publication_recovery

    root = tmp_path / ".harness"
    directory = root / ".candidate-operations"
    directory.mkdir(parents=True)
    record = directory / ("1" * 64 + ".json")
    if entry == "fifo":
        os.mkfifo(record)
    elif entry == "symlink":
        outside = tmp_path / "untouched"
        outside.write_bytes(b"private user bytes")
        record.symlink_to(outside)
    else:
        record.write_text('{"schema":"candidate-operation/v999"}' if entry == "unknown" else "{")
    for entrypoint in (publication_admission, publication_recovery):
        with pytest.raises(OSError, match="TRANSACTION_RECOVERY_"):
            with entrypoint(root):
                pytest.fail("pending candidate operation admitted ordinary mutation")
    assert record.lstat()


@pytest.mark.parametrize("cut", ["before_ref", "after_ref", "trace", "trace_member"])
def test_candidate_commit_recovers_two_resource_cut_points_without_false_rollback(tmp_path, monkeypatch, cut):
    import json
    import yaml
    from harness import controlplane
    from harness.candidate_commit import CandidateRefusal, recover

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch, gate_bound=True)
    task["authorizations"]["commit"] = {"granted": True, "source": "user", "granted_at": "2026-01-01T00:00:00+00:00"}
    (repo / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    index = (repo / ".git/index").read_bytes()
    script = '''
import os, sys
from pathlib import Path
from harness import candidate_commit, git_mutation
root, identifier, cut = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
original = git_mutation.update_ref
def killed_ref(*args):
    if cut == 'before_ref':
        os._exit(91)
    original(*args)
    if cut == 'after_ref':
        os._exit(91)
git_mutation.update_ref = killed_ref
publish = candidate_commit._publish_documents
tracing = [False]
def killed_trace(root, documents):
    if any(name.startswith('evidence/candidate-trace/') for name in documents):
        if cut == 'trace':
            os._exit(91)
        tracing[0] = True
    return publish(root, documents)
if cut in {'trace', 'trace_member'}:
    candidate_commit._publish_documents = killed_trace
if cut == 'trace_member':
    from harness import publication_fs
    exchange = publication_fs.exchange
    def killed_member(*args):
        result = exchange(*args)
        if tracing[0] and args[1] == identifier[7:] + '.json':
            os._exit(91)
        return result
    publication_fs.exchange = killed_member
candidate_commit.recover(root, identifier)
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.run([sys.executable, "-c", script, str(repo), operation["operation_id"], cut],
                           env=env, capture_output=True, text=True, timeout=30)
    assert child.returncode == 91, child.stderr
    expected_phase = "TRACE_PUBLISHED" if cut == "trace_member" else "REF_CAS_STARTED"
    assert json.loads(path.read_text())["phase"] == expected_phase
    assert yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["authorizations"]["commit"]["granted"] is False
    if cut == "before_ref":
        with pytest.raises(CandidateRefusal, match="USER_AUTHORITY_REQUIRED"):
            recover(repo, operation["operation_id"])
        monkeypatch.chdir(repo)
        assert controlplane.cmd_authorize("commit", True) == 0
    result = recover(repo, operation["operation_id"])
    assert result["proposed"] == operation["payload"]["proposed"]
    assert json.loads(path.read_text())["phase"] == "TRACE_PUBLISHED"
    assert (repo / ".git/index").read_bytes() == index
    assert subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=repo, text=True).strip() == "2"


def test_candidate_operation_is_idempotent_across_cas_and_recovery(tmp_path, monkeypatch):
    from harness.candidate_commit import recover
    from harness.git_mutation import update_ref

    repo, operation, path, task = _prepared_candidate_intent(tmp_path, monkeypatch)
    payload = operation["payload"]
    update_ref(repo, payload["full_ref"], payload["proposed"], payload["parent"])
    first = recover(repo, operation["operation_id"])
    trace = (repo / first["trace"]).read_bytes()
    assert recover(repo, operation["operation_id"])["proposed"] == payload["proposed"]
    assert (repo / first["trace"]).read_bytes() == trace
