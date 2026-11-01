"""Directory-only lifecycle authority, separate from regular-file journals.

Private callers hold the canonical owner and supply an already authorized plan.
Recovery never creates a missing payload or adopts an unacknowledged creation.
All displaced/aborted objects remain; no unlink or copy fallback exists here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from jsonschema import ValidationError, validate

from harness import publication_fs as fs
from harness.publication_journal import _write_new
from harness.schema_resources import read_schema
from harness.telemetry_lock import telemetry_lock
from harness.transaction_recovery import _locked, _pending_paths
from .layout import StorageError, require_layout_admission

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_LIMIT = 4 * 1024 * 1024


def _blocked():
    return StorageError("STORE_IDENTITY_CHANGED")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _id(info):
    return [info.st_dev, info.st_ino]


def _validate(document):
    try:
        validate(document, read_schema("storage-operation.schema.json"))
    except (ValidationError, ValueError, TypeError, RecursionError) as error:
        raise _blocked() from error


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _blocked()
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise _blocked()
    return path


@contextmanager
def _resources():
    """Attempt every close, retaining original refusal/cancellation as primary."""
    stack = ExitStack()
    try:
        yield stack
    except BaseException:
        try:
            stack.close()
        except OSError:
            try:
                print("STORE_CLEANUP_PARTIAL: cleanup during existing failure", file=sys.stderr)
            except OSError:
                pass
        raise
    else:
        try:
            stack.close()
        except OSError as error:
            raise StorageError("STORE_CLEANUP_PARTIAL") from error


def _fd(stack, value):
    stack.callback(os.close, value)
    return value


def _read(parent, name):
    opened = os.open(name, _READ, dir_fd=parent)
    try:
        before = os.fstat(opened)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _LIMIT:
            raise _blocked()
        chunks, size = [], 0
        while chunk := os.read(opened, min(65536, _LIMIT + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
            if size > _LIMIT:
                raise _blocked()
        after = os.fstat(opened)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        def token(info):
            return (_id(info), info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

        if token(before) != token(after) or token(after) != token(named):
            raise _blocked()
        return b"".join(chunks)
    finally:
        os.close(opened)


def _document(parent, name):
    raw = _read(parent, name)
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != _encoded(value):
        raise _blocked()
    _validate(value)
    return value


def _node(parent, name):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(info.st_mode):
        opened = os.open(name, _DIR, dir_fd=parent)
        try:
            if _id(os.fstat(opened)) != _id(info):
                raise _blocked()
        finally:
            os.close(opened)
        return {"identity": _id(info), "kind": "directory", "sha256": None}
    if stat.S_ISREG(info.st_mode):
        raw = _read(parent, name)
        if _id(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _id(info):
            raise _blocked()
        return {"identity": _id(info), "kind": "file", "sha256": _digest(raw), "size": len(raw)}
    raise StorageError("STORE_UNSAFE_NODE")


def _parent(root, relative, directories):
    """Pin/check every ancestor; never follow a path supplied by a descriptor."""
    opened = os.dup(root)
    current = Path(".")
    try:
        if _id(os.fstat(opened)) != directories.get("."):
            raise _blocked()
        for part in relative.parts:
            current /= part
            child = os.open(part, _DIR, dir_fd=opened)
            os.close(opened)
            opened = child
            info = os.fstat(opened)
            if (_id(info) != directories.get(current.as_posix())
                    or info.st_dev != os.fstat(root).st_dev):
                raise _blocked()
        return opened
    except BaseException:
        os.close(opened)
        raise


def _capture(root, relative, directories):
    """Capture existing ancestors only; missing ones require prior owned mkdir."""
    opened = os.dup(root)
    current = Path(".")
    try:
        for part in relative.parts:
            current /= part
            try:
                child = os.open(part, _DIR, dir_fd=opened)
            except FileNotFoundError:
                break
            os.close(opened)
            opened = child
            info = os.fstat(opened)
            if info.st_dev != os.fstat(root).st_dev:
                raise StorageError("STORE_UNSAFE_NODE")
            key = current.as_posix()
            if key in directories and directories[key] != _id(info):
                raise _blocked()
            directories[key] = _id(info)
    finally:
        os.close(opened)


def _move_map(mapping, source, target):
    result = dict(mapping)
    for name, value in mapping.items():
        path = Path(name)
        if path == source or path.is_relative_to(source):
            result.pop(name)
            result[(target / path.relative_to(source)).as_posix()] = value
    return result


@dataclass
class _State:
    phase: str
    sequence: int
    previous_hash: str
    acknowledged: list
    intent: int | None
    undo_intent: int | None
    directories: dict
    objects: dict


def _transition(document, state, frame):
    event, index, node = frame["event"], frame["action"], frame["node"]
    actions = document["plan"]["actions"]
    if (frame["operation_id"] != document["id"]
            or frame["sequence"] != state.sequence + 1
            or frame["previous_hash"] != state.previous_hash):
        raise _blocked()
    if event == "INTENT":
        if (state.phase not in {"PREPARED", "APPLYING"} or state.intent is not None
                or index != len(state.acknowledged) or index >= len(actions) or node is not None):
            raise _blocked()
        state.intent, state.phase = index, "APPLYING"
    elif event in {"ACK", "CANCEL"}:
        if state.intent != index or state.phase != "APPLYING":
            raise _blocked()
        if event == "ACK":
            if node is None:
                raise _blocked()
            entry = actions[index]
            if entry["kind"] == "move":
                expected = state.objects.get(entry["source"])
                if node != expected:
                    raise _blocked()
                state.directories = _move_map(state.directories, Path(entry["source"]), Path(entry["target"]))
                state.objects = _move_map(state.objects, Path(entry["source"]), Path(entry["target"]))
            else:
                if node["kind"] != ("directory" if entry["kind"] == "mkdir" else "file"):
                    raise _blocked()
                if entry['kind'] == 'copy':
                    original = state.objects.get(entry['source'])
                    if (original is None or node['sha256'] != original['sha256']
                            or node.get('size') != original.get('size') or node['identity'] == original['identity']):
                        raise _blocked()
                elif entry["kind"] != "mkdir" and node["sha256"] != _digest(_payload(document, state, entry)):
                    raise _blocked()
                state.objects[entry["target"]] = node
                if node["kind"] == "directory":
                    state.directories[entry["target"]] = node["identity"]
            state.acknowledged.append(index)
        elif node is not None:
            raise _blocked()
        state.intent = None
    elif event == "COMMIT_INTENT":
        if (state.phase not in {"PREPARED", "APPLYING"} or state.intent is not None
                or len(state.acknowledged) != len(actions) or index is not None or node is not None):
            raise _blocked()
        state.phase = "VALIDATED"
    elif event == "COMMITTED":
        if state.phase != "VALIDATED" or index is not None or node is not None:
            raise _blocked()
        state.phase = "COMMITTED"
    elif event == "ABORT_INTENT":
        if state.phase not in {"PREPARED", "APPLYING", "VALIDATED"} or state.intent is not None or index is not None or node is not None:
            raise _blocked()
        state.phase = "ABORTING"
    elif event == "UNDO_INTENT":
        if (state.phase != "ABORTING" or state.undo_intent is not None
                or not state.acknowledged or state.acknowledged[-1] != index or node is not None):
            raise _blocked()
        state.undo_intent = index
    elif event == "UNDONE":
        if state.phase != "ABORTING" or state.undo_intent != index or node is not None:
            raise _blocked()
        entry = actions[index]
        target = (Path(entry["source"]) if entry["kind"] == "move"
                  else Path(document["frames_path"]) / "quarantine" / f"object-{index}")
        if entry["kind"] != "reserve_ids":
            state.directories = _move_map(state.directories, Path(entry["target"]), target)
            state.objects = _move_map(state.objects, Path(entry["target"]), target)
        state.acknowledged.pop()
        state.undo_intent = None
    elif event == "ABORTED":
        if state.phase != "ABORTING" or state.acknowledged or state.undo_intent is not None or index is not None or node is not None:
            raise _blocked()
        state.phase = "ABORTED"
    else:
        raise _blocked()
    state.sequence = frame["sequence"]
    state.previous_hash = _digest(_encoded(frame))


def _plan_paths(plan):
    operation_id = plan["operation_id"]
    private = ".harness-store-prepare-" + operation_id
    protected = (Path(".harness/.transactions"), Path(".harness/.publication-retained"),
                 Path(".harness-store/operations"), Path(".harness-store/receipts"))
    for action in plan["actions"]:
        for value in (action["source"], action["target"]):
            if value is None:
                continue
            path = _relative(value)
            if path.parts[0] not in {".harness", ".harness-store", private}:
                raise StorageError("STORE_UNSAFE_NODE")
            if any(path == item or path.is_relative_to(item) for item in protected):
                selected_source = (plan['operation'] == 'M2' and value == action['source']
                                   and any(item['source'] == value for item in plan.get('relocations', []))
                                   and path.is_relative_to(Path('.harness/.publication-retained'))
                                   and path != Path('.harness/.publication-retained'))
                if not selected_source:
                    raise StorageError("STORE_UNSAFE_NODE")
            if plan["operation"] == "ACTIVATE" and path == Path(".harness"):
                raise StorageError("STORE_UNSAFE_NODE")
            if plan["operation"] != "ACTIVATE" and path.parts[0] == private:
                raise StorageError("STORE_UNSAFE_NODE")
            if plan["operation"] != "ACTIVATE" and path == Path(".harness-store"):
                raise StorageError("STORE_UNSAFE_NODE")
        if action["kind"] in {"move", "copy"}:
            if (action["source"] is None or action["content"] is not None
                    or Path(action["target"]).is_relative_to(Path(action["source"]))):
                raise _blocked()
        elif action["source"] is not None or action["identity"] is not None or action["sha256"] is not None:
            raise _blocked()
        if action["kind"] == "mkdir" and action["content"] is not None:
            raise _blocked()
        if action["kind"] not in {"move", "copy", "mkdir"}:
            if action["content"] is None:
                raise _blocked()
            base64.b64decode(action["content"], validate=True)


def _payload(document, state, action):
    from .archive import render_archive_descriptor, render_history_overlay, validate_reservation

    try:
        if action['kind'] == 'candidate_binding':
            from .turnover import render_candidate_binding

            return render_candidate_binding(document, state, action)
        if action["kind"] == "layout_metadata":
            from .migration import render_layout_metadata

            return render_layout_metadata(document, state, action)
        if action["kind"] == "archive_descriptor":
            return render_archive_descriptor(action, state.objects, document["id"])
        if action["kind"] == "history_overlay":
            return render_history_overlay(action, state.objects, document["id"], document["plan"]["actions"])
        raw = base64.b64decode(action["content"], validate=True)
        if action["kind"] == "reserve_ids":
            validate_reservation(raw, action, document["plan"])
        return raw
    except (ValidationError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise _blocked() from error


def _check_plan(repo, plan, authority):
    _validate(plan)
    _validate(authority)
    _plan_paths(plan)
    maintenance = authority.get('maintenance_snapshot')
    if maintenance is not None:
        if (authority['maintenance_digest'] != _digest(_encoded(maintenance))
                or maintenance['plan_digest'] != 'sha256:' + plan['plan_digest']
                or maintenance['workspace_id'] != plan['workspace_id']
                or maintenance['operation'] != plan['operation']):
            raise StorageError('STORE_AUTHORITY_REQUIRED')
    if (any(entry["kind"] == "archive_descriptor" for entry in plan["actions"])
            and plan["actions"][0]["kind"] != "reserve_ids"):
        raise StorageError("STORE_PLAN_STALE")
    if (not plan["ready"] or plan["workspace_root"] != str(repo)
            or plan["plan_digest"] != _digest(_encoded({k: v for k, v in plan.items() if k != "plan_digest"}))
            or authority["plan_digest"] != plan["plan_digest"]):
        raise StorageError("STORE_PLAN_STALE")


def _prepare(root, plan, authority):
    root = Path(root).absolute()
    _locked(root)
    _check_plan(root.parent, plan, authority)
    if _pending_paths(root):
        raise StorageError("STORE_RECOVERY_REQUIRED")
    layout = require_layout_admission(root)
    activation = plan["operation"] == "ACTIVATE"
    if layout.mode != ("legacy" if activation else "bound"):
        raise StorageError("STORE_PLAN_STALE")
    if not activation:
        header, binding = layout.identity["header"], layout.identity["binding"]
        if (plan["workspace_id"] != header["workspace_id"] or plan["store_id"] != header["store_id"]
                or plan["old_generation_id"] != binding["generation_id"]):
            raise StorageError("STORE_PLAN_STALE")
    fs._native()  # Unsupported ABI must fail before any metadata creation.
    with _resources() as stack:
        repo = _fd(stack, fs.open_directory(root.parent))
        directories = {".": _id(os.fstat(repo))}
        _capture(repo, Path(".harness"), directories)
        active = Path(".harness/.transactions" if activation else ".harness-store/operations")
        retained = Path(".harness/.publication-retained" if activation else ".harness-store/receipts")
        for path in (active, retained):
            _capture(repo, path.parent, directories)
            parent = _fd(stack, _parent(repo, path.parent, directories))
            try:
                os.mkdir(path.name, 0o700, dir_fd=parent)
                fs.sync_directory(parent)
            except FileExistsError:
                pass
            _capture(repo, path, directories)
        active_fd = _fd(stack, _parent(repo, active, directories))
        if os.listdir(active_fd):
            raise StorageError("STORE_RECOVERY_REQUIRED")
        sources = {}
        qualification = plan.get('qualification', {})
        facts = dict(qualification.get('entries', {}))
        for name, fact in qualification.get('sources', {}).items():
            if name == 'store.yaml':
                facts['.harness-store/store.yaml'] = fact
            elif name in {'current-task.yaml', 'gate.yaml', 'storage-binding.yaml'}:
                facts['.harness/' + name] = fact
            else:
                raise _blocked()
        authority_sources = authority.get('sources', {})
        if authority_sources:
            if set(authority_sources) != {f'decisions/{authority["decision_id"]}.yaml', 'decisions/index.yaml'}:
                raise _blocked()
            facts.update({'.harness/' + name: fact for name, fact in authority_sources.items()})
        for name, fact in facts.items():
            path = _relative(name)
            turnover_source = (plan['operation'] == 'TURNOVER' and path.parts[0] == '.harness'
                               and len(path.parts) > 1 and path.parts[1] not in {
                                   '.transactions', '.publication-retained', '.staging', 'history'})
            relocation_source = (plan['operation'] == 'M2' and any(
                name == item['source'] or (item['role'] == 'history' and path.is_relative_to(Path(item['source'])))
                for item in plan.get('relocations', [])))
            if not (relocation_source or turnover_source or path.is_relative_to(Path('.harness/history')) or name in {
                    '.harness/current-task.yaml', '.harness/gate.yaml',
                    '.harness/storage-binding.yaml', '.harness-store/store.yaml',
                    f'.harness/decisions/{authority["decision_id"]}.yaml', '.harness/decisions/index.yaml'}):
                raise _blocked()
            _capture(repo, path.parent, directories)
            parent = _parent(repo, path.parent, directories)
            try:
                node = _node(parent, path.name)
            finally:
                os.close(parent)
            if (node is None or node['identity'] != fact['identity']
                    or node['sha256'] != fact.get('sha256')
                    or ('kind' in fact and node['kind'] != fact['kind'])):
                raise StorageError('STORE_PLAN_STALE')
            sources[name] = node
            if node['kind'] == 'directory':
                directories[name] = node['identity']
        for entry in plan["actions"]:
            for value in (entry["target"], entry["source"]):
                if value is not None:
                    _capture(repo, _relative(value).parent, directories)
            if entry["identity"] is not None:
                source = _relative(entry["source"])
                parent = _parent(repo, source.parent, directories)
                try:
                    node = _node(parent, source.name)
                finally:
                    os.close(parent)
                if node is None or node["identity"] != entry["identity"] or node["sha256"] != entry["sha256"]:
                    raise StorageError("STORE_PLAN_STALE")
                sources[entry["source"]] = node
                if node["kind"] == "directory":
                    directories[entry["source"]] = node["identity"]
        retained_fd = _fd(stack, _parent(repo, retained, directories))
        frames_path = retained / ("storage-" + plan["operation_id"])
        os.mkdir(frames_path.name, 0o700, dir_fd=retained_fd)
        fs.sync_directory(retained_fd)
        _capture(repo, frames_path, directories)
        frames_fd = _fd(stack, _parent(repo, frames_path, directories))
        os.mkdir("quarantine", 0o700, dir_fd=frames_fd)
        fs.sync_directory(frames_fd)
        _capture(repo, frames_path / "quarantine", directories)
        document = {"version": 3, "kind": "storage_activation" if activation else "storage_directory",
                    "id": plan["operation_id"], "workspace_root": str(root.parent),
                    "repo_identity": directories["."], "root_identity": directories[".harness"],
                    "store_identity": None if activation else directories[".harness-store"],
                    "frames_path": frames_path.as_posix(), "frames_identity": _id(os.fstat(frames_fd)),
                    "active_parent_identity": _id(os.fstat(active_fd)), "parents": directories,
                    "sources": sources, "plan": plan, "authority": authority}
        _validate(document)
        if len(_encoded(document)) > _LIMIT:
            raise StorageError('STORE_PLAN_STALE')
        active_name = ('storage-activation-' if activation else '') + plan['operation_id'] + '.json'
        _write_new(active_fd, active_name, document)
    return DirectoryOperation(root.parent, plan["operation_id"])


def prepare_activation(harness_root, plan, authority):
    if plan.get("operation") != "ACTIVATE":
        raise StorageError("STORE_PLAN_STALE")
    return _prepare(harness_root, plan, authority)


def prepare_turnover(session, descriptor):
    plan = descriptor["plan"]
    if plan.get("operation") not in {"TURNOVER", "M1", "M2"}:
        raise StorageError("STORE_PLAN_STALE")
    return _prepare(session.harness_root, plan, descriptor["authority"])


@dataclass(frozen=True)
class DirectoryOperation:
    repo_root: Path
    operation_id: str

    def _load(self, stack):
        _locked(self.repo_root / ".harness")
        if not re.fullmatch("[0-9a-f]{32}", self.operation_id):
            raise _blocked()
        root = _fd(stack, fs.open_directory(self.repo_root))
        candidates = [Path('.harness/.transactions') / ('storage-activation-' + self.operation_id + '.json'),
                      Path(".harness/.transactions") / (self.operation_id + ".json"),
                      Path(".harness-store/operations") / (self.operation_id + ".json"),
                      Path(".harness-store/receipts") / ("storage-" + self.operation_id) / "descriptor.json",
                      Path(".harness/.publication-retained") / ("storage-" + self.operation_id) / "descriptor.json"]
        found = []
        for path in candidates:
            try:
                parent = fs.open_directory(self.repo_root / path.parent)
            except FileNotFoundError:
                continue
            _fd(stack, parent)
            try:
                document = _document(parent, path.name)
            except FileNotFoundError:
                continue
            found.append((path, parent, document))
        if len(found) != 1:
            raise StorageError("STORE_RECOVERY_REQUIRED")
        path, active_fd, document = found[0]
        if (document["version"] != 3 or document["kind"] not in {"storage_activation", "storage_directory"}
                or document["id"] != self.operation_id or document["workspace_root"] != str(self.repo_root)
                or document["repo_identity"] != _id(os.fstat(root))):
            raise _blocked()
        _check_plan(self.repo_root, document["plan"], document["authority"])
        activation = document["kind"] == "storage_activation"
        if (document["plan"]["operation_id"] != self.operation_id
                or activation != (document["plan"]["operation"] == "ACTIVATE")):
            raise _blocked()
        expected = (Path('.harness/.transactions') / ('storage-activation-' + self.operation_id + '.json')
                    if activation else Path('.harness-store/operations') / (self.operation_id + '.json'))
        legacy_bootstrap = Path('.harness/.transactions') / (self.operation_id + '.json')
        if path == expected or (activation and path == legacy_bootstrap):
            if _id(os.fstat(active_fd)) != document["active_parent_identity"] or os.listdir(active_fd) != [path.name]:
                raise _blocked()
        elif path.name != "descriptor.json":
            raise _blocked()
        # Nonactivation can never coexist with a current ordinary transaction.
        if not activation and _pending_paths(self.repo_root / ".harness"):
            raise StorageError("STORE_RECOVERY_REQUIRED")
        original = _relative(document["frames_path"])
        retired = Path(".harness-store/receipts") / ("storage-" + self.operation_id)
        frame_candidates = list(dict.fromkeys([original, retired]))
        frames = []
        for frame_path in frame_candidates:
            try:
                opened = _fd(stack, fs.open_directory(self.repo_root / frame_path))
            except FileNotFoundError:
                continue
            if _id(os.fstat(opened)) != document["frames_identity"]:
                raise _blocked()
            frames.append((frame_path, opened))
        if len(frames) != 1:
            raise _blocked()
        frame_path, frames_fd = frames[0]
        state = _State("PREPARED", 0, _digest(_encoded(document)), [], None, None,
                       dict(document["parents"]), dict(document["sources"]))
        names = os.listdir(frames_fd)
        journal = sorted(name for name in names if re.fullmatch(r"[0-9]{8}\.json", name))
        if len(journal) > 8192 or set(names) - set(journal) - {"quarantine", "descriptor.json"}:
            raise _blocked()
        for index, name in enumerate(journal, 1):
            if name != f"{index:08}.json":
                raise _blocked()
            frame = _document(frames_fd, name)
            _transition(document, state, frame)
        if frame_path != original:
            if state.phase != "COMMITTED":
                raise _blocked()
            state.directories = _move_map(state.directories, original, frame_path)
        checked = _fd(stack, _parent(root, frame_path, state.directories))
        if _id(os.fstat(checked)) != document["frames_identity"]:
            raise _blocked()
        return root, path, active_fd, document, frames_fd, state, frame_path

    def _append(self, document, frames_fd, state, event, index=None, node=None):
        frame = {"version": 1, "kind": "storage_frame", "operation_id": self.operation_id,
                 "sequence": state.sequence + 1, "previous_hash": state.previous_hash,
                 "event": event, "action": index, "node": node}
        _validate(frame)
        # Replay validates legal transition before publishing immutable new frame.
        _transition(document, state, frame)
        _write_new(frames_fd, f"{state.sequence:08}.json", frame)

    def advance(self, action):
        with _resources() as stack:
            root, _, _, document, frames, state, _ = self._load(stack)
            index = len(state.acknowledged)
            if (state.phase not in {"PREPARED", "APPLYING"} or state.intent is not None
                    or index >= len(document["plan"]["actions"]) or action != document["plan"]["actions"][index]):
                raise _blocked()
            target = _relative(action["target"])
            target_fd = _fd(stack, _parent(root, target.parent, state.directories))
            if _node(target_fd, target.name) is not None:
                raise _blocked()
            source_fd, expected = None, None
            if action["kind"] in {'move', 'copy'}:
                source = _relative(action["source"])
                source_fd = _fd(stack, _parent(root, source.parent, state.directories))
                expected = state.objects.get(action["source"])
                if expected is None or _node(source_fd, source.name) != expected:
                    raise _blocked()
            raw = None
            if action['kind'] == 'copy':
                if expected['kind'] != 'file' or expected['sha256'] != action['sha256']:
                    raise _blocked()
                raw = _read(source_fd, source.name)
                if _digest(raw) != expected['sha256']:
                    raise _blocked()
            elif action["kind"] not in {"move", "mkdir"}:
                raw = _payload(document, state, action)
                if action["kind"] == "history_overlay":
                    from .archive import validate_history_overlay_payload

                    validate_history_overlay_payload(raw, self.repo_root, action["content"])
            self._append(document, frames, state, "INTENT", index)
            if action["kind"] == "move":
                fs.move_noreplace(source_fd, source.name, target_fd, target.name)
                fs.sync_directory(source_fd)
            elif action["kind"] == "mkdir":
                os.mkdir(target.name, 0o700, dir_fd=target_fd)
            else:
                opened = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=target_fd)
                with os.fdopen(opened, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            fs.sync_directory(target_fd)
            node = _node(target_fd, target.name)
            if node is None or (action['kind'] == 'move' and node != expected):
                raise _blocked()
            self._append(document, frames, state, "ACK", index, node)
            return {"status": "APPLYING", "action": index, "identity": node["identity"]}

    def _check_objects(self, root, state):
        for path, expected in state.objects.items():
            with _resources() as stack:
                relative = _relative(path)
                parent = _fd(stack, _parent(root, relative.parent, state.directories))
                if _node(parent, relative.name) != expected:
                    raise _blocked()

    def commit(self):
        with _resources() as stack:
            root, path, active, document, frames, state, frame_path = self._load(stack)
            self._check_objects(root, state)
            if state.phase not in {"COMMITTED", "ABORTED"}:
                self._append(document, frames, state, "COMMIT_INTENT")
                self._append(document, frames, state, "COMMITTED")
            if state.phase != "COMMITTED":
                raise _blocked()
            return self._retire(stack, root, path, active, document, frames, state, frame_path)

    def abort(self):
        with _resources() as stack:
            root, path, active, document, frames, state, frame_path = self._load(stack)
            if state.phase == "COMMITTED":
                raise _blocked()
            actions = document["plan"]["actions"]
            if (state.phase == "PREPARED" and state.intent is None and not state.acknowledged
                    and actions and actions[0]["kind"] == "reserve_ids"):
                # Descriptor already observed these IDs. Complete only its exact
                # reservation metadata, never create missing archive/root payload.
                self.advance(actions[0])
                return self.abort()
            if state.intent is not None:
                index = state.intent
                entry = document["plan"]["actions"][index]
                target = _relative(entry["target"])
                parent = _fd(stack, _parent(root, target.parent, state.directories))
                node = _node(parent, target.name)
                if entry["kind"] != "move":
                    if node is not None:  # Creation before identity ACK is unowned, even matching bytes.
                        raise _blocked()
                    self._append(document, frames, state, "CANCEL", index)
                    if entry["kind"] == "reserve_ids":
                        self.advance(entry)
                        return self.abort()
                else:
                    source = _relative(entry["source"])
                    source_fd = _fd(stack, _parent(root, source.parent, state.directories))
                    before = _node(source_fd, source.name)
                    expected = state.objects.get(entry["source"])
                    if expected is None:
                        raise _blocked()
                    if before == expected and node is None:
                        self._append(document, frames, state, "CANCEL", index)
                    elif before is None and node == expected:
                        self._append(document, frames, state, "ACK", index, node)
                    else:
                        raise _blocked()
            self._check_objects_for_abort(root, document, state)
            if state.phase not in {"ABORTING", "ABORTED"}:
                self._append(document, frames, state, "ABORT_INTENT")
            while state.acknowledged:
                index = state.acknowledged[-1]
                entry = document["plan"]["actions"][index]
                if entry["kind"] == "reserve_ids":
                    if state.undo_intent is None:
                        self._append(document, frames, state, "UNDO_INTENT", index)
                    self._append(document, frames, state, "UNDONE", index)
                    continue  # Observed task IDs are permanent, not accepted aliases.
                source = _relative(entry["target"])
                target = (_relative(entry["source"]) if entry["kind"] == "move"
                          else _relative(document["frames_path"]) / "quarantine" / f"object-{index}")
                source_fd = _fd(stack, _parent(root, source.parent, state.directories))
                target_fd = _fd(stack, _parent(root, target.parent, state.directories))
                expected = state.objects.get(source.as_posix())
                if state.undo_intent is None:
                    self._append(document, frames, state, "UNDO_INTENT", index)
                before, after = _node(source_fd, source.name), _node(target_fd, target.name)
                if before == expected and after is None and expected is not None:
                    fs.move_noreplace(source_fd, source.name, target_fd, target.name)
                    fs.sync_directory(source_fd)
                    fs.sync_directory(target_fd)
                    if _node(target_fd, target.name) != expected:
                        raise _blocked()
                elif not (before is None and after == expected and expected is not None):
                    raise _blocked()
                self._append(document, frames, state, "UNDONE", index)
            if state.phase != "ABORTED":
                self._append(document, frames, state, "ABORTED")
            return self._retire(stack, root, path, active, document, frames, state, frame_path)

    def _check_objects_for_abort(self, root, document, state):
        # An interrupted inverse move is classified in the loop using both identities.
        if state.undo_intent is None:
            self._check_objects(root, state)

    def _retire(self, stack, root, path, active, document, frames, state, frame_path):
        if state.phase not in {"COMMITTED", "ABORTED"}:
            raise _blocked()
        if document["kind"] == "storage_activation" and state.phase == "COMMITTED":
            destination = Path(".harness-store/receipts") / ("storage-" + self.operation_id)
            if frame_path != destination:
                source_parent = _fd(stack, _parent(root, frame_path.parent, state.directories))
                destination_parent = _fd(stack, _parent(root, destination.parent, state.directories))
                fs.move_noreplace(source_parent, frame_path.name, destination_parent, destination.name)
                fs.sync_directory(source_parent)
                fs.sync_directory(destination_parent)
                frame_path = destination
        if path.name != "descriptor.json":
            fs.move_noreplace(active, path.name, frames, "descriptor.json")
            fs.sync_directory(active)
            fs.sync_directory(frames)
        return {"operation_id": self.operation_id, "status": state.phase,
                "receipt": (frame_path / "descriptor.json").as_posix()}


def recover_operation(repo_root, operation_id):
    repo = Path(repo_root).absolute()
    try:
        with _resources() as owner:
            owner.enter_context(telemetry_lock(repo / ".harness"))
            operation = DirectoryOperation(repo, operation_id)
            with _resources() as stack:
                _, _, _, _, _, state, _ = operation._load(stack)
                committed = state.phase == "COMMITTED"
            return operation.commit() if committed else operation.abort()
    except StorageError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise _blocked() from error
