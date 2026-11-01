"""Origin-qualified stable history. Index is authority, never a rebuild cache."""
import base64
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import io
import json
from pathlib import Path
import re

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.schema_resources import read_schema
from harness.transaction_recovery import _locked
from .layout import StorageError, _directory_identity, require_layout_admission

_LIMIT = 16 * 1024 * 1024


def _document(path, repo, selection=None):
    if selection is None:
        snapshot = source_access.read_regular_snapshot_beneath(path, repo, max_bytes=_LIMIT)
    else:
        snapshot, _ = source_access.read_history_selection_beneath(path, repo, selector=selection)
    value = yaml.safe_load(snapshot.content)
    try:
        validate(value, read_schema("storage-history.schema.json"))
    except (ValidationError, TypeError, ValueError) as error:
        raise StorageError("STORE_IDENTITY_CHANGED") from error
    return value


def load_history(harness_root, *, selection=None):
    root = Path(harness_root).absolute()
    _locked(root)
    layout = require_layout_admission(root)
    if layout.mode != "bound":
        raise StorageError("STORE_IDENTITY_CHANGED")
    value = _document(root.parent / ".harness-store/history/index.yaml", root.parent, selection)
    header = layout.identity["header"]
    if (value["kind"] != "storage_history" or value["store_id"] != header["store_id"]
            or value["workspace_id"] != header["workspace_id"]):
        raise StorageError("STORE_IDENTITY_CHANGED")
    return _validate_index(value)


def _validate_index(value):
    validate(value, read_schema("storage-history.schema.json"))
    if value["kind"] != "storage_history":
        raise StorageError("STORE_IDENTITY_CHANGED")
    reserved = set(value["reserved_task_ids"])
    reserved_numbers = {item.split("-", 1)[1].lstrip("0") or "0" for item in reserved}
    aliases = set()
    for archive_id, record in value["archives"].items():
        if (archive_id != record["archive_id"] or record["task_id"] not in reserved
                or record["origin"]["workspace_id"] != value["workspace_id"]):
            raise StorageError("STORE_IDENTITY_CHANGED")
    for entry in value["aliases"]:
        origin = entry["origin"]
        named = re.match(r"^TASK-([0-9]+)(?:-|$)", entry["logical_archive_alias"])
        if named and (named[1].lstrip("0") or "0") not in reserved_numbers:
            raise StorageError("STORE_IDENTITY_CHANGED")
        key = (origin["workspace_id"], origin["generation_id"], origin["original_workspace_root"],
               entry["logical_archive_alias"])
        record = value["archives"].get(entry["archive_id"])
        if key in aliases or record is None or record["origin"] != origin:
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        aliases.add(key)
    return value


def _selected_projection(raw, selector):
    """Stable selected-entry token, not a substituted hash for mutable bytes."""
    try:
        selected = json.loads(selector)
        if not isinstance(selected, dict) or set(selected) != {"origin", "logical_archive_alias"}:
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        value = _validate_index(yaml.safe_load(raw))
        matches = [entry for entry in value["aliases"]
                   if entry["origin"] == selected["origin"]
                   and entry["logical_archive_alias"] == selected["logical_archive_alias"]]
        if len(matches) != 1:
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        alias = matches[0]
        return _digest(_encoded({"alias": alias, "record": value["archives"][alias["archive_id"]]}))
    except (ValidationError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
        raise StorageError("STORE_IDENTITY_CHANGED") from error


def reserved_task_ids(harness_root):
    """Return persistent reservations, including invisible aborted candidates."""
    root = Path(harness_root).absolute()
    index = load_history(root)
    for record in index["archives"].values():
        _validate_archive_task_document(root.parent, record)
    result = set(index["reserved_task_ids"])
    directory = root.parent / ".harness-store/history/reservations"
    if source_access.is_symlink(directory):
        raise StorageError("STORE_UNSAFE_NODE")
    if source_access.exists(directory):
        for path in source_access.members(directory, "*"):
            if not re.fullmatch("[0-9a-f]{32}\\.json", path.name):
                raise StorageError("STORE_IDENTITY_CHANGED")
            value = _document(path, root.parent)
            if (value["kind"] != "storage_reservation" or value["operation_id"] != path.stem
                    or value["workspace_id"] != index["workspace_id"] or value["store_id"] != index["store_id"]):
                raise StorageError("STORE_IDENTITY_CHANGED")
            result.update(value["task_ids"])
    return tuple(sorted(result))


@dataclass(frozen=True)
class ReferenceOrigin:
    workspace_id: str
    generation_id: str
    original_workspace_root: str


def validate_origin(value):
    try:
        origin = ReferenceOrigin(**value)
    except (TypeError, ValueError) as error:
        raise StorageError("STORE_REFERENCE_AMBIGUOUS") from error
    for identity in (origin.workspace_id, origin.generation_id):
        if not isinstance(identity, str) or not re.fullmatch("[0-9a-f]{32}", identity):
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    root = origin.original_workspace_root
    if not isinstance(root, str) or not Path(root).is_absolute() or ".." in Path(root).parts:
        raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    return origin


def impact_archive_declarations(impact, *, bound=False):
    from harness.impact import typed_contracts

    contracts = typed_contracts(impact)
    if bound:
        for item in contracts:
            ref = item["ref"]
            logical_history = (ref.startswith(("history/", ".harness/history/"))
                               or (Path(ref).is_absolute() and "/.harness/history/" in ref))
            if item["kind"] == "generic" and logical_history and "storage_origin" not in item:
                raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    return tuple(item for item in contracts if "storage_origin" in item)


def project_dependencies(session, declarations):
    result = {}
    for declaration in declarations:
        origin = validate_origin(declaration["storage_origin"])
        handle = resolve_archive(session, declaration["ref"], origin)
        token = handle.token
        key = "archive:" + token["selected_alias_record_digest"] + ":" + token["member_path"]
        reference = {"ref": declaration["ref"], "sha256": "sha256:" + token["member_content_digest"],
                     "storage": token}
        if key in result and result[key] != reference:
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        result[key] = reference
    return result


def dependency_paths(repo_root, references):
    """Finite member authority from current validated reference tokens only."""
    result = set()
    for reference in references.values():
        token = reference["storage"]
        archive_id = token["archive_id"]
        if not isinstance(archive_id, str) or not re.fullmatch("[0-9a-f]{32}", archive_id):
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        member = _relative_member(token["member_path"])
        obj = repo_root / ".harness-store/history/archives" / archive_id
        result.update((repo_root / ".harness-store/history/index.yaml", obj, obj / "archive.yaml", obj / member))
        result.update(obj / parent for parent in member.parents)
    return result


@dataclass(frozen=True)
class ArchiveHandle:
    session: object
    reference: str
    origin: ReferenceOrigin
    token: dict

    def read_bytes(self):
        try:
            content, token = _resolve(self.session, self.reference, self.origin)
            if token != self.token:
                raise StorageError("STORE_IDENTITY_CHANGED")
            return content
        except StorageError:
            raise
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
            raise StorageError("STORE_IDENTITY_CHANGED") from error

    @contextmanager
    def open(self):
        # Detached bytes, not a file-descriptor capability for the store tree.
        with io.BytesIO(self.read_bytes()) as stream:
            yield stream


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _relative_member(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise StorageError("STORE_UNSAFE_NODE")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or not path.parts:
        raise StorageError("STORE_UNSAFE_NODE")
    return path


def _logical(reference, origin):
    if not isinstance(reference, str) or "\\" in reference or "\x00" in reference:
        raise StorageError("STORE_UNSAFE_NODE")
    filename, separator, fragment = reference.partition("#")
    if Path(filename).is_absolute():
        prefix = origin.original_workspace_root.rstrip("/") + "/.harness/"
        if not filename.startswith(prefix):
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        filename = filename[len(prefix):]
    elif filename.startswith(".harness/"):
        filename = filename[len(".harness/"):]
    path = _relative_member(filename)
    if len(path.parts) < 3 or path.parts[0] != "history":
        raise StorageError("STORE_UNSAFE_NODE")
    if separator and not fragment:
        raise StorageError("STORE_UNSAFE_NODE")
    return path.parts[1], Path(*path.parts[2:]).as_posix(), fragment


def _resolve(session, reference, origin):
    _locked(session.harness_root)
    if not isinstance(origin, ReferenceOrigin):
        raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    origin_value = asdict(origin)
    for value in (origin.workspace_id, origin.generation_id):
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{32}", value):
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    if not isinstance(origin.original_workspace_root, str) or not Path(origin.original_workspace_root).is_absolute():
        raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    alias_name, member_name, fragment = _logical(reference, origin)
    selection = _encoded({"origin": origin_value, "logical_archive_alias": alias_name}).decode()
    index = load_history(session.harness_root, selection=selection)
    layout = require_layout_admission(session.harness_root)
    if layout != session.layout or origin.workspace_id != index["workspace_id"]:
        raise StorageError("STORE_IDENTITY_CHANGED")
    selected = [entry for entry in index["aliases"]
                if entry["origin"] == origin_value and entry["logical_archive_alias"] == alias_name]
    if len(selected) != 1:
        raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    alias = selected[0]
    record = index["archives"][alias["archive_id"]]
    return _read_member(session.repo_root, record, alias, member_name, fragment)


def _archive_descriptor(repo, record):
    obj = repo / ".harness-store/history/archives" / record["archive_id"]
    if _directory_identity(obj, repo) != record["object_identity"]:
        raise StorageError("STORE_IDENTITY_CHANGED")
    descriptor_path = obj / "archive.yaml"
    snapshot = source_access.read_regular_snapshot_beneath(descriptor_path, repo, max_bytes=_LIMIT)
    if ([snapshot.device, snapshot.inode] != record["descriptor_identity"]
            or _digest(snapshot.content) != record["descriptor_sha256"]):
        raise StorageError("STORE_IDENTITY_CHANGED")
    source_access._observe(descriptor_path, "node_identity", {
        "identity": [snapshot.device, snapshot.inode], "kind": "file"})
    descriptor = yaml.safe_load(snapshot.content)
    try:
        validate(descriptor, read_schema("storage-history.schema.json"))
    except (ValidationError, ValueError, TypeError) as error:
        raise StorageError("STORE_IDENTITY_CHANGED") from error
    if (descriptor["kind"] != "storage_archive" or descriptor["archive_id"] != record["archive_id"]
            or descriptor["task_id"] != record["task_id"] or descriptor["origin"] != record["origin"]
            or descriptor["source_snapshot"]["operation_id"] != record["receipt_id"]
            or descriptor["object_identity"] != record["object_identity"]
            or descriptor["parents"].get(".") != record["object_identity"]):
        raise StorageError("STORE_IDENTITY_CHANGED")
    for name in descriptor["members"]:
        _relative_member(name)
    for name in descriptor["parents"]:
        if name != ".":
            _relative_member(name)
    return obj, descriptor


def _read_member(repo, record, alias, member_name, fragment):
    origin_value = record["origin"]
    alias_name = alias["logical_archive_alias"]
    obj, descriptor = _archive_descriptor(repo, record)
    member = descriptor["members"].get(member_name)
    if member is None:
        raise StorageError("STORE_IDENTITY_CHANGED")
    relative = _relative_member(member_name)
    for ancestor in reversed(relative.parents):
        if ancestor == Path("."):
            continue
        if _directory_identity(obj / ancestor, repo) != descriptor["parents"].get(ancestor.as_posix()):
            raise StorageError("STORE_IDENTITY_CHANGED")
    payload = source_access.read_regular_snapshot_beneath(obj / relative, repo, max_bytes=_LIMIT)
    source_access._observe(obj / relative, "node_identity", {
        "identity": [payload.device, payload.inode], "kind": "file"})
    digest = _digest(payload.content)
    if ([payload.device, payload.inode] != member["identity"] or digest != member["sha256"]
            or len(payload.content) != member["size"]):
        raise StorageError("STORE_IDENTITY_CHANGED")
    if fragment.startswith("sha256:") and fragment != "sha256:" + digest:
        raise StorageError("STORE_IDENTITY_CHANGED")
    token = {"version": 1, "origin": origin_value, "logical_archive_alias": alias_name,
             "selected_alias_record_digest": _digest(_encoded({"alias": alias, "record": record})),
             "archive_id": record["archive_id"], "archive_descriptor_digest": record["descriptor_sha256"],
             "member_path": member_name, "member_identity": [payload.device, payload.inode],
             "member_content_digest": digest}
    return payload.content, token


def render_archive_descriptor(action, objects, operation_id):
    """Deterministic metadata from already acknowledged directory/file objects."""
    blueprint = json.loads(base64.b64decode(action["content"], validate=True))
    if set(blueprint) != {"archive_id", "task_id", "origin", "source_snapshot", "members"}:
        raise StorageError("STORE_IDENTITY_CHANGED")
    obj = Path(action["target"]).parent
    if (obj.as_posix() != ".harness-store/history/archives/" + blueprint["archive_id"]
            or Path(action["target"]).name != "archive.yaml"
            or blueprint["source_snapshot"]["operation_id"] != operation_id):
        raise StorageError("STORE_IDENTITY_CHANGED")
    owned = objects.get(obj.as_posix())
    if owned is None or owned["kind"] != "directory":
        raise StorageError("STORE_IDENTITY_CHANGED")
    parents = {".": owned["identity"]}
    members = {}
    names = blueprint["members"]
    if not isinstance(names, list) or not names or len(set(names)) != len(names):
        raise StorageError("STORE_IDENTITY_CHANGED")
    for name in names:
        member = _relative_member(name)
        if member.as_posix() == "archive.yaml":
            raise StorageError("STORE_IDENTITY_CHANGED")
        node = objects.get((obj / member).as_posix())
        if node is None or node["kind"] != "file" or "size" not in node:
            raise StorageError("STORE_IDENTITY_CHANGED")
        members[name] = {"identity": node["identity"], "sha256": node["sha256"], "size": node["size"]}
        for parent in member.parents:
            if parent == Path("."):
                continue
            ancestor = objects.get((obj / parent).as_posix())
            if ancestor is None or ancestor["kind"] != "directory":
                raise StorageError("STORE_IDENTITY_CHANGED")
            parents[parent.as_posix()] = ancestor["identity"]
    descriptor = {"version": 1, "kind": "storage_archive", "archive_id": blueprint["archive_id"],
                  "task_id": blueprint["task_id"], "origin": blueprint["origin"],
                  "object_identity": owned["identity"], "source_snapshot": blueprint["source_snapshot"],
                  "parents": parents, "members": members}
    validate(descriptor, read_schema("storage-history.schema.json"))
    return _encoded(descriptor)


def render_history_overlay(action, objects, operation_id, actions):
    value = json.loads(base64.b64decode(action["content"], validate=True))
    if set(value) != {"base", "base_sha256", "archives", "reserve_ids"}:
        raise StorageError("STORE_IDENTITY_CHANGED")
    base = _validate_index(deepcopy(value["base"]))
    source = objects.get(".harness-store/history/index.yaml")
    if source is None or source["sha256"] != value["base_sha256"]:
        raise StorageError("STORE_PLAN_STALE")
    reservations = set()
    for entry in actions:
        if entry["kind"] != "reserve_ids":
            continue
        raw = base64.b64decode(entry["content"], validate=True)
        validate_reservation(raw, entry, {"operation_id": operation_id, "workspace_id": base["workspace_id"],
                                          "store_id": base["store_id"]})
        node = objects.get(entry["target"])
        if node is None or node["sha256"] != _digest(raw):
            raise StorageError("STORE_IDENTITY_CHANGED")
        reservations.update(json.loads(raw)["task_ids"])
    if not set(value["reserve_ids"]).issubset(reservations):
        raise StorageError("STORE_IDENTITY_CHANGED")
    for addition in value["archives"]:
        if set(addition) != {"path", "aliases"}:
            raise StorageError("STORE_IDENTITY_CHANGED")
        obj = _relative_member(addition["path"])
        descriptor_name = (obj / "archive.yaml").as_posix()
        candidates = [item for item in actions if item["kind"] == "archive_descriptor"
                      and item["target"] == descriptor_name]
        if len(candidates) != 1:
            raise StorageError("STORE_IDENTITY_CHANGED")
        content = render_archive_descriptor(candidates[0], objects, operation_id)
        descriptor = json.loads(content)
        observed = objects.get(descriptor_name)
        if observed is None or observed["sha256"] != _digest(content):
            raise StorageError("STORE_IDENTITY_CHANGED")
        archive_id = descriptor["archive_id"]
        if archive_id in base["archives"]:
            raise StorageError("STORE_REFERENCE_AMBIGUOUS")
        base["archives"][archive_id] = {
            "archive_id": archive_id, "task_id": descriptor["task_id"], "origin": descriptor["origin"],
            "object_identity": descriptor["object_identity"], "descriptor_identity": observed["identity"],
            "descriptor_sha256": observed["sha256"], "receipt_id": operation_id}
        for alias in addition["aliases"]:
            base["aliases"].append({"origin": descriptor["origin"], "logical_archive_alias": alias,
                                    "archive_id": archive_id})
    base["reserved_task_ids"] = sorted(set(base["reserved_task_ids"]) | set(value["reserve_ids"]))
    return _encoded(_validate_index(base))


def _validate_archive_task_document(repo, record):
    alias = {"origin": record["origin"], "logical_archive_alias": record["archive_id"],
             "archive_id": record["archive_id"]}
    try:
        content, _ = _read_member(repo, record, alias, "current-task.yaml", "")
        value = yaml.safe_load(content)
        task = value.get("task") if isinstance(value, dict) else None
        if not isinstance(task, dict) or task.get("id") != record["task_id"]:
            raise StorageError("STORE_IDENTITY_CHANGED")
    except StorageError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
        raise StorageError("STORE_IDENTITY_CHANGED") from error


def validate_history_overlay_payload(raw, repo, blueprint):
    value = json.loads(base64.b64decode(blueprint, validate=True))
    snapshot = source_access.read_regular_snapshot_beneath(
        repo / '.harness-store/history/index.yaml', repo, max_bytes=_LIMIT)
    if (_digest(snapshot.content) != value["base_sha256"]
            or yaml.safe_load(snapshot.content) != value["base"]):
        raise StorageError("STORE_PLAN_STALE")
    index = _validate_index(json.loads(raw))
    for record in index["archives"].values():
        _validate_archive_task_document(repo, record)


def validate_reservation(raw, action, plan):
    value = json.loads(raw)
    validate(value, read_schema("storage-history.schema.json"))
    if (value["kind"] != "storage_reservation" or value["operation_id"] != plan["operation_id"]
            or value["workspace_id"] != plan["workspace_id"] or value["store_id"] != plan["store_id"]
            or action["target"] != f'.harness-store/history/reservations/{plan["operation_id"]}.json'):
        raise StorageError("STORE_IDENTITY_CHANGED")


def find_receipted_snapshot(session, source_snapshot):
    """Reuse only exact origin/object/member bytes with original commit proof."""
    from contextlib import ExitStack
    from .journal import DirectoryOperation

    if not isinstance(source_snapshot, dict) or set(source_snapshot) != {
            "task_id", "origin", "source_identity", "manifest_digest"}:
        raise StorageError("STORE_IDENTITY_CHANGED")
    validate_origin(source_snapshot["origin"])
    index = load_history(session.harness_root)
    matches = []
    for record in index["archives"].values():
        if (record["task_id"] != source_snapshot["task_id"]
                or record["origin"] != source_snapshot["origin"]):
            continue
        _, descriptor = _archive_descriptor(session.repo_root, record)
        snapshot = descriptor["source_snapshot"]
        if (snapshot["source_identity"] != source_snapshot["source_identity"]
                or snapshot["manifest_digest"] != source_snapshot["manifest_digest"]):
            continue
        try:
            with ExitStack() as resources:
                _, _, _, receipt, _, state, _ = DirectoryOperation(
                    session.repo_root, record["receipt_id"])._load(resources)
                if state.phase != "COMMITTED":
                    continue
                acknowledged = [item for item in receipt["plan"]["actions"]
                                if item["kind"] == "archive_descriptor"
                                and item["target"] == f'.harness-store/history/archives/{record["archive_id"]}/archive.yaml']
                if len(acknowledged) != 1:
                    continue
                blueprint = json.loads(base64.b64decode(acknowledged[0]["content"], validate=True))
                if blueprint["source_snapshot"] != snapshot:
                    continue
        except (OSError, ValueError, TypeError, KeyError):
            continue  # Preserve another snapshot, never infer a missing receipt.
        alias = {"origin": record["origin"], "logical_archive_alias": record["archive_id"],
                 "archive_id": record["archive_id"]}
        for member in descriptor["members"]:
            _read_member(session.repo_root, record, alias, member, "")
        matches.append(record["archive_id"])
    if len(matches) > 1:
        raise StorageError("STORE_REFERENCE_AMBIGUOUS")
    return matches[0] if matches else None


def resolve_relocated_object(session, operation_id, logical_path, origin):
    """Exact M2 object location, not a capability to read nested fixture paths."""
    from .journal import DirectoryOperation, _parent, _relative, _resources
    import os

    _locked(session.harness_root)
    if not isinstance(origin, ReferenceOrigin):
        raise StorageError('STORE_REFERENCE_AMBIGUOUS')
    origin_value = asdict(validate_origin(asdict(origin)))
    layout = require_layout_admission(session.harness_root)
    if layout != session.layout or layout.mode != 'bound':
        raise StorageError('STORE_IDENTITY_CHANGED')
    if not isinstance(logical_path, str):
        raise StorageError('STORE_REFERENCE_AMBIGUOUS')
    original = Path(logical_path)
    if original.is_absolute():
        try:
            logical_path = original.relative_to(origin.original_workspace_root).as_posix()
        except ValueError as error:
            raise StorageError('STORE_REFERENCE_AMBIGUOUS') from error
    _relative(logical_path)
    with _resources() as resources:
        root, path, _, document, _, state, _ = DirectoryOperation(session.repo_root, operation_id)._load(resources)
        plan = document['plan']
        if (path.name != 'descriptor.json' or state.phase != 'COMMITTED' or plan['operation'] != 'M2'
                or plan['workspace_id'] != layout.identity['header']['workspace_id']
                or plan['store_id'] != layout.identity['header']['store_id']):
            raise StorageError('STORE_IDENTITY_CHANGED')
        matches = [item for item in plan.get('relocations', [])
                   if item['origin'] == origin_value and item['logical_path'] == logical_path]
        if len(matches) != 1:
            raise StorageError('STORE_REFERENCE_AMBIGUOUS')
        item = matches[0]
        expected = state.objects.get(item['target'])
        if expected is None or expected['kind'] != 'directory':
            raise StorageError('STORE_IDENTITY_CHANGED')
        target = _relative(item['target'])
        parent = _parent(root, target.parent, state.directories)
        try:
            from .journal import _node
            if _node(parent, target.name) != expected:
                raise StorageError('STORE_IDENTITY_CHANGED')
        finally:
            os.close(parent)
        return {'operation_id': operation_id, 'origin': deepcopy(origin_value), 'logical_path': logical_path,
                'path': item['target'], 'identity': list(expected['identity']), 'role': item['role'],
                'descriptor_digest': _digest(_encoded(document))}


def resolve_archive(session, reference, origin):
    try:
        _, token = _resolve(session, reference, origin)
        return ArchiveHandle(session, reference, origin, token)
    except StorageError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
        raise StorageError("STORE_IDENTITY_CHANGED") from error
