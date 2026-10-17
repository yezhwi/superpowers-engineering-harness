"""Whole-working-diff candidates: native behavior before any implementation fix."""

import errno
import json
import os

import pytest
import test_context_builder

from harness import controlplane, publication_journal, transaction
from harness.context.store import generate_context, load_context

harness = test_context_builder.harness


@pytest.mark.parametrize("fault", ["healthy", "before_commit", "after_commit"])
def test_context_reports_actual_commit_after_archive_failure(harness, monkeypatch, tmp_path, capsys, fault):
    """FND029: retained terminal journal is authority, not publish return."""
    generate_context(harness)
    current = harness / "context/current.yaml"
    original_inode = current.stat().st_ino
    original_bytes = current.read_bytes()
    output = tmp_path.parent / f"{tmp_path.name}-review-profile.json"
    commit = publication_journal.Operation.commit
    retain = transaction._retain_stage
    events = []

    def committed(operation):
        if fault == "before_commit":
            events.append("before_commit")
            raise OSError(errno.ENOSPC, "fixture before native commit")
        result = commit(operation)
        assert operation.document["state"] == "COMMITTED"
        assert operation.finished
        assert not list((harness / ".transactions").iterdir())
        events.append("committed")
        return result

    def archive(root, stage, **kwargs):
        assert events == ["committed"]
        if fault == "after_commit":
            events.append("archive_failed")
            raise OSError(errno.ENOSPC, "fixture stage archival after native commit")
        return retain(root, stage, **kwargs)

    monkeypatch.setattr(publication_journal.Operation, "commit", committed)
    monkeypatch.setattr(transaction, "_retain_stage", archive)
    code = controlplane.cmd_context(None, "compact", True, profile_json=output)
    stdout, stderr = capsys.readouterr()
    report = json.loads(output.read_text())
    assert code == (0 if fault == "healthy" else 2)
    assert not list((harness / ".transactions").iterdir())
    assert load_context(harness)[1]["freshness"] is True
    if fault == "before_commit":
        assert events == ["before_commit"]
        assert current.stat().st_ino == original_inode
        assert current.read_bytes() == original_bytes
        assert stdout == ""
        assert report["context_published"] is False
        assert "context_published=false" in stderr
    else:
        assert current.stat().st_ino != original_inode
        assert events == (["committed"] if fault == "healthy" else ["committed", "archive_failed"])
        if fault == "healthy":
            assert json.loads(stdout)["context_hash"] == load_context(harness)[0]["context_hash"]
        else:
            assert stdout == ""
        # Intentionally RED only when native commit happened but return raised.
        assert report["context_published"] is True, (events, report, stderr)
        if fault == "after_commit":
            assert "context_published=true" in stderr


@pytest.mark.parametrize("action", ["replace", "delete"])
def test_commit_syncs_retained_original_before_terminal(harness, monkeypatch, action):
    """FND030: trace actual file fsync, not directory sync or simulated power loss."""
    from harness.telemetry_lock import telemetry_lock

    target = harness / "sync-subject.yaml"
    target.write_bytes(b"original not explicitly synchronized by writer")
    info = target.stat()
    original = (info.st_dev, info.st_ino)
    calls = []
    terminal = []
    sync = os.fsync
    write = publication_journal._write_new

    def synchronized(fd):
        result = sync(fd)
        info = os.fstat(fd)
        calls.append((info.st_dev, info.st_ino))
        return result

    def written(fd, name, document):
        state = document.get("operation", document).get("state")
        if state == "COMMITTED":
            terminal.append((name, frozenset(calls)))
        return write(fd, name, document)

    monkeypatch.setattr(os, "fsync", synchronized)
    monkeypatch.setattr(publication_journal, "_write_new", written)
    payload = b"native replacement" if action == "replace" else None
    with telemetry_lock(harness), publication_journal.prepare(
        harness, (publication_journal.Member(target.name, target.read_bytes(), payload),)
    ) as operation:
        operation.apply()
        operation.commit()
        assert operation.finished and operation.document["state"] == "COMMITTED"
    assert not list((harness / ".transactions").iterdir())
    retained = [p for p in (harness / ".publication-retained").rglob("*")
                if p.is_file() and (p.stat().st_dev, p.stat().st_ino) == original]
    assert len(retained) == 1
    assert retained[0].read_bytes() == b"original not explicitly synchronized by writer"
    assert terminal and terminal[0][0].startswith("state-")
    assert terminal[-1][0] == "manifest.json"
    if payload is not None:
        assert target.read_bytes() == payload
        candidate = (target.stat().st_dev, target.stat().st_ino)
        assert candidate != original and candidate in terminal[0][1], "native candidate fsync observer control"
    else:
        assert not target.exists()
    assert original in terminal[0][1], (action, "retained original inode never fsynced before COMMITTED", original)


@pytest.mark.parametrize("original_source", ["archived", "live"])
def test_migration_original_survives_supported_audited_add(harness, original_source):
    """FND031: accepted origin must survive valid ADD, or fail before admission."""
    import yaml
    from test_context_builder import enable_plan_reconciliation, write_yaml
    from test_decision import proposal as decision_proposal

    from harness import alignment, decision
    from harness import test_scope as scope
    from harness._scope_replay import SCOPE_FILES, TestScopeError, raw_hash
    from harness.context.freshness import digest

    for name in SCOPE_FILES:
        (harness / name).unlink()
    enable_plan_reconciliation(harness, level="Q1")
    initial = ["tests/test_original.py"]
    extra = "tests/test_added.py"
    for name in (*initial, extra):
        path = harness.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_declared():\n    pass\n")
    write_yaml(harness / "impact.yaml", {"impact": {"changed": [], "required_tests": initial}})
    source = harness / ("impact.yaml" if original_source == "live" else "original-impact.yaml")
    if original_source == "archived":
        source.write_bytes((harness / "impact.yaml").read_bytes())
    descriptor = {"path": f".harness/{source.name}", "hash": raw_hash(source.read_bytes()), "tests_hash": digest(initial)}
    impact_hash = raw_hash((harness / "impact.yaml").read_bytes())
    value = decision_proposal(recommendation="local")
    value["constraints"] = ["PRESERVE_OBLIGATIONS", "PRESERVE_RISK", "NO_EXECUTION", "NO_RELEASE"]
    value["scope"] = sorted({descriptor["path"], ".harness/impact.yaml", ".harness/gate.yaml",
                             *(f".harness/{name}" for name in SCOPE_FILES)})
    value["options"][0]["test_scope_authorization"] = {
        "version": 1, "task_id": "TASK-028", "operation": "MIGRATE",
        "expected_impact_hash": impact_hash,
        "contract_hash": alignment.contract_hash(alignment.load_alignment(harness)),
        "original_source": descriptor, "retirements": [], "bindings": [], "plan_refs": [],
    }
    created = decision.propose(harness, value)
    accepted = decision.accept(harness, created["id"], option="local", source="accepted_recommendation")
    request = {"version": 1, "task_id": "TASK-028", "expected_impact_hash": impact_hash,
               "decision_ref": accepted["id"], "original_source": descriptor}
    canonical_names = (*SCOPE_FILES, "impact.yaml", "gate.yaml", "current-task.yaml")
    before = {name: (harness / name).read_bytes() if (harness / name).exists() else None for name in canonical_names}
    try:
        result = scope.migrate_test_scope(harness, request)
    except TestScopeError as exc:
        # Refusing mutable canonical origin is allowed; archived source must work.
        assert original_source == "live" and exc.code == "TEST_SCOPE_RETIREMENT_UNAUTHORIZED"
        assert before == {name: (harness / name).read_bytes() if (harness / name).exists() else None for name in canonical_names}
        return
    assert result["status"] == "VALIDATED", result
    assert scope.assess_test_scope_retirements(harness) == []
    baseline_before = (harness / SCOPE_FILES[0]).read_bytes()
    scope.add_required_test(harness, extra)
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert audit["entries"][-1]["operation"] == "ADD"
    assert audit["entries"][-1]["before_tests"] == initial
    assert set(audit["entries"][-1]["after_tests"]) == {*initial, extra}
    assert (harness / SCOPE_FILES[0]).read_bytes() == baseline_before
    assert yaml.safe_load((harness / "impact.yaml").read_text())["impact"]["required_tests"] == [*initial, extra]
    assert not list((harness / ".transactions").iterdir())
    assert scope.assess_test_scope_retirements(harness) == [], "supported ADD invalidated accepted original-source descriptor"


@pytest.mark.parametrize("entry", ["new", "recover"])
def test_task_turnover_preserves_retained_original_inode(harness, entry):
    """FND032: copying bytes does not preserve lifetime of displaced original."""
    import yaml
    from test_context_builder import write_yaml

    from harness.telemetry_lock import telemetry_lock
    from harness.test_scope import assess_test_scope_retirements

    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["state"] = "DONE" if entry == "new" else "IMPLEMENTING"
    write_yaml(harness / "current-task.yaml", task)
    target = harness / "retention-subject.yaml"
    target.write_bytes(b"original record")
    held = os.open(target, os.O_RDWR)
    original = (os.fstat(held).st_dev, os.fstat(held).st_ino)

    def original_paths():
        return [p for p in harness.parent.rglob("*") if p.is_file()
                and (p.stat().st_dev, p.stat().st_ino) == original]

    try:
        with telemetry_lock(harness), publication_journal.prepare(
            harness, (publication_journal.Member(target.name, b"original record", b"new canonical"),)
        ) as operation:
            operation.apply()
            operation.commit()
        paths = original_paths()
        assert len(paths) == 1 and ".publication-retained" in paths[0].parts
        assert os.fstat(held).st_nlink >= 1
        os.pwrite(held, b"before turnover", 0)
        assert paths[0].read_bytes() == b"before turnover", "healthy held-FD retention control"
        assert target.read_bytes() == b"new canonical"
        assert not list((harness / ".transactions").iterdir())
        code = (controlplane.cmd_task_new("TASK-029", "private retention fixture") if entry == "new"
                else controlplane.cmd_task_recover("TASK-029", "private retention fixture", "fixture stale task"))
        current = yaml.safe_load((harness / "current-task.yaml").read_text())
        if code == 0:
            assert current["task"]["id"] == "TASK-029"
            assert current["state"] == "CREATED"
            assert assess_test_scope_retirements(harness) == []
        else:
            # Explicit fail-closed refusal is allowed, but must not lose originals.
            assert code == 2 and current["task"]["id"] == "TASK-028"
        os.pwrite(held, b"after turnover!", 0)
        paths = original_paths()
        assert paths and os.fstat(held).st_nlink >= 1, (entry, code, "original inode unlinked by turnover", os.fstat(held).st_nlink)
        assert any(p.read_bytes() == b"after turnover!" for p in paths)
        assert target.read_bytes() == b"new canonical"
    finally:
        os.close(held)


@pytest.mark.parametrize("fault", ["archive_schema", "terminal_io", "terminal_cancel"])
def test_context_postcommit_failure_reports_fact_not_return(harness, monkeypatch, tmp_path, capsys, fault):
    """New FND029 outcome transport must survive schema errors and terminal teardown."""
    finish = publication_journal.Operation._finish
    retain = transaction._retain_stage
    events = []

    def finish_fault(operation):
        if fault.startswith("terminal") and operation.document["state"] == "COMMITTED":
            events.append("committed")
            if fault == "terminal_cancel":
                raise KeyboardInterrupt
            raise OSError(errno.EIO, "fixture terminal failure")
        return finish(operation)

    def retain_fault(*args, **kwargs):
        if fault == "archive_schema":
            events.append("committed")
            raise ValueError("fixture postcommit schema failure")
        return retain(*args, **kwargs)

    monkeypatch.setattr(publication_journal.Operation, "_finish", finish_fault)
    monkeypatch.setattr(transaction, "_retain_stage", retain_fault)
    output = tmp_path.parent / f"{tmp_path.name}-postcommit.json"
    code = controlplane.cmd_context(None, "compact", True, profile_json=output)
    stdout, stderr = capsys.readouterr()
    report = json.loads(output.read_text())
    assert events == ["committed"]
    assert code == (130 if fault == "terminal_cancel" else 2)
    assert stdout == "" and (harness / "context/current.yaml").is_file()
    assert report["outcome"] == ("CANCELLED" if fault == "terminal_cancel" else "FAILED")
    assert report["context_published"] is True
    if fault != "terminal_cancel":
        assert "context_published=true" in stderr


@pytest.mark.parametrize("action", ["replace", "delete"])
@pytest.mark.parametrize("boundary", ["commit", "abort", "recover_commit", "recover_abort"])
def test_original_sync_failure_keeps_recovery_authority(harness, monkeypatch, action, boundary):
    """FND030: original-file synchronization errors cannot retire authority."""
    from harness.telemetry_lock import telemetry_lock
    from harness.transaction_recovery import recover_pending_publications

    target = harness / "sync-failure.yaml"
    target.write_bytes(b"old sync object")
    original = (target.stat().st_dev, target.stat().st_ino)
    payload = b"new sync object" if action == "replace" else None
    sync = os.fsync
    finish = publication_journal.Operation._finish
    hits = []

    def sync_fault(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == original:
            hits.append(original)
            raise OSError(errno.EIO, "fixture retained file sync failure")
        return sync(fd)

    def terminal_pause(operation):
        if operation.document["state"] in {"COMMITTED", "ABORTED"}:
            raise OSError("fixture terminal handoff pause")
        return finish(operation)

    with telemetry_lock(harness):
        with publication_journal.prepare(
            harness, (publication_journal.Member(target.name, b"old sync object", payload),)
        ) as operation:
            operation.apply()
            if boundary.startswith("recover"):
                with monkeypatch.context() as fault:
                    fault.setattr(publication_journal.Operation, "_finish", terminal_pause)
                    with pytest.raises(OSError, match="fixture terminal handoff pause"):
                        operation.commit() if boundary == "recover_commit" else operation.abort()
            else:
                with monkeypatch.context() as fault:
                    fault.setattr(os, "fsync", sync_fault)
                    with pytest.raises(OSError, match="fixture retained file sync failure"):
                        operation.commit() if boundary == "commit" else operation.abort()
        assert list((harness / ".transactions").iterdir())
        if boundary.startswith("recover"):
            with monkeypatch.context() as fault:
                fault.setattr(os, "fsync", sync_fault)
                with pytest.raises(OSError, match="fixture retained file sync failure"):
                    recover_pending_publications(harness)
            assert list((harness / ".transactions").iterdir())
        assert hits, "actual original-file fsync failure hook must be reached"
        recover_pending_publications(harness)
    assert not list((harness / ".transactions").iterdir())
    assert any(p.is_file() and (p.stat().st_dev, p.stat().st_ino) == original
               for p in harness.rglob("*"))
    expected = payload if boundary == "recover_commit" else b"old sync object"
    assert (target.read_bytes() if target.exists() else None) == expected


def _retained_fd(root):
    from harness.telemetry_lock import telemetry_lock

    target = root / "held-original.yaml"
    target.write_bytes(b"old fd object")
    held = os.open(target, os.O_RDWR)
    try:
        with telemetry_lock(root), publication_journal.prepare(
            root, (publication_journal.Member(target.name, b"old fd object", b"new fd object"),)
        ) as operation:
            operation.apply()
            operation.commit()
        return held
    except BaseException:
        os.close(held)
        raise


def _inode_paths(parent, fd):
    info = os.fstat(fd)
    return [p for p in parent.rglob("*") if p.is_file()
            and (p.stat().st_dev, p.stat().st_ino) == (info.st_dev, info.st_ino)]


@pytest.mark.parametrize("entry", ["new", "recover"])
def test_repeated_turnover_retains_all_original_fds(harness, entry):
    import yaml
    from test_context_builder import write_yaml

    held = []
    try:
        for number in range(29, 32):
            held.append(_retained_fd(harness))
            task = yaml.safe_load((harness / "current-task.yaml").read_text())
            task["state"] = "DONE" if entry == "new" else "IMPLEMENTING"
            write_yaml(harness / "current-task.yaml", task)
            code = (controlplane.cmd_task_new(f"TASK-{number:03}", "fixture repeat") if entry == "new"
                    else controlplane.cmd_task_recover(f"TASK-{number:03}", "fixture repeat", "fixture stale"))
            assert code == 0
            for fd in held:
                os.pwrite(fd, b"late fd bytes", 0)
                paths = _inode_paths(harness.parent, fd)
                assert paths and os.fstat(fd).st_nlink >= 1
                assert any(p.read_bytes() == b"late fd bytes" for p in paths)
    finally:
        for fd in held:
            os.close(fd)


def test_prepared_replacement_does_not_clone_terminal_retention(harness):
    from harness.task_replacement import replacement_workspace

    assert (harness / ".publication-retained").is_dir()
    staged = replacement_workspace(harness)
    assert not (staged / ".publication-retained").exists()
    assert (staged / "current-task.yaml").read_bytes() == (harness / "current-task.yaml").read_bytes()


@pytest.mark.parametrize("moment", ["before", "after"])
def test_turnover_retention_error_preserves_original_and_owner(harness, monkeypatch, moment, capsys):
    from test_publication_admission import assert_review_owner

    from harness import publication_fs as fs

    held = _retained_fd(harness)
    move = fs.move_noreplace
    hits = []

    def fault(src_fd, src_name, dst_fd, dst_name):
        if src_name == f".{harness.name}.backup" and dst_name == "previous":
            assert_review_owner(harness)
            hits.append(moment)
            if moment == "before":
                raise OSError(errno.ENOSPC, "fixture retention move failure")
            move(src_fd, src_name, dst_fd, dst_name)
            raise OSError(errno.ENOSPC, "fixture retention handoff failure")
        return move(src_fd, src_name, dst_fd, dst_name)

    monkeypatch.setattr(fs, "move_noreplace", fault)
    try:
        assert controlplane.cmd_task_recover("TASK-029", "fixture", "fixture stale") == 2
        assert hits == [moment]
        assert "TASK_REPLACEMENT_FAILED" in capsys.readouterr().err
        os.pwrite(held, b"late fd bytes", 0)
        paths = _inode_paths(harness.parent, held)
        assert paths and any(p.read_bytes() == b"late fd bytes" for p in paths)
    finally:
        os.close(held)


@pytest.mark.parametrize("restore_fails", [False, True])
def test_turnover_rollback_preserves_primary_and_old_tree(harness, monkeypatch, restore_fails):
    from pathlib import Path

    from harness.task_replacement import publish_replacement, replacement_workspace

    held = _retained_fd(harness)
    staged = replacement_workspace(harness)
    backup = harness.with_name(f".{harness.name}.backup")
    replace = Path.replace

    def fault(path, target):
        if path == staged:
            raise OSError("fixture stage primary")
        if path == backup and restore_fails:
            raise OSError("fixture restore secondary")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fault)
    try:
        with pytest.raises(OSError, match="fixture stage primary"):
            publish_replacement(harness, staged)
        assert (backup if restore_fails else harness).is_dir()
        assert _inode_paths(harness.parent, held)
    finally:
        os.close(held)


@pytest.mark.parametrize("kind", ["directory", "broken_symlink"])
def test_turnover_unknown_backup_refuses_without_loss(harness, monkeypatch, kind):
    from harness.task_replacement import publish_replacement, replacement_workspace

    staged = replacement_workspace(harness)
    backup = harness.with_name(f".{harness.name}.backup")
    if kind == "directory":
        backup.mkdir()
    else:
        backup.symlink_to(harness.parent / "absent-operator-tree")
    before = (harness / "current-task.yaml").read_bytes()
    with pytest.raises(FileExistsError, match="replacement backup exists"):
        publish_replacement(harness, staged)
    assert (harness / "current-task.yaml").read_bytes() == before
    assert backup.is_dir() if kind == "directory" else backup.is_symlink()


def test_turnover_retention_symlink_refuses_without_following(harness):
    from harness.task_replacement import publish_replacement, replacement_workspace

    held = _retained_fd(harness)
    staged = replacement_workspace(harness)
    external = harness.parent / "outside-retention"
    external.mkdir()
    # A prepared replacement with an operator-controlled retention alias is invalid.
    import shutil
    shutil.rmtree(staged / ".publication-retained", ignore_errors=True)
    (staged / ".publication-retained").symlink_to(external, target_is_directory=True)
    try:
        with pytest.raises(OSError):
            publish_replacement(harness, staged)
        assert list(external.iterdir()) == []
        assert os.fstat(held).st_nlink >= 1
    finally:
        os.close(held)


def test_publication_outcome_is_per_invocation_not_sticky(harness):
    outcome = transaction.PublicationOutcome()
    artifact = transaction.StagedArtifact("outcome.yaml", b"first")
    transaction.publish(harness, transaction.stage(harness, [artifact]), outcome=outcome)
    assert outcome.committed is True
    with pytest.raises(FileExistsError):
        transaction.publish(harness, transaction.stage(harness, [artifact]), outcome=outcome)
    assert outcome.committed is False
    assert (harness / "outcome.yaml").read_bytes() == b"first"
    transaction.publish(harness, transaction.stage(harness, []), outcome=outcome)
    assert outcome.committed is False  # No native transaction occurred.


@pytest.mark.parametrize("foreign_kind", ["file", "directory"])
def test_journal_sync_rechecks_opened_inode_and_type(harness, monkeypatch, foreign_kind):
    from harness.telemetry_lock import telemetry_lock

    target = harness / "sync-identity.yaml"
    target.write_bytes(b"original")
    foreign = harness.parent / "foreign-object"
    foreign.mkdir() if foreign_kind == "directory" else foreign.write_bytes(b"unrelated")
    opened = os.open
    armed = [False]
    with telemetry_lock(harness), publication_journal.prepare(
        harness, (publication_journal.Member(target.name, b"original", b"candidate"),)
    ) as operation:
        operation.apply()
        values = operation._values

        def checked(*args, **kwargs):
            result = values(*args, **kwargs)
            armed[0] = True
            return result

        def substitute(name, flags, *args, **kwargs):
            if armed[0] and name == target.name:
                armed[0] = False
                return opened(foreign, flags)
            return opened(name, flags, *args, **kwargs)

        with monkeypatch.context() as fault:
            fault.setattr(operation, "_values", checked)
            fault.setattr(os, "open", substitute)
            with pytest.raises(OSError, match="TRANSACTION_RECOVERY_BLOCKED"):
                operation.commit()
        operation.abort()
    assert target.read_bytes() == b"original"
    assert not list((harness / ".transactions").iterdir())
    assert foreign.is_dir() if foreign_kind == "directory" else foreign.read_bytes() == b"unrelated"


def test_journal_sync_primary_beats_close_failure(harness, monkeypatch):
    from harness.telemetry_lock import telemetry_lock

    target = harness / "sync-cleanup.yaml"
    target.write_bytes(b"original")
    sync, close = os.fsync, os.close
    failed_fd = [None]
    with telemetry_lock(harness), publication_journal.prepare(
        harness, (publication_journal.Member(target.name, b"original", b"candidate"),)
    ) as operation:
        operation.apply()
        candidate = target.stat().st_ino

        def sync_fault(fd):
            if os.fstat(fd).st_ino == candidate:
                failed_fd[0] = fd
                raise OSError("fixture sync primary")
            return sync(fd)

        def close_fault(fd):
            close(fd)
            if fd == failed_fd[0]:
                failed_fd[0] = None
                raise OSError("fixture close secondary")

        with monkeypatch.context() as fault:
            fault.setattr(os, "fsync", sync_fault)
            fault.setattr(os, "close", close_fault)
            with pytest.raises(OSError, match="fixture sync primary"):
                operation.commit()
        operation.abort()
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("body_fails", [False, True])
def test_retention_cleanup_preserves_primary_or_reports_error(harness, monkeypatch, body_fails):
    from harness import publication_fs as fs
    from harness.task_replacement import _retain_replaced_harness
    from harness.telemetry_lock import telemetry_lock

    backup = harness.parent / ".fixture-backup"
    backup.mkdir()
    original = backup / "original.yaml"
    original.write_bytes(b"retained bytes")
    inode = original.stat().st_ino
    move, close = fs.move_noreplace, os.close
    armed = [False]

    def move_fault(*args):
        armed[0] = True
        if body_fails:
            raise OSError("fixture retention primary")
        return move(*args)

    def close_fault(fd):
        close(fd)
        if armed[0]:
            armed[0] = False
            raise OSError("fixture retention cleanup")

    with telemetry_lock(harness), monkeypatch.context() as fault:
        fault.setattr(fs, "move_noreplace", move_fault)
        fault.setattr(os, "close", close_fault)
        with pytest.raises(OSError, match="fixture retention primary" if body_fails else "fixture retention cleanup"):
            _retain_replaced_harness(harness, backup)
    kept = [p for p in harness.parent.rglob("*") if p.is_file() and p.stat().st_ino == inode]
    assert len(kept) == 1 and kept[0].read_bytes() == b"retained bytes"


@pytest.mark.parametrize("primary", ["cancel", "body"])
@pytest.mark.parametrize("fault", ["healthy", "sync_io", "broken_warning", "closed_warning", "sync_and_close"])
def test_abort_sync_secondary_never_replaces_primary(harness, monkeypatch, primary, fault):
    import sys

    from harness.telemetry_lock import telemetry_lock
    from harness.transaction_recovery import recover_pending_publications

    target = harness / "abort-primary.yaml"
    target.write_bytes(b"original")
    prepare, sync, close = publication_journal.prepare, os.fsync, os.close
    operation_fd = [None]
    captured = {}
    candidate = [None]
    aborting = [False]
    hits = []

    def prepared(*args, **kwargs):
        operation = prepare(*args, **kwargs)
        operation_fd[0] = operation.fds["root"]
        captured.update({fd: (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in operation.fds.values()})
        return operation

    def callback():
        candidate[0] = target.stat().st_ino
        aborting[0] = True
        if primary == "cancel":
            raise KeyboardInterrupt("fixture primary cancel")
        raise OSError("fixture primary body")

    def sync_fault(fd):
        if aborting[0] and fault != "healthy" and os.fstat(fd).st_ino == candidate[0]:
            hits.append("sync")
            raise OSError("fixture secondary abort sync")
        return sync(fd)

    def close_fault(fd):
        close(fd)
        if fault == "sync_and_close" and fd == operation_fd[0]:
            operation_fd[0] = None
            hits.append("close")
            raise OSError("fixture secondary descriptor close")

    class FailedWarning:
        def write(self, message):
            if fault == "closed_warning":
                raise ValueError("fixture closed warning")
            raise OSError("fixture broken warning")

        def flush(self):
            pass

    staged = transaction.stage(harness, [transaction.StagedArtifact(target.name, b"candidate")])
    try:
        with monkeypatch.context() as edge:
            edge.setattr(publication_journal, "prepare", prepared)
            edge.setattr(os, "fsync", sync_fault)
            edge.setattr(os, "close", close_fault)
            if fault in {"broken_warning", "closed_warning"}:
                edge.setattr(sys, "stderr", FailedWarning())
            with pytest.raises(KeyboardInterrupt if primary == "cancel" else OSError, match="fixture primary"):
                transaction.publish(harness, staged, replace_paths=frozenset({target.name}), after_publish=callback)
        for fd in captured:
            with pytest.raises(OSError):
                os.fstat(fd)
        assert hits == ([] if fault == "healthy" else ["sync", "close"] if fault == "sync_and_close" else ["sync"])
        assert target.read_bytes() == b"original"
        assert bool(list((harness / ".transactions").iterdir())) == (fault != "healthy")
        with telemetry_lock(harness):
            recover_pending_publications(harness)
        assert not list((harness / ".transactions").iterdir())
    finally:
        # Faulty baseline __exit__ may stop closing early; preserve test isolation.
        for fd, identity in captured.items():
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) == identity:
                    close(fd)
            except OSError:
                pass


@pytest.mark.parametrize("sync_fails", [False, True])
def test_context_finalizer_cancel_keeps_130_when_abort_sync_fails(harness, monkeypatch, tmp_path, sync_fails):
    from harness.context import store

    sync = os.fsync
    candidate = [None]

    def cancel(*args, **kwargs):
        candidate[0] = (harness / "context/current.yaml").stat().st_ino
        raise KeyboardInterrupt("fixture finalizer cancel")

    def sync_fault(fd):
        if sync_fails and os.fstat(fd).st_ino == candidate[0]:
            raise OSError("fixture secondary abort sync")
        return sync(fd)

    output = tmp_path.parent / f"{tmp_path.name}-abort-cancel.json"
    monkeypatch.setattr(store, "_equal", cancel)
    monkeypatch.setattr(os, "fsync", sync_fault)
    code = controlplane.cmd_context(None, "compact", True, profile_json=output)
    report = json.loads(output.read_text())
    assert candidate[0] is not None
    assert code == 130 and report["outcome"] == "CANCELLED"
    assert report["context_published"] is False


def test_operation_exit_reports_cleanup_without_primary(harness, monkeypatch):
    from harness.telemetry_lock import telemetry_lock

    target = harness / "exit-cleanup.yaml"
    target.write_bytes(b"original")
    close = os.close
    captured = []
    close_fd = [None]

    def close_fault(fd):
        close(fd)
        if fd == close_fd[0]:
            close_fd[0] = None
            raise OSError("fixture successful-body cleanup failure")

    with telemetry_lock(harness), monkeypatch.context() as fault:
        fault.setattr(os, "close", close_fault)
        with pytest.raises(OSError, match="fixture successful-body cleanup failure"), publication_journal.prepare(
            harness, (publication_journal.Member(target.name, b"original", b"candidate"),)
        ) as operation:
            operation.apply()
            operation.commit()
            captured.extend(operation.fds.values())
            close_fd[0] = operation.fds["root"]
    assert not operation.fds
    for fd in captured:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert target.read_bytes() == b"candidate"
    assert not list((harness / ".transactions").iterdir())


@pytest.mark.parametrize("primary_kind", ["cancel", "body"])
@pytest.mark.parametrize("stream_error", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_abort_warning_adapter_cannot_replace_primary(harness, monkeypatch, primary_kind, stream_error):
    import sys

    target = harness / "warning-adapter.yaml"
    target.write_bytes(b"original")
    primary = KeyboardInterrupt("fixture primary") if primary_kind == "cancel" else OSError("fixture primary")
    candidate = [None]
    sync = os.fsync

    class FailedAdapter:
        def write(self, message):
            raise stream_error("fixture warning adapter")

        def flush(self):
            pass

    def callback():
        candidate[0] = target.stat().st_ino
        raise primary

    def sync_fault(fd):
        if os.fstat(fd).st_ino == candidate[0]:
            raise OSError("fixture secondary abort sync")
        return sync(fd)

    staged = transaction.stage(harness, [transaction.StagedArtifact(target.name, b"candidate")])
    actual = None
    with monkeypatch.context() as edge:
        edge.setattr(sys, "stderr", FailedAdapter())
        edge.setattr(os, "fsync", sync_fault)
        try:
            transaction.publish(harness, staged, replace_paths=frozenset({target.name}), after_publish=callback)
        except (RuntimeError, KeyboardInterrupt, SystemExit, OSError) as exc:
            actual = exc
    assert candidate[0] is not None
    assert actual is primary, (type(actual), str(actual))
    assert target.read_bytes() == b"original"
    assert list((harness / ".transactions").iterdir())
