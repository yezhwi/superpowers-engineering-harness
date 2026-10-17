"""Public ``harness plan`` mutation command contract tests."""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fixtures.harness import make_harness

REPO = Path(__file__).resolve().parents[1]


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "reconcile", "P-001"),
        (
            "plan",
            "reconcile",
            "P-001",
            "--complete",
            "--skipped",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
        ),
        ("plan", "reconcile", "P-001", "--complete", "--reason", "x"),
        ("plan", "reconcile", "P-001", "--complete", "--decision", "DEC-001"),
        ("plan", "reconcile", "P-001", "--complete", "--replacement", "P-002"),
        ("plan", "reconcile", "P-001", "--skipped", "--decision", "DEC-001"),
        ("plan", "reconcile", "P-001", "--skipped", "--reason", "x"),
        (
            "plan",
            "reconcile",
            "P-001",
            "--skipped",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
            "--surface",
            "src/x.py",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--superseded",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--superseded",
            "--reason",
            "x",
            "--decision",
            "DEC-001",
            "--replacement",
            "P-002",
            "--evidence",
            "unit",
        ),
        ("plan", "begin", "P-001", "--reason", "x"),
        ("plan", "block", "P-001"),
        ("plan", "resume", "P-001", "--surface", "src/x.py"),
        ("plan", "refresh-proof", "P-001", "--reason", "x"),
        ("plan", "upgrade-execution", "P-001"),
    ],
)
def test_plan_mutation_parser_rejects_invalid_arguments(tmp_path, arguments):
    result = cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "begin", "P-001"),
        ("plan", "block", "P-001", "--reason", "waiting"),
        ("plan", "resume", "P-001"),
        (
            "plan",
            "reconcile",
            "P-001",
            "--complete",
            "--evidence",
            "unit-a",
            "--evidence",
            "unit-b",
            "--surface",
            "src/x.py",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--skipped",
            "--reason",
            "gone",
            "--decision",
            "DEC-001",
        ),
        (
            "plan",
            "reconcile",
            "P-001",
            "--superseded",
            "--reason",
            "split",
            "--decision",
            "DEC-001",
            "--replacement",
            "P-002",
        ),
        (
            "plan",
            "refresh-proof",
            "P-001",
            "--evidence",
            "unit",
            "--surface",
            "src/x.py",
        ),
        ("plan", "upgrade-execution"),
        ("plan", "sync-fingerprint"),
    ],
)
def test_plan_mutation_parser_accepts_valid_argument_shapes(tmp_path, arguments):
    result = cli(tmp_path, *arguments)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR:")
    assert "usage:" not in result.stderr


def test_plan_reconcile_auto_parser_accepts_closed_auto_shape(tmp_path):
    result = cli(tmp_path, "plan", "reconcile", "P-001", "--auto")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR:")
    assert "usage:" not in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("--auto", "--complete"),
        ("--auto", "--skipped", "--reason", "x", "--decision", "DEC-001"),
        ("--auto", "--superseded", "--reason", "x", "--decision", "DEC-001", "--replacement", "P-002"),
        ("--auto", "--reason", "x"),
        ("--auto", "--decision", "DEC-001"),
        ("--auto", "--replacement", "P-002"),
        ("--auto", "--evidence", "unit"),
        ("--auto", "--surface", "src/x.py"),
    ],
)
def test_plan_reconcile_auto_parser_rejects_semantic_or_explicit_proof_options(
    tmp_path, arguments
):
    result = cli(tmp_path, "plan", "reconcile", "P-001", *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "begin", "P-001", "--auto"),
        ("plan", "block", "P-001", "--reason", "x", "--auto"),
        ("plan", "resume", "P-001", "--auto"),
        ("plan", "refresh-proof", "P-001", "--auto"),
        ("plan", "upgrade-execution", "--auto"),
    ],
)
def test_non_reconcile_commands_reject_auto(tmp_path, arguments):
    result = cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr


def test_plan_sync_markdown_parser_accepts_one_explicit_path(tmp_path):
    result = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR:")
    assert "usage:" not in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "sync-markdown"),
        ("plan", "sync-markdown", "one.md", "two.md"),
    ],
)
def test_plan_sync_markdown_parser_rejects_missing_or_extra_paths(tmp_path, arguments):
    result = cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def execution_bytes(root: Path) -> bytes:
    return (root / ".harness" / "plan-execution.yaml").read_bytes()


def markdown_target(root: Path, content: bytes = b"- [x] P-001\n") -> Path:
    target = root / "docs" / "plan.md"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(content)
    return target


def mutation_repo(tmp_path: Path, *, stale: bool = False) -> Path:
    from harness.plan_reconciliation import plan_fingerprint

    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("fixture\n")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-qm", "fixture")
    head = git(tmp_path, "rev-parse", "HEAD")

    harness_dir = make_harness(tmp_path, state="IMPLEMENTING", risk="Q3")
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-062"
    task["git"] = {"head": head, "base_commit": head}
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    (harness_dir / "current-task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False)
    )
    plan = {
        "version": 1,
        "items": [{"id": "P-001", "intent": "first", "surfaces": ["src/first.py"]}],
    }
    (harness_dir / "plan.yaml").write_text(yaml.safe_dump(plan, sort_keys=False))
    execution = {
        "version": 2,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": "sha256:" + "0" * 64 if stale else plan_fingerprint(plan),
        },
        "sequence": 0,
        "transitions": [],
        "items": {},
    }
    (harness_dir / "plan-execution.yaml").write_text(
        yaml.safe_dump(execution, sort_keys=False)
    )
    return harness_dir


def test_plan_reconcile_auto_cli_publishes_ordinary_complete_transition(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    assert cli(tmp_path, "plan", "begin", "P-001").returncode == 0
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "first.py").write_text("VALUE = 1\n")

    result = cli(tmp_path, "plan", "reconcile", "P-001", "--auto")

    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        "PLAN_EXECUTION_UPDATED\n",
        "",
    )
    execution = yaml.safe_load((harness_dir / "plan-execution.yaml").read_text())
    assert execution["items"]["P-001"] == {
        "status": "COMPLETE",
        "surface_refs": ["src/first.py"],
    }
    assert execution["transitions"][-1]["action"] == "RECONCILE"
    assert "auto" not in execution
    assert "auto" not in execution["transitions"][-1]


def test_plan_sync_markdown_updates_then_reports_exact_noop(tmp_path):
    mutation_repo(tmp_path)
    target = markdown_target(tmp_path)

    updated = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")
    unchanged = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert (updated.returncode, updated.stdout, updated.stderr) == (
        0,
        "PLAN_MARKDOWN_UPDATED\n",
        "",
    )
    assert (unchanged.returncode, unchanged.stdout, unchanged.stderr) == (
        0,
        "PLAN_MARKDOWN_UNCHANGED\n",
        "",
    )
    assert target.read_bytes() == b"- [ ] P-001\n"


@pytest.mark.parametrize("target", ["/tmp/plan.md", "../plan.md", "docs/../plan.md"])
def test_plan_sync_markdown_rejects_nonlocal_target_without_writing(tmp_path, target):
    mutation_repo(tmp_path)
    markdown = markdown_target(tmp_path)
    before = markdown.read_bytes()

    result = cli(tmp_path, "plan", "sync-markdown", target)

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == "PLAN_MARKDOWN_TARGET_INVALID\n"
    assert markdown.read_bytes() == before


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_plan_sync_markdown_rejects_nonregular_target(tmp_path, kind):
    mutation_repo(tmp_path)
    path = tmp_path / "docs" / "plan.md"
    path.parent.mkdir()
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        outside = tmp_path / "outside.md"
        outside.write_text("- [ ] P-001\n")
        path.symlink_to(outside)

    result = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == "PLAN_MARKDOWN_TARGET_INVALID\n"


def test_plan_sync_markdown_rejects_protected_user_target(tmp_path):
    from harness.workspace import protected_paths_fingerprint

    harness_dir = mutation_repo(tmp_path)
    target = markdown_target(tmp_path)
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["user_changes"] = {
        "paths": ["docs/plan.md"],
        "fingerprint": protected_paths_fingerprint(["docs/plan.md"], repo_root=tmp_path),
    }
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    before = target.read_bytes()

    result = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == "PLAN_MARKDOWN_TARGET_INVALID\n"
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    ("artifact_change", "code"),
    [
        ("missing", "PLAN_REQUIRED"),
        ("stale", "PLAN_STALE"),
        ("v1", "PLAN_TASK_LEVEL_REQUIRED"),
        ("replay", "PLAN_SEQUENCE_INVALID"),
    ],
)
def test_plan_sync_markdown_rejects_untrusted_execution(tmp_path, artifact_change, code):
    harness_dir = mutation_repo(tmp_path, stale=artifact_change == "stale")
    target = markdown_target(tmp_path)
    execution_path = harness_dir / "plan-execution.yaml"
    if artifact_change == "missing":
        (harness_dir / "plan.yaml").unlink()
    elif artifact_change == "v1":
        execution = yaml.safe_load(execution_path.read_text())
        execution_path.write_text(
            yaml.safe_dump(
                {"version": 1, "plan": execution["plan"], "items": {}},
                sort_keys=False,
            )
        )
    elif artifact_change == "replay":
        execution = yaml.safe_load(execution_path.read_text())
        execution["sequence"] = 1
        execution_path.write_text(yaml.safe_dump(execution, sort_keys=False))
    before = target.read_bytes()

    result = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == f"{code}\n"
    assert target.read_bytes() == before


@pytest.mark.parametrize("profile", ["FAST", "disabled"])
def test_plan_sync_markdown_rejects_ineffective_policy_before_adjacent_reads(
    tmp_path, profile
):
    harness_dir = mutation_repo(tmp_path)
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    if profile == "FAST":
        task["risk"]["level"] = "Q1"
        task["risk"]["profile"] = "FAST"
    else:
        task["plan_reconciliation"] = {"enabled": False}
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    (harness_dir / "plan.yaml").write_text("not: [valid")
    markdown_target(tmp_path, b"\xff")

    result = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == "PLAN_MARKDOWN_TARGET_INVALID\n"
    assert "PLAN_SOURCE_INVALID" not in result.stderr
    assert "while parsing" not in result.stderr


@pytest.mark.parametrize(
    "content",
    [b"- [ ]  P-001\n", b"- [ ] P-001\n\xff"],
)
def test_plan_sync_markdown_malformed_target_is_zero_write(tmp_path, content):
    mutation_repo(tmp_path)
    target = markdown_target(tmp_path, content)

    result = cli(tmp_path, "plan", "sync-markdown", "docs/plan.md")

    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr == "PLAN_MARKDOWN_TARGET_INVALID\n"
    assert target.read_bytes() == content


def test_sync_plan_markdown_skips_atomic_write_for_exact_noop(tmp_path, monkeypatch):
    from harness import plan_markdown

    harness_dir = mutation_repo(tmp_path)
    markdown_target(tmp_path, b"- [ ] P-001\n")
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        plan_markdown,
        "atomic_write",
        lambda *_args, **_kwargs: pytest.fail("no-op must not publish"),
    )

    assert not plan_markdown.sync_plan_markdown(
        harness_dir, tmp_path, task, "docs/plan.md"
    )


def test_sync_plan_markdown_atomic_failure_preserves_target(tmp_path, monkeypatch):
    from harness import plan_markdown

    harness_dir = mutation_repo(tmp_path)
    target = markdown_target(tmp_path)
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    before = target.read_bytes()
    monkeypatch.chdir(tmp_path)

    def fail_write(*_args, **_kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr(plan_markdown, "atomic_write", fail_write)

    with pytest.raises(OSError, match="injected publication failure"):
        plan_markdown.sync_plan_markdown(harness_dir, tmp_path, task, "docs/plan.md")
    assert target.read_bytes() == before


def test_sync_plan_markdown_serializes_concurrent_writers(tmp_path, monkeypatch):
    from harness.plan_markdown import sync_plan_markdown

    harness_dir = mutation_repo(tmp_path)
    target = markdown_target(tmp_path)
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    monkeypatch.chdir(tmp_path)
    def run(_index):
        return sync_plan_markdown(harness_dir, tmp_path, task, "docs/plan.md")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))

    assert sorted(results) == [False, True]
    assert target.read_bytes() == b"- [ ] P-001\n"


def test_plan_mutation_cli_runs_lifecycle_and_exact_refresh_retry(tmp_path):
    harness_dir = mutation_repo(tmp_path)

    for arguments in (
        ("plan", "begin", "P-001"),
        ("plan", "block", "P-001", "--reason", "waiting"),
        ("plan", "resume", "P-001"),
    ):
        result = cli(tmp_path, *arguments)
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            "PLAN_EXECUTION_UPDATED\n",
            "",
        )

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "first.py").write_text("VALUE = 1\n")
    complete = cli(
        tmp_path,
        "plan",
        "reconcile",
        "P-001",
        "--complete",
        "--surface",
        "src/first.py",
    )
    refresh = cli(
        tmp_path,
        "plan",
        "refresh-proof",
        "P-001",
        "--surface",
        "src/first.py",
    )
    before_retry = execution_bytes(tmp_path)
    retry = cli(
        tmp_path,
        "plan",
        "refresh-proof",
        "P-001",
        "--surface",
        "src/first.py",
    )

    assert complete.returncode == refresh.returncode == retry.returncode == 0
    assert retry.stdout == "PLAN_EXECUTION_UNCHANGED\n"
    assert execution_bytes(tmp_path) == before_retry
    execution = yaml.safe_load(execution_bytes(tmp_path))
    assert [entry["action"] for entry in execution["transitions"]] == [
        "BEGIN",
        "BLOCK",
        "RESUME",
        "RECONCILE",
        "REFRESH_PROOF",
    ]
    assert execution["items"]["P-001"]["status"] == "COMPLETE"
    assert "proof_receipt" in execution["transitions"][-1]
    assert not (harness_dir / "plan-execution.yaml.tmp").exists()


def test_plan_mutation_cli_stale_plan_is_domain_refusal_without_write(tmp_path):
    mutation_repo(tmp_path, stale=True)
    before = execution_bytes(tmp_path)

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "PLAN_STALE\n",
    )
    assert execution_bytes(tmp_path) == before


def test_plan_mutation_cli_malformed_task_is_invalid_state_without_write(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    before = execution_bytes(tmp_path)
    (harness_dir / "current-task.yaml").write_text("[")

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert execution_bytes(tmp_path) == before


def test_plan_mutation_cli_malformed_plan_is_invalid_state_without_write(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    before = execution_bytes(tmp_path)
    (harness_dir / "plan.yaml").write_text("[")

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INVALID_HARNESS_STATE:")
    assert execution_bytes(tmp_path) == before


@pytest.mark.parametrize('protocol', ['v1', 'v2'])
@pytest.mark.parametrize('entry', ['cli', 'domain'])
def test_plan_upgrade_refuses_pending_partial_publication(tmp_path, protocol, entry):
    """Break caught: upgrade writes an active recovery member and strands recovery."""
    from test_plan_mutation import tree_bytes

    from harness import plan_reconciliation, publication_journal, transaction_recovery
    from harness.telemetry_lock import telemetry_lock

    root = mutation_repo(tmp_path)
    task_path, execution_path = root / 'current-task.yaml', root / 'plan-execution.yaml'
    task_bytes = task_path.read_bytes()
    task = yaml.safe_load(task_bytes)
    execution = yaml.safe_load(execution_path.read_text())
    legacy = {'version': 1, 'plan': execution['plan'], 'items': {'P-001': {'status': 'PENDING'}}}
    execution_path.write_text(yaml.safe_dump(legacy, sort_keys=False))
    original = execution_path.read_bytes()
    changed = yaml.safe_load(task_bytes)
    changed['budget']['context_expansions'] = changed['budget'].get('context_expansions', 0) + 1
    partial = yaml.safe_dump(changed, sort_keys=False).encode()
    with telemetry_lock(root):
        if protocol == 'v1':
            transaction_recovery.begin(root, [(task_path, task_bytes, partial),
                                              (execution_path, original, original + b'\n')])
            task_path.write_bytes(partial)
        else:
            with publication_journal.prepare(root, (
                publication_journal.Member('current-task.yaml', task_bytes, partial),
                publication_journal.Member('plan-execution.yaml', original, original + b'\n'),
            )) as operation:
                operation._save(state='APPLYING')
                operation._step(0, 'forward')
    before = tree_bytes(root)
    if entry == 'cli':
        result = cli(tmp_path, 'plan', 'upgrade-execution')
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    else:
        try:
            plan_reconciliation.mutate_plan_execution(root, task, plan_reconciliation.PlanMutationRequest(action='UPGRADE_EXECUTION'))
            code, stdout, stderr = 0, '', ''
        except transaction_recovery.PublicationAdmissionError as error:
            code, stdout, stderr = 2, '', str(error)
    after = tree_bytes(root)
    recovery_error = None
    with telemetry_lock(root):
        try:
            transaction_recovery.recover_pending_publications(root)
        except OSError as error:
            recovery_error = str(error)
    changed_paths = [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)]
    assert code == 2, f'pending plan exit={code}; changed={changed_paths}; recovery={recovery_error}'
    assert stdout == '' and 'TRANSACTION_RECOVERY_REQUIRED' in stderr
    assert after == before and recovery_error is None
    assert task_path.read_bytes() == task_bytes and execution_path.read_bytes() == original


@pytest.mark.parametrize('action', ['begin', 'block', 'resume', 'reconcile', 'refresh-proof', 'upgrade-execution'])
def test_plan_command_pending_refuses_before_task_read(tmp_path, monkeypatch, capsys, action):
    from types import SimpleNamespace

    from test_plan_mutation import tree_bytes

    from harness import controlplane, publication_fs, transaction_recovery

    root = mutation_repo(tmp_path)
    pending = root / '.transactions'
    pending.mkdir(exist_ok=True)
    (pending / 'pending.json').write_text('{"version":999}')
    before = tree_bytes(root)
    monkeypatch.chdir(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError('Plan task fact/recovery/probe reached before pending refusal')

    monkeypatch.setattr(controlplane, 'load_task', forbidden)
    monkeypatch.setattr(transaction_recovery, 'recover_pending_publications', forbidden)
    monkeypatch.setattr(publication_fs, 'check_capabilities', forbidden)
    assert controlplane.cmd_plan_mutation(SimpleNamespace(plan_command=action)) == 2
    output = capsys.readouterr()
    assert output.out == '' and 'TRANSACTION_RECOVERY_REQUIRED' in output.err
    assert tree_bytes(root) == before


def test_plan_command_owner_teardown_failure_is_bounded(tmp_path, monkeypatch, capsys):
    import fcntl
    from types import SimpleNamespace

    from harness import controlplane, plan_reconciliation

    root = mutation_repo(tmp_path)
    path = root / 'plan-execution.yaml'
    execution = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({'version': 1, 'plan': execution['plan'], 'items': {}}))
    monkeypatch.chdir(tmp_path)
    real_write, real_flock = plan_reconciliation.atomic_write, fcntl.flock
    persisted, released = [], []

    def wrote(*args, **kwargs):
        real_write(*args, **kwargs)
        persisted.append(True)

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN and persisted:
            released.append(True)
            raise OSError('private-plan-cleanup-data')
        return real_flock(fd, operation)

    monkeypatch.setattr(plan_reconciliation, 'atomic_write', wrote)
    monkeypatch.setattr(fcntl, 'flock', failed_release)
    assert controlplane.cmd_plan_mutation(SimpleNamespace(plan_command='upgrade-execution')) == 2
    output = capsys.readouterr()
    assert persisted == [True] and released == [True]
    assert 'PUBLICATION_LOCK_TEARDOWN_FAILED' in output.err and 'private-plan-cleanup-data' not in output.err
    assert yaml.safe_load(path.read_text())['version'] == 2


@pytest.mark.parametrize('entry', ['cli', 'domain'])
@pytest.mark.parametrize('primary', [OSError('plan-body-io'), KeyboardInterrupt('plan-cancel')])
def test_plan_mutation_primary_survives_owner_cleanup(tmp_path, monkeypatch, entry, primary):
    import fcntl
    from types import SimpleNamespace

    from harness import controlplane, plan_reconciliation

    root = mutation_repo(tmp_path)
    task = yaml.safe_load((root / 'current-task.yaml').read_text())
    monkeypatch.chdir(tmp_path)
    real_flock = fcntl.flock
    released = []

    def failed_body(*args, **kwargs):
        raise primary

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            released.append(True)
            raise OSError('private-plan-cleanup-data')
        return real_flock(fd, operation)

    monkeypatch.setattr(plan_reconciliation, 'load_plan_artifacts', failed_body)
    monkeypatch.setattr(fcntl, 'flock', failed_release)
    if entry == 'cli' and isinstance(primary, OSError):
        # Existing command policy normalizes body I/O, unlike raw domain API.
        assert controlplane.cmd_plan_mutation(SimpleNamespace(plan_command='upgrade-execution')) == 2
    else:
        with pytest.raises(type(primary)) as error:
            if entry == 'cli':
                controlplane.cmd_plan_mutation(SimpleNamespace(plan_command='upgrade-execution'))
            else:
                plan_reconciliation.mutate_plan_execution(root, task, plan_reconciliation.PlanMutationRequest(action='UPGRADE_EXECUTION'))
        assert error.value is primary
    assert released == [True]


def test_plan_mutation_cli_upgrades_all_pending_v1_and_retries_exactly(tmp_path):
    harness_dir = mutation_repo(tmp_path)
    plan = yaml.safe_load((harness_dir / "plan.yaml").read_text())
    from harness.plan_reconciliation import plan_fingerprint

    legacy = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": {"P-001": {"status": "PENDING"}},
    }
    (harness_dir / "plan-execution.yaml").write_text(
        yaml.safe_dump(legacy, sort_keys=False)
    )

    upgraded = cli(tmp_path, "plan", "upgrade-execution")
    before_retry = execution_bytes(tmp_path)
    retry = cli(tmp_path, "plan", "upgrade-execution")

    assert (upgraded.returncode, upgraded.stdout, upgraded.stderr) == (
        0,
        "PLAN_EXECUTION_UPDATED\n",
        "",
    )
    assert (retry.returncode, retry.stdout, retry.stderr) == (
        0,
        "PLAN_EXECUTION_UNCHANGED\n",
        "",
    )
    assert execution_bytes(tmp_path) == before_retry
    assert yaml.safe_load(before_retry)["version"] == 2


@pytest.mark.parametrize(
    ("profile", "mode", "enabled"),
    [
        ("FAST", "task_and_final", True),
        ("STANDARD", "final", True),
        ("STRICT", "task_and_final", False),
    ],
)
def test_plan_mutation_cli_policy_refuses_before_malformed_plan_read(
    tmp_path, profile, mode, enabled
):
    harness_dir = mutation_repo(tmp_path)
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    task["risk"]["profile"] = profile
    task["risk"]["level"] = {"FAST": "Q1", "STANDARD": "Q2", "STRICT": "Q3"}[profile]
    task["plan_reconciliation"] = (
        {"enabled": enabled, "mode": mode} if enabled else {"enabled": False}
    )
    (harness_dir / "current-task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False)
    )
    (harness_dir / "plan.yaml").write_text("[")
    before = execution_bytes(tmp_path)

    result = cli(tmp_path, "plan", "begin", "P-001")

    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "PLAN_TASK_LEVEL_DISABLED\n",
    )
    assert execution_bytes(tmp_path) == before
