"""Behavioral contract for safe, bounded v2 publication failure context."""

from __future__ import annotations

import errno
import json
import re
import sys
from pathlib import Path

import pytest

from harness import publication_fs, publication_journal, transaction


PREFIX = "PUBLICATION_FAILURE_CONTEXT "
MAX_RECORD_BYTES = 2048


def _context(stderr: str, root: Path, prefix: str = PREFIX) -> dict:
    records = [line for line in stderr.splitlines() if line.startswith(prefix)]
    assert len(records) == 1, stderr
    record = records[0]
    assert len(record.encode()) <= MAX_RECORD_BYTES
    assert str(root) not in record
    value = json.loads(record.removeprefix(prefix))
    assert re.fullmatch(r"[0-9a-f]{32}", value["operation_id"])
    assert value["retained_location"] == f".publication-retained/{value['operation_id']}"
    assert value["observed_state"] in {"ABORTED", "ABORTING", "COMMITTED"}
    assert set(value) <= {
        "operation_id", "canonical_member", "observed_state", "retained_location"
    }
    return value


def _replacement(root: Path, member: str = "impact.yaml") -> tuple[Path, int]:
    root.mkdir()
    target = root / member
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original bytes")
    original_inode = target.stat().st_ino
    staged = transaction.stage(
        root, [transaction.StagedArtifact(member, b"candidate secret payload")]
    )
    return staged, original_inode


def _inject_exchange_after_prepare(
    monkeypatch, *, member: str, state: str, error: BaseException
) -> dict:
    real_prepare = publication_journal.prepare
    real_exchange = publication_fs.exchange
    observed = {"operation": None, "prepare_success": 0, "injections": 0}
    basename = Path(member).name

    def prepare_wrapper(*args, **kwargs):
        operation = real_prepare(*args, **kwargs)
        observed["operation"] = operation
        observed["prepare_success"] += 1
        return operation

    def exchange_wrapper(*args, **kwargs):
        operation = observed["operation"]
        names = {args[1], args[3]}
        if (
            operation is not None
            and operation.document["state"] == state
            and basename in names
        ):
            observed["injections"] += 1
            raise error
        return real_exchange(*args, **kwargs)

    monkeypatch.setattr(publication_journal, "prepare", prepare_wrapper)
    monkeypatch.setattr(publication_fs, "exchange", exchange_wrapper)
    return observed


def _capture_prepare(monkeypatch) -> dict:
    real_prepare = publication_journal.prepare
    observed = {"operation": None, "prepare_success": 0}

    def prepare_wrapper(*args, **kwargs):
        operation = real_prepare(*args, **kwargs)
        observed["operation"] = operation
        observed["prepare_success"] += 1
        return operation

    monkeypatch.setattr(publication_journal, "prepare", prepare_wrapper)
    return observed


def test_apply_failure_reports_member_after_successful_compensation(
    tmp_path, monkeypatch, capsys
):
    """Break caught: abort clears forward intent before diagnostics identify its member."""
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = OSError(errno.EIO, "private native failure text")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member="impact.yaml", state="APPLYING", error=primary
    )

    with pytest.raises(OSError) as raised:
        transaction.publish(root, staged, replace_paths=frozenset({"impact.yaml"}))

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert observed["operation"].document["state"] == "ABORTED"
    assert raised.value is primary
    assert raised.value.errno == errno.EIO
    assert (root / "impact.yaml").read_bytes() == b"original bytes"
    assert (root / "impact.yaml").stat().st_ino == original_inode
    context = _context(capsys.readouterr().err, root)
    assert context["canonical_member"] == "impact.yaml"
    assert context["observed_state"] == "ABORTED"


def test_callback_failure_reports_aborted_without_inventing_member(
    tmp_path, monkeypatch, capsys
):
    """Break caught: a callback failure is misleadingly assigned to a bundle member."""
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = OSError(errno.EPERM, "private callback failure text")
    observed = _capture_prepare(monkeypatch)

    with pytest.raises(OSError) as raised:
        transaction.publish(
            root,
            staged,
            replace_paths=frozenset({"impact.yaml"}),
            after_publish=lambda: (_ for _ in ()).throw(primary),
        )

    assert observed["prepare_success"] == 1
    assert observed["operation"].document["state"] == "ABORTED"
    assert raised.value is primary
    assert raised.value.errno == errno.EPERM
    assert (root / "impact.yaml").read_bytes() == b"original bytes"
    assert (root / "impact.yaml").stat().st_ino == original_inode
    context = _context(capsys.readouterr().err, root)
    assert "canonical_member" not in context
    assert context["observed_state"] == "ABORTED"


def test_abort_failure_reports_aborting_member_and_preserves_primary(
    tmp_path, monkeypatch, capsys
):
    """Break caught: secondary compensation failure hides the affected member/state."""
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = OSError(errno.EBUSY, "private validation failure text")
    secondary = OSError(errno.EIO, "private reverse exchange failure text")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member="impact.yaml", state="ABORTING", error=secondary
    )

    with pytest.raises(OSError) as raised:
        transaction.publish(
            root,
            staged,
            replace_paths=frozenset({"impact.yaml"}),
            after_publish=lambda: (_ for _ in ()).throw(primary),
        )

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert observed["operation"].document["state"] == "ABORTING"
    assert raised.value is primary
    assert raised.value.errno == errno.EBUSY
    assert (root / "impact.yaml").read_bytes() == b"candidate secret payload"
    assert (root / "impact.yaml").stat().st_ino != original_inode
    context = _context(capsys.readouterr().err, root)
    assert context["canonical_member"] == "impact.yaml"
    assert context["observed_state"] == "ABORTING"
    assert list((root / ".transactions").glob("*.json"))


def test_post_commit_stage_retention_failure_reports_committed_truth(
    tmp_path, monkeypatch, capsys
):
    """Break caught: housekeeping failure implies rollback after durable commit."""
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = OSError(errno.ENOSPC, "private stage retention failure text")
    observed = _capture_prepare(monkeypatch)

    def fail_retention(*_args, **_kwargs):
        raise primary

    monkeypatch.setattr(transaction, "_retain_stage", fail_retention)
    with pytest.raises(OSError) as raised:
        transaction.publish(root, staged, replace_paths=frozenset({"impact.yaml"}))

    assert observed["prepare_success"] == 1
    assert observed["operation"].document["state"] == "COMMITTED"
    assert raised.value is primary
    assert raised.value.errno == errno.ENOSPC
    assert (root / "impact.yaml").read_bytes() == b"candidate secret payload"
    assert (root / "impact.yaml").stat().st_ino != original_inode
    stderr = capsys.readouterr().err
    assert PREFIX not in stderr
    context = _context(stderr, root, prefix="PUBLICATION_COMMITTED_CONTEXT ")
    assert context["observed_state"] == "COMMITTED"
    assert "canonical_member" not in context


@pytest.mark.parametrize("helper_error", [RuntimeError, KeyboardInterrupt])
def test_member_extraction_failure_cannot_skip_compensation(
    tmp_path, monkeypatch, capsys, helper_error
):
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = OSError(errno.EIO, "private native failure text")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member="impact.yaml", state="APPLYING", error=primary
    )

    def fail_extraction(_document):
        raise helper_error("diagnostic extraction failed")

    monkeypatch.setattr(transaction, "_active_publication_member", fail_extraction)
    actual = None
    try:
        transaction.publish(root, staged, replace_paths=frozenset({"impact.yaml"}))
    except BaseException as exc:
        actual = exc

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert observed["operation"].document["state"] == "ABORTED"
    assert actual is primary
    assert isinstance(actual, OSError)
    assert actual.errno == errno.EIO
    assert (root / "impact.yaml").read_bytes() == b"original bytes"
    assert (root / "impact.yaml").stat().st_ino == original_inode
    context = _context(capsys.readouterr().err, root)
    assert context["observed_state"] == "ABORTED"
    assert "canonical_member" not in context


@pytest.mark.parametrize("helper_error", [RuntimeError, KeyboardInterrupt])
def test_abort_failure_extraction_cannot_replace_cancellation(
    tmp_path, monkeypatch, capsys, helper_error
):
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = KeyboardInterrupt("private cancellation text")
    secondary = OSError(errno.EIO, "private reverse exchange failure text")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member="impact.yaml", state="ABORTING", error=secondary
    )
    real_extraction = transaction._active_publication_member
    extraction_calls = 0

    def fail_second_extraction(document):
        nonlocal extraction_calls
        extraction_calls += 1
        if extraction_calls == 2:
            raise helper_error("diagnostic extraction failed")
        return real_extraction(document)

    monkeypatch.setattr(transaction, "_active_publication_member", fail_second_extraction)
    actual = None
    try:
        transaction.publish(
            root,
            staged,
            replace_paths=frozenset({"impact.yaml"}),
            after_publish=lambda: (_ for _ in ()).throw(primary),
        )
    except BaseException as exc:
        actual = exc

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert extraction_calls == 2
    assert observed["operation"].document["state"] == "ABORTING"
    assert actual is primary
    assert isinstance(actual, KeyboardInterrupt)
    assert (root / "impact.yaml").read_bytes() == b"candidate secret payload"
    assert (root / "impact.yaml").stat().st_ino != original_inode
    context = _context(capsys.readouterr().err, root)
    assert "canonical_member" not in context
    assert context["observed_state"] == "ABORTING"


@pytest.mark.parametrize("sink_error", [RuntimeError, KeyboardInterrupt])
def test_diagnostic_sink_failure_never_replaces_cancellation(
    tmp_path, monkeypatch, sink_error
):
    """Break caught: diagnostic output failure replaces the publication primary."""
    root = tmp_path / ".harness"
    staged, original_inode = _replacement(root)
    primary = KeyboardInterrupt("private cancellation text")
    secondary = OSError(errno.EIO, "private compensation text")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member="impact.yaml", state="ABORTING", error=secondary
    )

    class FailedSink:
        def write(self, _message):
            raise sink_error("diagnostic sink failed")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stderr", FailedSink())
    actual = None
    try:
        transaction.publish(
            root,
            staged,
            replace_paths=frozenset({"impact.yaml"}),
            after_publish=lambda: (_ for _ in ()).throw(primary),
        )
    except BaseException as exc:
        actual = exc

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert observed["operation"].document["state"] == "ABORTING"
    assert actual is primary
    assert isinstance(actual, KeyboardInterrupt)
    assert (root / "impact.yaml").read_bytes() == b"candidate secret payload"
    assert (root / "impact.yaml").stat().st_ino != original_inode


def test_context_is_one_bounded_json_line_without_payload_or_exception_text(
    tmp_path, monkeypatch, capsys
):
    """Break caught: unsafe member/control data turns diagnostics into injected output."""
    root = tmp_path / ".harness"
    member = "nested/member-\n-control.yaml"
    basename = "member-\n-control.yaml"
    staged, original_inode = _replacement(root, member)
    primary = OSError(errno.EIO, "DO_NOT_PRINT_EXCEPTION_TEXT")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member=member, state="APPLYING", error=primary
    )

    with pytest.raises(OSError) as raised:
        transaction.publish(root, staged, replace_paths=frozenset({member}))

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert observed["operation"].document["state"] == "ABORTED"
    assert raised.value is primary
    assert raised.value.errno == errno.EIO
    assert (root / member).read_bytes() == b"original bytes"
    assert (root / member).stat().st_ino == original_inode
    stderr = capsys.readouterr().err
    context = _context(stderr, root)
    assert context["canonical_member"] == basename
    assert len(stderr.splitlines()) == 1
    assert json.dumps(basename) in stderr
    assert "nested/" not in stderr
    assert "candidate secret payload" not in stderr
    assert "original bytes" not in stderr
    assert "DO_NOT_PRINT_EXCEPTION_TEXT" not in stderr


def test_maximum_basename_json_escaping_stays_bounded(tmp_path, monkeypatch, capsys):
    root = tmp_path / ".harness"
    basename = "\x01" * 255
    staged, original_inode = _replacement(root, basename)
    primary = OSError(errno.EIO, "private native failure text")
    observed = _inject_exchange_after_prepare(
        monkeypatch, member=basename, state="APPLYING", error=primary
    )

    with pytest.raises(OSError) as raised:
        transaction.publish(root, staged, replace_paths=frozenset({basename}))

    assert observed["prepare_success"] == 1
    assert observed["injections"] == 1
    assert observed["operation"].document["state"] == "ABORTED"
    assert raised.value is primary
    assert raised.value.errno == errno.EIO
    assert (root / basename).read_bytes() == b"original bytes"
    assert (root / basename).stat().st_ino == original_inode
    stderr = capsys.readouterr().err
    context = _context(stderr, root)
    assert context["canonical_member"] == basename
    assert len(stderr.splitlines()) == 1


def test_successful_publication_is_quiet(tmp_path, capsys):
    """Control: the new diagnostic channel is failure-only."""
    root = tmp_path / ".harness"
    staged, _inode = _replacement(root)

    transaction.publish(root, staged, replace_paths=frozenset({"impact.yaml"}))

    assert capsys.readouterr().err == ""
    assert (root / "impact.yaml").read_bytes() == b"candidate secret payload"
