"""Unknown history origins may not fall back to another generation."""
import json

import pytest
from storage_factory import fixture_store, repository


@pytest.mark.parametrize("reserved", ["TASK-7", "TASK-0007"])
def test_bound_aborted_candidate_id_reservation_survives_without_visible_archive(tmp_path, reserved):
    from harness.storage import admit_storage
    from harness.task_identity import TaskIdentityError, require_available

    repo = repository(tmp_path)
    store, header, _ = fixture_store(repo)
    (store / "history/index.yaml").write_text(json.dumps({
        "version": 1, "kind": "storage_history", "store_id": header["store_id"],
        "workspace_id": header["workspace_id"], "archives": {}, "aliases": [],
        "reserved_task_ids": [reserved],
    }))
    with admit_storage(repo / ".harness"):
        with pytest.raises(TaskIdentityError, match="TASK_ID_ALREADY_USED"):
            require_available(repo / ".harness", "TASK-007", {"task": {"id": "TASK-002"}})


def test_unknown_bound_registry_never_falls_back_to_empty_legacy_history(tmp_path):
    from harness.storage import admit_storage
    from harness.task_identity import TaskIdentityError, require_available

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / "history/index.yaml").write_text('{"version":999}')
    with admit_storage(repo / ".harness"):
        with pytest.raises(TaskIdentityError, match="TASK_ID_RESERVATION_INVALID"):
            require_available(repo / ".harness", "TASK-007", {"task": {"id": "TASK-002"}})


@pytest.mark.parametrize("form", ["relative", "harness", "absolute", "digest-fragment"])
def test_supported_legacy_forms_resolve_only_explicit_owner_generation(tmp_path, form):
    from harness.storage import ReferenceOrigin, admit_storage, resolve_archive
    from storage_archive_factory import install_archive

    repo = repository(tmp_path)
    fixture_store(repo)
    origin, member, reference = install_archive(repo)
    references = {
        "relative": "history/TASK-7-snapshot/requirements.yaml",
        "harness": reference["ref"],
        "absolute": str(repo / reference["ref"]),
        "digest-fragment": reference["ref"] + "#" + reference["sha256"],
    }
    with admit_storage(repo / ".harness") as session:
        handle = resolve_archive(session, references[form], ReferenceOrigin(**origin))
        assert handle.read_bytes() == member.read_bytes()
        assert handle.token == reference["storage"]


def test_same_archive_alias_in_two_generations_never_falls_back(tmp_path):
    from harness.storage import ReferenceOrigin, StorageError, admit_storage, resolve_archive
    from storage_archive_factory import install_archive

    repo = repository(tmp_path)
    fixture_store(repo)
    first, _, _ = install_archive(repo)
    second, _, _ = install_archive(repo, archive_id="c" * 32, generation_id="4" * 32)
    ref = "history/TASK-7-snapshot/requirements.yaml"
    with admit_storage(repo / ".harness") as session:
        a = resolve_archive(session, ref, ReferenceOrigin(**first))
        b = resolve_archive(session, ref, ReferenceOrigin(**second))
        assert a.token["archive_id"] == "b" * 32
        assert b.token["archive_id"] == "c" * 32
        with pytest.raises(StorageError, match="STORE_REFERENCE_AMBIGUOUS"):
            resolve_archive(session, ref, None)
        with pytest.raises(StorageError, match="STORE_REFERENCE_AMBIGUOUS"):
            resolve_archive(session, ref, ReferenceOrigin("2" * 32, "5" * 32, str(repo)))


def test_absolute_old_workspace_requires_registered_origin_not_string_replacement(tmp_path):
    from harness.storage import ReferenceOrigin, StorageError, admit_storage, resolve_archive
    from storage_archive_factory import install_archive

    repo = repository(tmp_path)
    fixture_store(repo)
    origin, _, _ = install_archive(repo, original_root="/explicit-old-workspace")
    with admit_storage(repo / ".harness") as session:
        handle = resolve_archive(session, "/explicit-old-workspace/.harness/history/TASK-7-snapshot/requirements.yaml", ReferenceOrigin(**origin))
        assert handle.read_bytes() == b"requirements: []\n"
        with pytest.raises(StorageError, match="STORE_REFERENCE_AMBIGUOUS"):
            resolve_archive(session, str(repo / ".harness/history/TASK-7-snapshot/requirements.yaml"), ReferenceOrigin(**origin))


@pytest.mark.parametrize("damage", ["descriptor-inode", "member-inode", "missing-member", "missing-alias", "duplicate-alias"])
def test_missing_or_replaced_selected_object_fails_closed(tmp_path, damage):
    from harness.storage import ReferenceOrigin, StorageError, admit_storage, resolve_archive
    from storage_archive_factory import install_archive

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    origin, member, _ = install_archive(repo)
    if damage in {"descriptor-inode", "member-inode"}:
        path = member if damage == "member-inode" else member.parent / "archive.yaml"
        raw = path.read_bytes()
        path.rename(path.with_name("parked"))
        path.write_bytes(raw)
    elif damage == "missing-member":
        member.rename(member.with_name("parked"))
    else:
        path = store / "history/index.yaml"
        index = json.loads(path.read_bytes())
        index["aliases"] = [] if damage == "missing-alias" else index["aliases"] * 2
        path.write_text(json.dumps(index))
    with admit_storage(repo / ".harness") as session, pytest.raises(StorageError):
        resolve_archive(session, "history/TASK-7-snapshot/requirements.yaml", ReferenceOrigin(**origin))


def test_registry_and_archived_task_document_disagreement_refuses_new_identity(tmp_path):
    import hashlib

    from harness.storage import admit_storage
    from harness.task_identity import TaskIdentityError, require_available
    from storage_archive_factory import encoded, install_archive
    from storage_factory import identity

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    _, member, _ = install_archive(repo)
    task = member.parent / "current-task.yaml"
    task.write_bytes(encoded({"task": {"id": "TASK-99"}}))
    # Honest bytes/identities, but conflicting domain identities. Not an I/O failure.
    path = member.parent / "archive.yaml"
    descriptor = json.loads(path.read_bytes())
    descriptor["members"]["current-task.yaml"] = {
        "identity": identity(task), "size": task.stat().st_size,
        "sha256": hashlib.sha256(task.read_bytes()).hexdigest(),
    }
    path.write_bytes(encoded(descriptor))
    index_path = store / "history/index.yaml"
    index = json.loads(index_path.read_bytes())
    index["archives"]["b" * 32]["descriptor_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_bytes(encoded(index))
    with admit_storage(repo / ".harness"), pytest.raises(TaskIdentityError, match="TASK_ID_RESERVATION_INVALID"):
        require_available(repo / ".harness", "TASK-100", {"task": {"id": "TASK-002"}})


def test_original_archive_alias_identity_cannot_escape_persistent_reservations(tmp_path):
    from harness.storage import admit_storage
    from harness.task_identity import TaskIdentityError, require_available
    from storage_archive_factory import install_archive

    repo = repository(tmp_path)
    fixture_store(repo)
    install_archive(repo, alias="TASK-99-old-name", task_id="TASK-7")
    with admit_storage(repo / ".harness"), pytest.raises(TaskIdentityError, match="TASK_ID_RESERVATION_INVALID"):
        require_available(repo / ".harness", "TASK-99", {"task": {"id": "TASK-002"}})


def test_missing_archive_is_not_fuzzy_matched(tmp_path):
    from harness.storage import ReferenceOrigin, StorageError, admit_storage, resolve_archive

    repo = repository(tmp_path)
    fixture_store(repo)
    origin = ReferenceOrigin("2" * 32, "3" * 32, str(repo.resolve()))
    with admit_storage(repo / ".harness") as session:
        with pytest.raises(StorageError):
            resolve_archive(session, "history/TASK-999/requirements.yaml", origin)
