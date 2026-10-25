"""Only the explicit no-scope legacy path may repair a malformed current ID string."""
import os

import pytest
import yaml
from test_cli_task_recovery import make_repo, run_cli, set_task_state
from test_task_identity import arguments, reserve, setup, tree

from harness._scope_replay import SCOPE_FILES


def legacy(tmp_path, identity):
    repo, harness = setup(tmp_path, "migrate-id")
    # Explicit legacy input fixture, not removal of scope from a live task.
    for name in SCOPE_FILES:
        (harness / name).unlink()
    set_task_state(repo, "CREATED", identity)
    return repo, harness


@pytest.mark.parametrize("identity", ["legacy-bad-id", "", "TASK-x"])
def test_legacy_invalid_current_string_can_be_repaired_without_rewriting_other_facts(tmp_path, identity):
    repo, harness = legacy(tmp_path, identity)
    reserve(harness, "decision")
    original_decision = (harness / "decisions/DEC-001.yaml").read_bytes()
    before = yaml.safe_load((harness / "current-task.yaml").read_text())
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = before
    expected["task"]["id"] = "TASK-006"
    assert yaml.safe_load((harness / "current-task.yaml").read_text()) == expected
    assert (harness / "decisions/DEC-001.yaml").read_bytes() == original_decision
    assert not any((harness / name).exists() for name in SCOPE_FILES)


def test_legacy_unassigned_null_binds_without_creating_scope_or_rewriting_other_facts(tmp_path):
    repo, harness = legacy(tmp_path, None)
    reserve(harness, "decision")
    original_decision = (harness / "decisions/DEC-001.yaml").read_bytes()
    expected = yaml.safe_load((harness / "current-task.yaml").read_text())
    assert expected["task"]["id"] is None
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 0, result.stdout + result.stderr
    expected["task"]["id"] = "TASK-006"
    assert yaml.safe_load((harness / "current-task.yaml").read_text()) == expected
    assert (harness / "decisions/DEC-001.yaml").read_bytes() == original_decision
    assert not any((harness / name).exists() for name in SCOPE_FILES)


def test_cli_genesis_unassigned_null_binds_task_and_existing_scope(tmp_path):
    repo = make_repo(tmp_path)
    harness = repo / ".harness"
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["task"]["id"] is None
    for name in SCOPE_FILES:
        assert yaml.safe_load((harness / name).read_text())["task_id"] is None
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["task"]["id"] == "TASK-006"
    for name in SCOPE_FILES:
        assert yaml.safe_load((harness / name).read_text())["task_id"] == "TASK-006"


@pytest.mark.parametrize("identity", ["legacy-bad-id", None], ids=["invalid-string", "unassigned-null"])
@pytest.mark.parametrize("source", ["history-name", "history-document", "decision", "decision-index"])
def test_legacy_repair_still_rejects_occupied_target_and_numeric_alias(tmp_path, source, identity):
    repo, harness = legacy(tmp_path, identity)
    reserve(harness, source)
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-5")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_ALREADY_USED" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("identity", ["legacy-bad-id", None], ids=["invalid-string", "unassigned-null"])
@pytest.mark.parametrize("kind", ["history-owner", "decision-owner", "index-owner", "bad-yaml", "symlink", "fifo"])
def test_legacy_repair_does_not_skip_invalid_other_identity_sources(tmp_path, kind, identity):
    repo, harness = legacy(tmp_path, identity)
    path = harness / "decisions/DEC-001.yaml"
    if kind == "history-owner":
        path = harness / "history/legacy/current-task.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("task:\n  id: another-bad-identity\n")
    elif kind == "decision-owner":
        path.write_text("task_id: another-bad-identity\n")
    elif kind == "index-owner":
        (harness / "decisions/index.yaml").write_text("decisions:\n- task_id: another-bad-identity\n")
    elif kind == "bad-yaml":
        path.write_text("task_id: [broken\n")
    elif kind == "symlink":
        external = repo / "external.yaml"
        external.write_text("task_id: TASK-007\n")
        path.symlink_to(external)
    else:
        os.mkfifo(path)
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("operation,state", [("new", "DONE"), ("recover", "IMPLEMENTING")])
def test_invalid_current_identity_is_not_ignored_for_replacement(tmp_path, operation, state):
    repo, harness = legacy(tmp_path, "legacy-bad-id")
    set_task_state(repo, state, "legacy-bad-id")
    before = tree(harness)
    result = run_cli(repo, *arguments(operation, "TASK-006"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("scope", ["all", "one", "dangling"])
def test_scope_artifact_presence_cannot_select_legacy_repair(tmp_path, scope):
    repo, harness = setup(tmp_path, "migrate-id")
    set_task_state(repo, "CREATED", "legacy-bad-id")
    if scope != "all":
        for name in SCOPE_FILES:
            (harness / name).unlink()
        path = harness / SCOPE_FILES[0]
        if scope == "dangling":
            path.symlink_to(repo / "missing-scope")
        else:
            path.write_text("version: 1\n")
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("identity", [5, True, [], {}])
def test_structurally_invalid_current_owner_is_not_legacy_string_repair(tmp_path, identity):
    repo, harness = legacy(tmp_path, identity)
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("task_field", ["missing", None, [], "not a mapping"])
def test_missing_task_structure_is_not_reconstructed_by_legacy_repair(tmp_path, task_field):
    repo, harness = legacy(tmp_path, "legacy-bad-id")
    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    if task_field == "missing":
        task.pop("task")
    else:
        task["task"] = task_field
    path.write_text(yaml.safe_dump(task))
    before = tree(harness)
    result = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "TASK_ID_RESERVATION_INVALID" in result.stderr
    assert "Traceback" not in result.stderr
    assert tree(harness) == before


@pytest.mark.parametrize("migration,repair", [(True, False), (False, True), (False, False)])
def test_guard_does_not_infer_legacy_repair_from_migration_alone(tmp_path, migration, repair):
    from harness.task_identity import TaskIdentityError, require_available

    root = tmp_path / ".harness"
    root.mkdir()
    with pytest.raises(TaskIdentityError, match="TASK_ID_RESERVATION_INVALID"):
        require_available(root, "TASK-006", {"task": {"id": "legacy-bad-id"}},
                          migration=migration, legacy_repair=repair)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("damage", ["bad-yaml", "fifo", "directory-symlink"])
def test_same_id_legacy_exception_does_not_certify_reservation_sources(tmp_path, damage):
    repo, harness = legacy(tmp_path, "TASK-004")
    path = harness / "decisions/DEC-001.yaml"
    if damage == "bad-yaml":
        path.write_text("task_id: [broken\n")
    elif damage == "fifo":
        os.mkfifo(path)
    else:
        (harness / "decisions").rename(repo / "original-decisions")
        (harness / "decisions").symlink_to(repo / "missing-decisions", target_is_directory=True)
    original_sources = tree(harness / "decisions") if damage != "directory-symlink" else os.readlink(harness / "decisions")
    same = run_cli(repo, "task", "migrate-id", "TASK-004")
    assert same.returncode == 0, same.stdout + same.stderr
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["task"]["id"] == "TASK-004"
    if damage != "directory-symlink":
        assert tree(harness / "decisions") == original_sources
    else:
        assert os.readlink(harness / "decisions") == original_sources
    before_new_identity = tree(harness)
    different = run_cli(repo, "task", "migrate-id", "TASK-006")
    assert different.returncode == 2, different.stdout + different.stderr
    assert "TASK_ID_RESERVATION_INVALID" in different.stderr
    assert tree(harness) == before_new_identity
