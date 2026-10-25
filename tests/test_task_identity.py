"""Task entrypoints must not associate a new task with an older task's decisions."""
import json
import os
import stat

import pytest
import yaml
from test_cli_task_recovery import run_cli, set_task_state
from test_decision import proposal
from test_task_replacement import committed_repo

from harness import decision


def tree(root):
    """Synthetic fixture tree only. Never traverse a live acceptance-probe tree."""
    result = {}
    for path in root.rglob("*"):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        value = (info.st_dev, info.st_ino, info.st_mode)
        if stat.S_ISREG(info.st_mode):
            value += (path.read_bytes(),)
        elif stat.S_ISLNK(info.st_mode):
            value += (os.readlink(path),)
        result[relative] = value
    return result


def arguments(operation, target):
    if operation == "recover":
        return "task", "recover", target, "--reason", "identity regression fixture"
    return "task", operation, target


def setup(tmp_path, operation):
    repo = committed_repo(tmp_path)
    if operation != "migrate-id":
        set_task_state(repo, "DONE" if operation == "new" else "IMPLEMENTING")
    return repo, repo / ".harness"


def reserve(harness, source):
    if source in {"decision", "decision-index"}:
        # Produce an actual valid persistent decision belonging to an older task.
        path = harness / "current-task.yaml"
        original = path.read_bytes()
        task = yaml.safe_load(original)
        task["task"]["id"] = "TASK-005"
        path.write_text(yaml.safe_dump(task))
        decision.propose(harness, proposal())
        path.write_bytes(original)
        if source == "decision-index":
            (harness / "decisions/DEC-001.yaml").unlink()  # Unit fixture: only index retains old ownership.
    else:
        archive = harness / "history" / "TASK-005-20200101000000"
        if source == "history-document":
            archive = harness / "history" / "legacy-archive"
        archive.mkdir(parents=True)
        if source != "history-name":
            (archive / "current-task.yaml").write_text("task:\n  id: TASK-005\nstate: DONE\n")


@pytest.mark.parametrize("operation", ["new", "recover", "migrate-id"])
@pytest.mark.parametrize("source", ["history-name", "history-document", "decision", "decision-index"])
def test_task_entry_rejects_existing_identity_before_any_mutation(tmp_path, operation, source):
    repo, harness = setup(tmp_path, operation)
    reserve(harness, source)
    before = tree(harness)
    result = run_cli(repo, *arguments(operation, "TASK-005"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before
    assert not list(repo.glob("..harness.replacement-*"))


@pytest.mark.parametrize("operation", ["new", "recover"])
def test_replacement_cannot_reuse_current_id(tmp_path, operation):
    repo, harness = setup(tmp_path, operation)
    before = tree(harness)
    result = run_cli(repo, *arguments(operation, "TASK-004"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("operation", ["new", "recover", "migrate-id"])
def test_leading_zero_alias_cannot_evade_identity_reservation(tmp_path, operation):
    repo, harness = setup(tmp_path, operation)
    reserve(harness, "decision")
    before = tree(harness)
    result = run_cli(repo, *arguments(operation, "TASK-5"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("operation", ["new", "recover", "migrate-id"])
def test_fresh_identity_does_not_inherit_old_decision(tmp_path, operation):
    repo, harness = setup(tmp_path, operation)
    reserve(harness, "decision")
    old = (harness / "decisions/DEC-001.yaml").read_bytes()
    result = run_cli(repo, *arguments(operation, "TASK-006"))
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    assert task["task"]["id"] == "TASK-006"
    assert task["state"] == "CREATED"
    assert (harness / "decisions/DEC-001.yaml").read_bytes() == old
    assert [row for row in decision.load_decisions(harness) if row["task_id"] == task["task"]["id"]] == []


@pytest.mark.parametrize("operation", ["new", "recover", "migrate-id"])
@pytest.mark.parametrize("source", ["history", "decision", "decision-index"])
@pytest.mark.parametrize("kind", ["malformed", "not_mapping", "missing_identity", "symlink", "fifo"])
def test_unreadable_identity_sources_fail_closed_without_mutation(tmp_path, operation, source, kind):
    repo, harness = setup(tmp_path, operation)
    if source == "history":
        directory = harness / "history" / "legacy-archive"
        directory.mkdir(parents=True)
        path = directory / "current-task.yaml"
    else:
        path = harness / ("decisions/index.yaml" if source == "decision-index" else "decisions/DEC-001.yaml")
        path.unlink(missing_ok=True)
    if kind == "malformed":
        path.write_text("task: [broken\n")
    elif kind == "not_mapping":
        path.write_text("[]\n")
    elif kind == "missing_identity":
        path.write_text("unrelated: true\n")
    elif kind == "symlink":
        outside = repo / "outside.yaml"
        outside.write_text("task_id: TASK-007\ntask:\n  id: TASK-007\n")
        path.symlink_to(outside)
    else:
        os.mkfifo(path)
    before = tree(harness)
    result = run_cli(repo, *arguments(operation, "TASK-006"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert "Traceback" not in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("directory", ["history", "decisions"])
def test_identity_directory_symlink_is_not_followed(tmp_path, directory):
    repo, harness = setup(tmp_path, "new")
    path = harness / directory
    if path.exists():
        path.rename(repo / f"original-{directory}")
    path.symlink_to(repo / "missing", target_is_directory=True)
    before = tree(harness)
    result = run_cli(repo, "task", "new", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("task_id", ["TASK-005", "TASK-007"])
def test_history_name_and_declared_identity_both_reserve_ids(tmp_path, task_id):
    repo, harness = setup(tmp_path, "new")
    archive = harness / "history/TASK-005-legacy"
    archive.mkdir(parents=True)
    (archive / "current-task.yaml").write_text("task:\n  id: TASK-007\n")
    before = tree(harness)
    result = run_cli(repo, "task", "new", task_id)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before


def test_already_bound_scope_cannot_be_renamed_by_migration(tmp_path):
    repo, harness = setup(tmp_path, "migrate-id")
    assert run_cli(repo, "task", "migrate-id", "TASK-006").returncode == 0
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-007")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TEST_SCOPE_AUDIT_INVALID" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("records", [None, {}, "not a list", [None], [{}]])
def test_malformed_decision_index_cannot_be_treated_as_no_reservations(tmp_path, records):
    repo, harness = setup(tmp_path, "migrate-id")
    (harness / "decisions/index.yaml").write_text(yaml.safe_dump({"decisions": records}))
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("operation", ["new", "recover"])
def test_collision_refuses_before_copying_opaque_or_large_trees(tmp_path, monkeypatch, operation):
    from harness import controlplane

    repo, harness = setup(tmp_path, operation)
    reserve(harness, "history-name")
    probe = harness / "acceptance-probes"
    probe.mkdir()
    os.mkfifo(probe / "must-not-open")
    before = tree(harness)
    monkeypatch.chdir(repo)

    def cannot_copy(*args):
        pytest.fail("identity collision reached replacement copying")

    monkeypatch.setattr(controlplane, "replacement_workspace", cannot_copy)
    if operation == "new":
        result = controlplane.cmd_task_new("TASK-005")
    else:
        result = controlplane.cmd_task_recover("TASK-005", "fixture", "fixture")
    assert result == 2
    assert tree(harness) == before


def test_competing_recoveries_cannot_both_claim_same_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    repo, harness = setup(tmp_path, "recover")
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(run_cli, repo, *arguments("recover", "TASK-006")) for _ in range(2)]
        results = [call.result(timeout=30) for call in calls]
    assert sum(result.returncode == 0 for result in results) == 1, [(r.returncode, r.stderr) for r in results]
    assert all(result.returncode in {0, 2} for result in results)
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["task"]["id"] == "TASK-006"
    assert not list((harness / "history").glob("TASK-006-*"))


def test_guard_ignores_non_authoritative_probe_and_retained_storage(tmp_path):
    from harness.task_identity import require_available

    root = tmp_path / ".harness"
    root.mkdir()
    for name in ("acceptance-probes", "acceptance-artifacts", ".publication-retained"):
        path = root / name
        path.mkdir()
        os.mkfifo(path / "current-task.yaml")
    before = tree(root)
    require_available(root, "TASK-006", {"task": {"id": "TASK-004"}})
    assert tree(root) == before


def test_legacy_same_id_migration_is_not_new_identity_creation(tmp_path):
    from harness._scope_replay import SCOPE_FILES

    repo, harness = setup(tmp_path, "migrate-id")
    for name in SCOPE_FILES:
        (harness / name).unlink()
    set_task_state(repo, "CREATED", "TASK-004")
    reserve(harness, "decision")
    original = (harness / "decisions/DEC-001.yaml").read_bytes()
    result = run_cli(repo, "task", "migrate-id", "TASK-004")
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["task"]["id"] == "TASK-004"
    assert (harness / "decisions/DEC-001.yaml").read_bytes() == original
    assert not any((harness / name).exists() for name in SCOPE_FILES)


def test_decision_discovery_matches_existing_consumer_glob(tmp_path):
    repo, harness = setup(tmp_path, "new")
    reserve(harness, "decision")
    # load_decisions consumes DEC-*.yaml, not only numeric filenames.
    (harness / "decisions/DEC-001.yaml").rename(harness / "decisions/DEC-legacy.yaml")
    (harness / "decisions/index.yaml").unlink()
    assert decision.load_decisions(harness)[0]["task_id"] == "TASK-005"
    before = tree(harness)
    result = run_cli(repo, "task", "new", "TASK-005")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("identity", [5, True, [], {}, "not-a-task", None])
def test_invalid_decision_owner_is_not_an_unused_identity(tmp_path, identity):
    repo, harness = setup(tmp_path, "migrate-id")
    (harness / "decisions/DEC-001.yaml").write_text(yaml.safe_dump({"task_id": identity}))
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert tree(harness) == before


def test_scope_binding_sdk_cannot_bypass_identity_reservation(tmp_path):
    from harness.test_scope import bind_scope_identity

    _repo, harness = setup(tmp_path, "migrate-id")
    reserve(harness, "decision")
    before = tree(harness)
    with pytest.raises(ValueError, match="TASK_ID_ALREADY_USED"):
        bind_scope_identity(harness, "TASK-005")
    assert tree(harness) == before


def test_native_history_collision_cannot_make_old_decision_current(tmp_path):
    repo = committed_repo(tmp_path)
    harness = repo / ".harness"
    assert run_cli(repo, "task", "migrate-id", "TASK-005").returncode == 0
    decision.propose(harness, proposal())
    replaced = run_cli(repo, "task", "recover", "TASK-006", "--reason", "anonymous old-task fixture")
    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    set_task_state(repo, "DONE", "TASK-006")  # Terminal fixture setup, not Gate qualification.
    before = tree(harness)
    result = run_cli(repo, "task", "new", "TASK-005")
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    inherited = [row["id"] for row in decision.load_decisions(harness) if row["task_id"] == task["task"]["id"]]
    assert result.returncode == 2, json.dumps({"stdout": result.stdout, "stderr": result.stderr,
                                             "current_id": task["task"]["id"], "old_decisions_now_current": inherited})
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before
