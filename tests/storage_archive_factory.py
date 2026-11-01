"""Explicit committed-index fixtures; never production archive writers."""
import hashlib
import json

from storage_factory import identity


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def install_archive(repo, *, archive_id="b" * 32, generation_id="3" * 32,
                    alias="TASK-7-snapshot", task_id="TASK-7", original_root=None):
    store = repo / ".harness-store"
    origin = {"workspace_id": "2" * 32, "generation_id": generation_id,
              "original_workspace_root": str(original_root or repo)}
    obj = store / "history/archives" / archive_id
    obj.mkdir(mode=0o700)
    content = b"requirements: []\n"
    member = obj / "requirements.yaml"
    member.write_bytes(content)
    task = obj / "current-task.yaml"
    task.write_bytes(encoded({"task": {"id": task_id}}))
    descriptor = {"version": 1, "kind": "storage_archive", "archive_id": archive_id,
                  "task_id": task_id, "origin": origin, "object_identity": identity(obj),
                  "source_snapshot": {"operation_id": "a" * 32, "source_identity": identity(obj),
                                      "manifest_digest": "8" * 64},
                  "parents": {".": identity(obj)},
                  "members": {p.name: {"identity": identity(p), "size": p.stat().st_size,
                                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in (member, task)}}
    descriptor_path = obj / "archive.yaml"
    descriptor_path.write_bytes(encoded(descriptor))
    record = {"archive_id": archive_id, "task_id": task_id, "origin": origin,
              "object_identity": identity(obj), "descriptor_identity": identity(descriptor_path),
              "descriptor_sha256": hashlib.sha256(descriptor_path.read_bytes()).hexdigest(),
              "receipt_id": "a" * 32}
    index_path = store / "history/index.yaml"
    index = json.loads(index_path.read_bytes()) if index_path.exists() else {
        "version": 1, "kind": "storage_history", "store_id": "1" * 32,
        "workspace_id": "2" * 32, "archives": {}, "aliases": [], "reserved_task_ids": [],
    }
    index["archives"][archive_id] = record
    index["aliases"].append({"origin": origin, "logical_archive_alias": alias, "archive_id": archive_id})
    if task_id not in index["reserved_task_ids"]:
        index["reserved_task_ids"].append(task_id)
    index_path.write_bytes(encoded(index))
    token = {"version": 1, "origin": origin, "logical_archive_alias": alias,
             "selected_alias_record_digest": hashlib.sha256(encoded({"alias": index["aliases"][-1], "record": record})).hexdigest(),
             "archive_id": archive_id, "archive_descriptor_digest": record["descriptor_sha256"],
             "member_path": "requirements.yaml", "member_identity": identity(member),
             "member_content_digest": hashlib.sha256(content).hexdigest()}
    reference = {"ref": f".harness/history/{alias}/requirements.yaml",
                 "sha256": "sha256:" + hashlib.sha256(content).hexdigest(), "storage": token}
    return origin, member, reference
