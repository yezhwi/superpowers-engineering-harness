"""Evidence classifications shared by status and quality gate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml
from test_cli_task_recovery import make_repo, run_cli


harness = test_context_builder.harness


@pytest.mark.parametrize('protocol', ['v1', 'v2'])
@pytest.mark.parametrize('entry', ['cli', 'module', 'script'])
def test_status_refuses_pending_partial_publication(harness, capsys, protocol, entry):
    """Break caught: pending publication returns0 and substitutes persisted Gate PASS."""
    from harness import harness_status, publication_journal, transaction_recovery
    from harness.telemetry_lock import telemetry_lock

    task_path, impact_path = harness / 'current-task.yaml', harness / 'impact.yaml'
    original, impact = task_path.read_bytes(), impact_path.read_bytes()
    task = yaml.safe_load(original)
    assert task['gate']['status'] == 'PASS'
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
    if entry == 'module':
        code = harness_status.main(['--harness-dir', str(harness)])
        output = capsys.readouterr()
        stdout, stderr = output.out, output.err
    else:
        if entry == 'cli':
            result = run_cli(harness.parent, 'status')
        else:
            repo = Path(__file__).resolve().parents[1]
            result = subprocess.run([sys.executable, str(repo / 'scripts/harness_status.py'),
                                     '--harness-dir', str(harness)], cwd=harness.parent,
                                    env={**os.environ, 'PYTHONPATH': str(repo / 'src')},
                                    capture_output=True, text=True, timeout=30, check=False)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    assert code == 2, f'pending status consumed: {code}\n{stdout}\n{stderr}'
    assert 'TRANSACTION_RECOVERY_REQUIRED' in stderr
    assert stdout == '' and 'Traceback' not in stderr
    assert {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()} == before
    with telemetry_lock(harness):
        transaction_recovery.recover_pending_publications(harness)
    assert task_path.read_bytes() == original and impact_path.read_bytes() == impact


@pytest.mark.parametrize('state', ['PREPARED', 'APPLYING', 'VALIDATING', 'ABORTING', 'BLOCKED', 'unknown_version'])
def test_status_pending_refusal_precedes_fact_reads(harness, monkeypatch, capsys, state):
    from harness import harness_status, publication_fs, transaction_recovery

    pending = harness / '.transactions'
    pending.mkdir(exist_ok=True)
    (pending / 'pending.json').write_text(json.dumps({'version': 999 if state == 'unknown_version' else 2, 'state': state}))
    before = {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError('facts/recovery/probes consumed before pending refusal')

    monkeypatch.setattr(harness_status, '_load', forbidden)
    monkeypatch.setattr(transaction_recovery, 'recover_pending_publications', forbidden)
    monkeypatch.setattr(publication_fs, 'check_capabilities', forbidden)
    assert harness_status.main(['--harness-dir', str(harness)]) == 2
    output = capsys.readouterr()
    assert output.out == '' and 'TRANSACTION_RECOVERY_REQUIRED' in output.err
    assert {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('failure', ['acquire', 'inspect'])
def test_status_admission_io_failure_is_bounded(harness, monkeypatch, capsys, failure):
    from contextlib import contextmanager
    from importlib import import_module

    from harness import harness_status, transaction_recovery
    from harness.telemetry_lock import _HELD

    held_before = set(getattr(_HELD, 'paths', set()))

    @contextmanager
    def unavailable(*args):
        raise PermissionError('private-status-admission-data')
        yield

    def unreadable(*args):
        raise PermissionError('private-status-admission-data')

    def forbidden(*args):
        raise AssertionError('status facts read before admission failure')

    monkeypatch.setattr(harness_status, '_load', forbidden)
    if failure == 'acquire':
        monkeypatch.setattr(import_module('harness.telemetry_lock'), 'telemetry_lock', unavailable)
    else:
        monkeypatch.setattr(transaction_recovery, 'require_no_pending_publications', unreadable)
    assert harness_status.main(['--harness-dir', str(harness)]) == 2
    output = capsys.readouterr()
    assert output.out == '' and 'TRANSACTION_RECOVERY_BLOCKED: cannot inspect recovery state' in output.err
    assert 'private-status-admission-data' not in output.err and 'Traceback' not in output.err
    assert set(getattr(_HELD, 'paths', set())) == held_before


@pytest.mark.parametrize('invalid_task', [False, True])
def test_status_owner_teardown_failure_does_not_emit_report(harness, monkeypatch, capsys, invalid_task):
    import fcntl

    from harness import harness_status

    real_flock, real_render = fcntl.flock, harness_status._render
    completed = False
    releases = []

    def rendered(*args):
        nonlocal completed
        text = real_render(*args)
        completed = True
        return text

    def invalid(*args):
        nonlocal completed
        completed = True

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN and completed:
            releases.append(True)
            raise OSError('private-status-teardown-data')
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, 'flock', failed_release)
    monkeypatch.setattr(harness_status, '_load' if invalid_task else '_render', invalid if invalid_task else rendered)
    assert harness_status.main(['--harness-dir', str(harness)]) == 2
    output = capsys.readouterr()
    assert releases == [True]
    assert output.out == '' and 'PUBLICATION_LOCK_TEARDOWN_FAILED' in output.err
    assert 'private-status-teardown-data' not in output.err and 'Traceback' not in output.err


@pytest.mark.parametrize('primary', [OSError('primary-status-io'), KeyboardInterrupt('status-cancel')])
def test_status_preserves_body_failure_over_cleanup_failure(harness, monkeypatch, capsys, primary):
    import fcntl

    from harness import harness_status

    real_flock = fcntl.flock
    releases = []

    def failed_body(*args):
        raise primary

    def failed_release(fd, operation):
        if operation == fcntl.LOCK_UN:
            releases.append(True)
            raise OSError('private-secondary-cleanup-data')
        return real_flock(fd, operation)

    monkeypatch.setattr(harness_status, '_load', failed_body)
    monkeypatch.setattr(fcntl, 'flock', failed_release)
    with pytest.raises(type(primary)) as error:
        harness_status.main(['--harness-dir', str(harness)])
    assert error.value is primary
    assert releases == [True]
    output = capsys.readouterr()
    assert output.out == '' and 'private-secondary-cleanup-data' not in output.err


def test_status_committed_retention_does_not_block(harness, capsys):
    from harness import harness_status, publication_journal
    from harness.telemetry_lock import telemetry_lock

    path = harness / 'impact.yaml'
    old = path.read_bytes()
    with telemetry_lock(harness), publication_journal.prepare(harness, (
        publication_journal.Member('impact.yaml', old, old + b'\n'),
    )) as operation:
        operation.apply()
        operation.commit()
    before = {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()}
    assert harness_status.main(['--harness-dir', str(harness)]) == 0
    assert 'State        CLASSIFIED' in capsys.readouterr().out
    assert {str(p.relative_to(harness)): p.read_bytes() for p in harness.rglob('*') if p.is_file()} == before


def fresh_record() -> dict:
    return {
        "type": "build",
        "timestamp": "2026-08-27T00:00:00+00:00",
        "command": "python -m pytest",
        "exit_code": 0,
        "commit": "a" * 40,
        "workspace_fingerprint": "sha256:" + "b" * 64,
        "workspace_fingerprint_after": "sha256:" + "b" * 64,
    }


def test_status_renders_active_decision_summary(tmp_path: Path):
    """Break caught: resumed session cannot see accepted user constraint."""
    from harness.decision import accept, propose
    from harness.init import init_harness

    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    assert init_harness(repo).harness_dir == repo / ".harness"
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    task_path = repo / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))
    proposed = propose(
        repo / ".harness",
        {
            "topic": "pagination",
            "question": "Which pagination?",
            "context": ["clients exist"],
            "options": [{"id": "cursor", "description": "cursor"}],
            "recommendation": {
                "option": "cursor",
                "reasons": ["stable"],
                "tradeoffs": [],
            },
            "scope": [],
            "constraints": [],
        },
    )
    accept(repo / ".harness", proposed["id"], "cursor", "accepted_recommendation")

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "DEC-001 pagination = cursor" in result.stdout


def test_status_renders_public_interface_summary(tmp_path: Path):
    """Break caught: resumed session hides declared public compatibility impact."""
    from harness.init import init_harness

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    init_harness(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    (tmp_path / ".harness" / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "impact": {
                    "changed": [],
                    "direct_dependents": [],
                    "contracts": [],
                    "interfaces": [
                        {
                            "id": "INT-001",
                            "kind": "cli",
                            "visibility": "external",
                            "consumers": ["agent"],
                            "compatibility": "compatible",
                            "affected_contracts": [],
                            "contract_id": "INT-001",
                        }
                    ],
                    "risks": [],
                    "required_tests": [],
                    "full_suite": {"recommended": False, "reason": None},
                }
            }
        )
    )

    result = run_cli(tmp_path, "status")

    assert "Interfaces" in result.stdout
    assert "public changes: 1" in result.stdout
    assert "compatibility: compatible" in result.stdout


def test_projection_marks_current_successful_evidence_fresh(tmp_path: Path):
    """Break caught: status calls a different freshness rule than Gate."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    path = tmp_path / "build.json"
    path.write_text(json.dumps(fresh_record()))

    projection = project_evidence(
        path,
        current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.FRESH
    assert projection.code is None
    assert projection.record["command"] == "python -m pytest"


def test_projection_marks_current_failed_command_failed(tmp_path: Path):
    """Break caught: nonzero current evidence is displayed as stale or fresh."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    record = fresh_record()
    record["exit_code"] = 1
    path = tmp_path / "build.json"
    path.write_text(json.dumps(record))

    projection = project_evidence(
        path,
        current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.FAILED
    assert projection.code == "EVIDENCE_RESULT_MISMATCH"


def test_projection_marks_head_mismatch_stale(tmp_path: Path):
    """Break caught: stale HEAD-bound proof can look valid before Gate."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    path = tmp_path / "build.json"
    path.write_text(json.dumps(fresh_record()))

    projection = project_evidence(
        path,
        current_head="c" * 40,
        current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.STALE
    assert projection.code == "EVIDENCE_HEAD_MISMATCH"


def test_status_summary_matches_fresh_build_evidence(tmp_path: Path):
    """Break caught: FRESH build evidence still prints Build unknown."""
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    from harness.workspace import snapshot

    record = fresh_record()
    record["commit"] = head
    record["workspace_fingerprint"] = snapshot(repo).fingerprint
    record["workspace_fingerprint_after"] = record["workspace_fingerprint"]
    (repo / ".harness/evidence/build.json").write_text(json.dumps(record))
    task_path = repo / ".harness/current-task.yaml"
    before = task_path.read_bytes()

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "Build        unknown" not in result.stdout
    assert "Build        passed" in result.stdout
    assert "evidence/build.json" in result.stdout
    assert task_path.read_bytes() == before


def test_status_summary_marks_stale_build_instead_of_unknown(tmp_path: Path):
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True
    )
    (repo / "app.py").write_text("base\n")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    record = fresh_record()
    record["commit"] = head
    (repo / ".harness/evidence/build.json").write_text(json.dumps(record))
    (repo / "app.py").write_text("changed\n")

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "Build        unknown" not in result.stdout
    assert "Build        stale" in result.stdout
    assert "evidence/build.json" in result.stdout


def test_status_summary_selects_latest_valid_evidence_path(tmp_path: Path):
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    from harness.workspace import snapshot

    fingerprint = snapshot(repo).fingerprint
    older = fresh_record()
    older.update(
        {
            "commit": head,
            "timestamp": "2026-08-27T00:00:00+00:00",
            "workspace_fingerprint": fingerprint,
            "workspace_fingerprint_after": fingerprint,
        }
    )
    newer = dict(older)
    newer["timestamp"] = "2026-08-28T00:00:00+00:00"
    newer["command"] = "python -m build"
    (repo / ".harness/evidence/build.json").write_text(json.dumps(older))
    (repo / ".harness/evidence/build-later.json").write_text(json.dumps(newer))

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "Build        passed" in result.stdout
    assert "evidence/build-later.json" in result.stdout.split("Build", 1)[1].split(
        "Unit Tests", 1
    )[0]


def test_status_projects_stale_evidence_without_mutating_task(tmp_path: Path):
    """Break caught: status trusts persisted verification flags or writes a new truth."""
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "app.py").write_text("base\n")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    record = fresh_record()
    record["commit"] = head
    (repo / ".harness/evidence/build.json").write_text(json.dumps(record))
    task_path = repo / ".harness/current-task.yaml"
    before = task_path.read_bytes()
    (repo / "app.py").write_text("changed\n")

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "build" in result.stdout.lower()
    assert "STALE" in result.stdout
    assert task_path.read_bytes() == before


def test_status_reuses_one_workspace_for_gate(harness, monkeypatch, capsys):
    from harness import harness_status, quality_gate

    walks = 0
    real = quality_gate.snapshot

    def counting(*args, **kwargs):
        nonlocal walks
        walks += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(quality_gate, "snapshot", counting)
    assert harness_status.main(["--harness-dir", str(harness)]) == 0
    assert walks == 0
    assert capsys.readouterr().out


def test_status_rejects_done_with_cached_pass_and_open_canonical_finding(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    task_path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "DONE"
    task["gate"] = {"status": "PASS", "blocked_by": []}
    task_path.write_text(yaml.safe_dump(task))
    (repo / ".harness/findings/FND-001.yaml").write_text(yaml.safe_dump({
        "id": "FND-001", "category": "adversarial", "kind": "failure_scenario", "target": "REQ-001",
        "scenario": "open canonical defect", "severity": "major", "status": "PROPOSED",
    }))

    result = run_cli(repo, "status")

    assert result.returncode == 2
    assert "DONE without current gate PASS" in result.stderr


def test_projection_marks_missing_evidence_missing(tmp_path: Path):
    """Break caught: absent required evidence is indistinguishable from invalid data."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    projection = project_evidence(
        tmp_path / "missing.json",
        current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.MISSING
    assert projection.code == "EVIDENCE_MISSING"
