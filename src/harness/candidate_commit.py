"""Immutable candidate preparation for the opt-in candidate-commit/v1 flow."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import datetime
from pathlib import Path, PurePosixPath

import yaml
from .candidate_assessment import _control_document


class CandidateRefusal(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _git(root: Path, *args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> bytes:
    command = ["git", *args]
    clean_env = os.environ.copy()
    for name in tuple(clean_env):
        if name.startswith("GIT_"):
            clean_env.pop(name)
    if env:
        clean_env.update(env)
    result = subprocess.run(command, cwd=root, env=clean_env, input=stdin, capture_output=True)
    if result.returncode:
        raise CandidateRefusal("CANDIDATE_GIT_UNSUPPORTED")
    return result.stdout


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or value.startswith("-") or path.is_absolute()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or value != path.as_posix() or path.as_posix() == "."
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise CandidateRefusal("CANDIDATE_PATH_INVALID")
    normalized = path.as_posix()
    if normalized == ".harness" or normalized.startswith(".harness/"):
        raise CandidateRefusal("CANDIDATE_PATH_INVALID")
    return normalized


def _index_entries(root: Path) -> dict[str, dict[str, str]]:
    raw = _git(root, "ls-files", "--stage", "-z")
    entries: dict[str, dict[str, str]] = {}
    for field in raw.split(b"\0"):
        if not field:
            continue
        try:
            header, raw_path = field.split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise CandidateRefusal("CANDIDATE_INDEX_UNSUPPORTED") from exc
        path = _safe_path(path)
        if stage != "0" or path in entries:
            raise CandidateRefusal("CANDIDATE_INDEX_UNSUPPORTED")
        entries[path] = {"mode": mode, "oid": oid}
    return entries


def _file_fact(root: Path, path: str) -> dict[str, object]:
    path = _safe_path(path)
    parts = PurePosixPath(path).parts
    target = root.joinpath(*parts)
    try:
        parent = root
        for part in parts[:-1]:
            parent = parent / part
            if not stat.S_ISDIR(parent.lstat().st_mode):
                raise CandidateRefusal('CANDIDATE_INPUT_RACE')
        info = target.lstat()
    except FileNotFoundError:
        return {"path": path, "kind": "missing"}
    if stat.S_ISLNK(info.st_mode):
        raw = os.readlink(target).encode("utf-8", "surrogateescape")
        return {"path": path, "kind": "symlink", "sha256": _digest(raw), "size": len(raw)}
    if not stat.S_ISREG(info.st_mode):
        raise CandidateRefusal("CANDIDATE_SPECIAL_FILE_UNSUPPORTED")
    from . import source_access
    try:
        data = source_access.read_regular_bytes_beneath(target, root)
        current = target.lstat()
        if ((current.st_dev, current.st_ino, current.st_mode, current.st_size, current.st_mtime_ns)
                != (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns)):
            raise CandidateRefusal('CANDIDATE_INPUT_RACE')
    except (OSError, ValueError) as exc:
        raise CandidateRefusal('CANDIDATE_INPUT_RACE') from exc
    return {"path": path, "kind": "regular", "sha256": _digest(data), "size": len(data), "mode": stat.S_IMODE(info.st_mode)}


def _reject_special_nodes(root: Path) -> None:
    """Reject repository special nodes by metadata only; never open their payload."""
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        names[:] = [name for name in names if name not in {".git", ".harness"}]
        base = Path(directory)
        for name in [*names, *files]:
            mode = (base / name).lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                raise CandidateRefusal("CANDIDATE_SPECIAL_FILE_UNSUPPORTED")


def _selected(root: Path, requested: list[str], entries: dict[str, dict[str, str]], parent: str) -> list[dict[str, str]]:
    parent_paths = set(_git(root, "ls-tree", "-r", "--name-only", "-z", parent).decode("utf-8").rstrip("\0").split("\0"))
    selected: list[dict[str, str]] = []
    for path in sorted({_safe_path(value) for value in requested}):
        if path in entries:
            entry = entries[path]
            if entry["mode"] not in {"100644", "100755", "120000"}:
                raise CandidateRefusal("CANDIDATE_MODE_UNSUPPORTED")
            if entry["mode"] == "120000":
                target = _git(root, "cat-file", "blob", entry["oid"]).decode("utf-8")
                link = PurePosixPath(path).parent / target
                if target.startswith("/") or ".." in link.parts or str(link) not in entries:
                    raise CandidateRefusal("CANDIDATE_SYMLINK_UNSUPPORTED")
            selected.append({"action": "upsert", "index_mode": entry["mode"], "index_oid": entry["oid"], "path": path})
        elif path in parent_paths:
            selected.append({"action": "delete", "index_mode": "000000", "index_oid": "0" * 40, "path": path})
        else:
            raise CandidateRefusal("CANDIDATE_SELECTION_NOT_STAGED")
    if not selected:
        raise CandidateRefusal("CANDIDATE_SELECTION_EMPTY")
    return selected


def _candidate_tree(root: Path, parent: str, selected: list[dict[str, str]], work: Path) -> str:
    index = work / "index"
    env = {"GIT_INDEX_FILE": str(index)}
    _git(root, "read-tree", parent, env=env)
    lines = []
    for item in selected:
        if item["action"] == "delete":
            lines.append(f"0 {'0' * 40}\t{item['path']}\n")
        else:
            lines.append(f"{item['index_mode']} {item['index_oid']}\t{item['path']}\n")
    _git(root, "update-index", "--index-info", env=env, stdin="".join(lines).encode())
    return _git(root, "write-tree", env=env).decode().strip()


def _candidate_entry(command):
    from functools import wraps
    from .candidate_assessment import CandidateAssessmentError
    from .transaction_recovery import PublicationAdmissionError, publication_admission

    @wraps(command)
    def admitted(*args, **kwargs):
        root = Path(args[0] if args else kwargs.get("repo_root", kwargs.get("root")))
        try:
            with publication_admission(root / ".harness"):
                return command(*args, **kwargs)
        except PublicationAdmissionError as exc:
            raise CandidateRefusal("RECOVERY_UNSUPPORTED") from exc
        except CandidateAssessmentError as exc:
            raise CandidateRefusal(str(exc)) from exc
    return admitted


def _publish_immutable(root: Path, path: Path, content: bytes) -> None:
    from . import source_access

    if os.path.lexists(path):
        if source_access.read_regular_bytes_beneath(path, root / ".harness") != content:
            raise CandidateRefusal("CANDIDATE_RECORD_CONFLICT")
        return
    _publish_documents(root, {path.relative_to(root / ".harness").as_posix(): content})


@_candidate_entry
def prepare(repo_root: Path, requested: list[str]) -> dict[str, object]:
    from .candidate_assessment import (
        CandidateAssessmentError, require_candidate_policy, semantic_source_snapshot,
    )

    root = repo_root.resolve()
    harness = root / ".harness"
    from . import source_access
    try:
        task = yaml.safe_load(source_access.read_regular_bytes_beneath(
            harness / 'current-task.yaml', harness))
    except (OSError, yaml.YAMLError) as exc:
        raise CandidateRefusal("CANDIDATE_TASK_INVALID") from exc
    if not isinstance(task, dict) or task.get("state") != "IMPLEMENTING":
        raise CandidateRefusal("CANDIDATE_PHASE_INVALID")
    try:
        require_candidate_policy(harness)
    except CandidateAssessmentError as exc:
        raise CandidateRefusal(str(exc)) from exc
    owned = set((task.get("scope") or {}).get("owned_paths") or ())
    protected = set((task.get("scope") or {}).get("protected_user_paths") or ())
    paths = [_safe_path(path) for path in requested]
    if any(path not in owned for path in paths):
        raise CandidateRefusal("CANDIDATE_PATH_NOT_OWNED")
    if any(path in protected for path in paths):
        raise CandidateRefusal("CANDIDATE_PATH_PROTECTED")
    _reject_special_nodes(root)
    from .git_mutation import GitMutationError, repository_policy
    try:
        git_policy = repository_policy(root)
    except GitMutationError as exc:
        raise CandidateRefusal("CANDIDATE_GIT_UNSUPPORTED") from exc

    parent = _git(root, "rev-parse", "HEAD").decode().strip()
    full_ref = _git(root, "symbolic-ref", "-q", "HEAD").decode().strip()
    if not full_ref.startswith("refs/heads/"):
        raise CandidateRefusal("CANDIDATE_REPOSITORY_UNSUPPORTED")
    entries = _index_entries(root)
    selected = _selected(root, paths, entries, parent)
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    from . import source_access
    index_info = index_path.lstat()
    index_bytes = source_access.read_regular_bytes_beneath(index_path, root / ".git")

    raw_untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = sorted(_safe_path(value.decode("utf-8")) for value in raw_untracked.split(b"\0") if value and not value.startswith(b".harness/"))
    input_facts = {
        "tracked_worktree": [_file_fact(root, path) for path in sorted(entries)],
        "untracked": [_file_fact(root, path) for path in untracked],
        "protected": [_file_fact(root, path) for path in sorted(protected)],
    }
    with tempfile.TemporaryDirectory(prefix="candidate-index-", dir=harness) as directory:
        tree = _candidate_tree(root, parent, selected, Path(directory))
    common = Path(_git(root, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = (root / common).resolve()
    projection = {
        "schema": "candidate-prepared/v1",
        "domain": "harness:candidate-prepared:v1",
        "task": {"id": (task.get("task") or {}).get("id"), "type": (task.get("task") or {}).get("type")},
        "risk": {key: (task.get("risk") or {}).get(key) for key in ("level", "profile", "dimensions")},
        "git_policy": git_policy,
        "scope": {"owned_paths": sorted(owned), "protected_user_paths": sorted(protected)},
        "git": {key: (task.get("git") or {}).get(key) for key in ("base_ref", "base_commit", "head_at_start")},
        "plan_reconciliation": task.get("plan_reconciliation"),
        "parent": parent,
        "full_ref": full_ref,
        "repository_identity": _digest(str(root).encode()),
        "common_git_dir_identity": _digest(str(common).encode()),
        "object_format": "sha1",
        "candidate_tree": tree,
        "selected": selected,
        "index": {"sha256": _digest(index_bytes),
                  "identity": [index_info.st_dev, index_info.st_ino, stat.S_IMODE(index_info.st_mode)],
                  "entries": [{"path": path, **entry} for path, entry in sorted(entries.items())]},
        "inputs": input_facts,
        "semantic_sources": semantic_source_snapshot(harness),
    }
    candidate_id = _digest(b"harness:candidate-prepared:v1\0" + _canonical_bytes(projection))
    record = {**projection, "candidate_id": candidate_id}
    directory = harness / "evidence" / "candidate-prepared"
    target = directory / f"{candidate_id.removeprefix('sha256:')}.json"
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    _publish_immutable(root, target, encoded)
    pointer = {"schema": "candidate-active/v1", "task_id": record["task"]["id"], "candidate_id": candidate_id}
    _publish_documents(root, {".candidate-active.json": _canonical_bytes(pointer)})
    return {"candidate": candidate_id, "record": target.relative_to(root).as_posix(), "status": "PREPARED"}


COMMAND_REASONS = frozenset({
    'CANDIDATE_UNSUPPORTED', 'CANDIDATE_DRIFT', 'CANDIDATE_PROOF_UNQUALIFIED',
    'CANDIDATE_REVIEW_UNQUALIFIED', 'CANDIDATE_GATE_BLOCKED', 'USER_AUTHORITY_REQUIRED',
    'CANDIDATE_OPERATION_PENDING', 'CANDIDATE_REF_CONFLICT', 'REF_PUBLISHED_POSTCHECK_FAILED',
    'RECOVERY_UNSUPPORTED', 'CANDIDATE_SCHEMA_UNSUPPORTED', 'CANDIDATE_INTERNAL_ERROR',
})


def _command_base(command, payload, reason, candidate_id, operation_id):
    reason = reason if reason in COMMAND_REASONS or reason is None else 'CANDIDATE_UNSUPPORTED'
    def identifier(value):
        return value if isinstance(value, str) and re_full_sha(value) else None
    return {
        'schema': 'candidate-command-result/v1', 'ok': reason is None, 'command': command,
        'task_id': None, 'candidate_id': identifier(payload.get('candidate') or candidate_id),
        'operation_id': identifier(payload.get('operation') or operation_id),
        'acceptance_id': identifier(payload.get('acceptance')), 'parent_commit': None,
        'proposed_commit': None, 'phase': 'NOT_STARTED', 'mutation_started': False,
        'reason_code': reason, 'message': reason or 'Candidate command completed.', 'artifact_ref': None,
    }


def unavailable_command_result(command, *, candidate_id=None, operation_id=None):
    result = _command_base(command, {}, 'CANDIDATE_INTERNAL_ERROR', candidate_id, operation_id)
    result.update(phase='UNKNOWN', mutation_started=None)
    return result


def command_result(root, command, payload=None, *, reason=None, candidate_id=None, operation_id=None):
    """Closed public DTO. Caller holds task lock across action and correlation."""
    import re
    from . import source_access
    from .transaction_recovery import candidate_operations

    payload = payload or {}
    result = _command_base(command, payload, reason, candidate_id, operation_id)
    if reason is None:
        result['phase'] = {'candidate prepare': 'PREPARED', 'candidate prove': 'PROVED',
                           'candidate review-record': 'RECORDED', 'gate': 'CONVERGED',
                           'candidate status': 'KNOWN'}.get(command, 'NOT_STARTED')
    if root is None:
        return result
    harness = root / '.harness'
    try:
        task = yaml.safe_load(source_access.read_regular_bytes_beneath(harness / 'current-task.yaml', harness))
        task_id = task.get('task', {}).get('id')
        if isinstance(task_id, str) and re.fullmatch(r'TASK-[0-9]+', task_id):
            result['task_id'] = task_id
        operations = candidate_operations(harness, allow_incomplete_trace=True)
        matches = [item for item in operations if item['payload']['task_id'] == task_id and (
            item['operation_id'] == result['operation_id'] if result['operation_id'] else
            item['payload']['candidate_id'] == result['candidate_id'] and item['phase'] != 'ABORTED_AUTHORITY_REVOKED')]
        if len(matches) == 1:
            operation = matches[0]
            captured = operation['payload']
            result.update(candidate_id=captured['candidate_id'], operation_id=operation['operation_id'],
                          acceptance_id=captured['acceptance_id'], parent_commit=captured['parent'],
                          proposed_commit=captured['proposed'], phase=operation['phase'],
                          mutation_started=operation['mutation_started'])
            if operation['phase'] == 'TRACE_PUBLISHED':
                result['artifact_ref'] = '.harness/evidence/candidate-trace/' + operation['operation_id'][7:] + '.json'
            else:
                result['artifact_ref'] = '.harness/.candidate-operations/' + operation['operation_id'][7:] + '.json'
        elif len(matches) > 1:
            result.update(phase='UNKNOWN', mutation_started=None)
        elif result['candidate_id'] is not None:
            _, candidate = _candidate_record(root, result['candidate_id'])
            result['parent_commit'] = candidate['parent']
            if command == 'candidate status':
                result['artifact_ref'] = '.harness/evidence/candidate-prepared/' + result['candidate_id'][7:] + '.json'
    except Exception:
        # Unreadable intent is uncertainty, never evidence of no Git side effects.
        if os.path.lexists(harness / '.candidate-operations'):
            result.update(phase='UNKNOWN', mutation_started=None)
    reference = payload.get('record')
    if reference is not None and re.fullmatch(
            r'\.harness/evidence/candidate-(prepared|proof|review|acceptance|trace)/[a-f0-9]{64}\.json', str(reference)):
        result['artifact_ref'] = reference
    return result


def render_refusal(code: str) -> dict[str, str]:
    return {"code": code, "status": "REFUSED"}


def _candidate_record(root: Path, candidate_id: str) -> tuple[Path, dict]:
    if not isinstance(candidate_id, str) or not re_full_sha(candidate_id):
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
    path = root / ".harness" / "evidence" / "candidate-prepared" / f"{candidate_id[7:]}.json"
    from jsonschema import ValidationError
    from .candidate_assessment import CandidateAssessmentError, _bound_document

    try:
        record = _bound_document(root / '.harness', path.relative_to(root / '.harness'),
                                 'candidate-prepared.schema.json', 'candidate_id',
                                 b'harness:candidate-prepared:v1\0')
    except (OSError, ValueError, TypeError, KeyError, ValidationError, CandidateAssessmentError) as exc:
        raise CandidateRefusal('CANDIDATE_SCHEMA_UNSUPPORTED') from exc
    return path, record


def re_full_sha(value: str) -> bool:
    return value.startswith("sha256:") and len(value) == 71 and set(value[7:]) <= set("0123456789abcdef")


def _safe_json_document(path: Path) -> tuple[dict, bytes]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED") from exc
    try:
        current = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
        chunks: list[bytes] = []
        remaining = 8 * 1024 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
    finally:
        os.close(descriptor)
    if len(data) > 8 * 1024 * 1024:
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
    try:
        value = json.loads(data)
    except json.JSONDecodeError as exc:
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED") from exc
    if not isinstance(value, dict):
        raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
    return value, data


def _safe_json_file(path: Path) -> dict:
    return _safe_json_document(path)[0]


@_candidate_entry
def prove(root: Path, candidate_id: str, spec_path: Path) -> dict[str, object]:
    from .candidate_runner import CandidateRunnerError, run

    _, record = _candidate_record(root, candidate_id)
    task = _control_document(root / '.harness', 'current-task.yaml')
    if task.get("state") not in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "GATING"}:
        raise CandidateRefusal("CANDIDATE_PHASE_INVALID")
    spec, spec_bytes = _safe_json_document(spec_path)
    try:
        result = run(root, record, spec)
    except CandidateRunnerError as exc:
        raise CandidateRefusal(str(exc)) from exc
    if result["execution"]["exit_code"] != 0:
        raise CandidateRefusal("CANDIDATE_PROOF_UNQUALIFIED")
    receipt = {
        "schema": "candidate-proof/v1",
        "domain": "harness:candidate-proof:v1",
        "candidate_id": candidate_id,
        "spec_sha256": _digest(spec_bytes),
        "execution": result["execution"],
        "record": result["record"],
        "qualification": result["qualification"],
    }
    proof_id = _digest(b"harness:candidate-proof:v1\0" + _canonical_bytes(receipt))
    receipt["proof_id"] = proof_id
    target = root / ".harness" / "evidence" / "candidate-proof" / f"{proof_id[7:]}.json"
    _publish_immutable(root, target, _canonical_bytes(receipt))
    return {"candidate": candidate_id, "proof": proof_id, "record": target.relative_to(root).as_posix(), "status": "PROVED"}


def _candidate_proof_fingerprint(
    root: Path, candidate_id: str, candidate: dict
) -> str:
    from jsonschema import ValidationError, validate

    from .schema_resources import read_schema

    directory = root / ".harness" / "evidence" / "candidate-proof"
    fingerprints: set[str] = set()
    for path in sorted(directory.glob("*.json")) if directory.exists() else ():
        proof = _safe_json_file(path)
        if proof.get("candidate_id") != candidate_id:
            continue
        try:
            validate(proof, read_schema("candidate-proof.schema.json"))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED") from exc
        projection = dict(proof)
        proof_id = projection.pop("proof_id")
        expected = _digest(
            b"harness:candidate-proof:v1\0" + _canonical_bytes(projection)
        )
        execution = proof["execution"]
        if (
            proof_id != expected
            or path.name != f"{expected[7:]}.json"
            or execution["candidate_tree"] != candidate["candidate_tree"]
            or execution["parent_commit"] != candidate["parent"]
            or execution["source_before"] != execution["source_after"]
        ):
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
        fingerprints.add(execution["source_before"])
    if len(fingerprints) != 1:
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
    return next(iter(fingerprints))


def _review_scope(
    root: Path,
    candidate_id: str,
    kind: str,
    scope: dict,
    task: dict,
    source_fingerprint: str,
) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
    from .workspace import observability_inspected_paths, project_typed_scope

    if set(scope) != {
        "schema",
        "candidate_id",
        "kind",
        "source_fingerprint",
        "files",
        "contract_refs",
        "direct_dependencies",
    } or (
        scope.get("schema") != "candidate-review-scope/v1"
        or scope.get("candidate_id") != candidate_id
        or scope.get("kind") != kind
        or scope.get("source_fingerprint") != source_fingerprint
        or not isinstance(scope.get("files"), list)
        or not isinstance(scope.get("contract_refs"), list)
        or not isinstance(scope.get("direct_dependencies"), list)
    ):
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
    harness = root / ".harness"
    try:
        impact = _control_document(harness, 'impact.yaml') or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED") from exc
    inspected = observability_inspected_paths(harness)
    try:
        expected_files, expected_refs = project_typed_scope(
            task,
            impact.get("impact") or {},
            inspected_paths=inspected,
            direct_dependencies=(
                tuple(scope["direct_dependencies"])
                if kind == "diagnosability"
                else ()
            ),
        )
    except (TypeError, ValueError) as exc:
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED") from exc
    if (
        tuple(sorted(set(scope["files"]))) != expected_files
        or tuple(sorted(set(scope["contract_refs"]))) != expected_refs
        or (kind != "diagnosability" and scope["direct_dependencies"])
    ):
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
    return scope, expected_files, expected_refs


@_candidate_entry
def review_record(root: Path, candidate_id: str, kind: str, manifest: Path, scope: Path, report: Path) -> dict[str, object]:
    import datetime

    from jsonschema import ValidationError

    from .complexity import validate_complexity_checks, validate_complexity_finding

    _, candidate = _candidate_record(root, candidate_id)
    manifest_document, manifest_bytes = _safe_json_document(manifest)
    if manifest_document != candidate:
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
    task = _control_document(root / '.harness', 'current-task.yaml')
    if task.get("state") not in {"VERIFYING", "REVIEWING", "GATING"} or kind not in {"complexity", "diagnosability", "interface"}:
        raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
    source_fingerprint = _candidate_proof_fingerprint(
        root, candidate_id, candidate
    )
    scope_document, scope_bytes = _safe_json_document(scope)
    scope_document, files, contract_refs = _review_scope(
        root, candidate_id, kind, scope_document, task, source_fingerprint
    )
    report_document, report_bytes = _safe_json_document(report)
    task_id = (task.get("task") or {}).get("id")
    common = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "exit_code": 0,
        "execution_domain": "outside-git",
        "candidate_tree": candidate["candidate_tree"],
        "source_fingerprint": source_fingerprint,
    }
    if kind == "complexity":
        if (
            report_document.get("task") != task_id
            or not isinstance(report_document.get("findings"), list)
        ):
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
        try:
            validate_complexity_checks(report_document)
            for finding in report_document["findings"]:
                validate_complexity_finding(finding)
        except (ValidationError, ValueError) as exc:
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED") from exc
        finding_ids = [finding["id"] for finding in report_document["findings"]]
        if len(finding_ids) != len(set(finding_ids)) or any(
            check["result"] == "fail"
            for check in report_document["checks"].values()
        ) or any(
            finding["status"] == "open" and finding["severity"] == "high"
            for finding in report_document["findings"]
        ):
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
        record = {
            **common,
            "type": "review",
            "command": "harness review complexity",
            "base": candidate["parent"],
            "head": candidate["candidate_tree"],
            "finding_ids": finding_ids,
            "checks": report_document["checks"],
            "review_scope": {
                "files": list(files),
                "contract_refs": list(contract_refs),
            },
        }
    elif kind == "diagnosability":
        from .diagnosability import (
            load_contract,
            validate_review_evidence,
            validate_review_input,
            validate_review_readiness,
        )

        try:
            review = validate_review_input(report_document, task_id=task_id)
            contract = load_contract(
                root / ".harness", task_type=(task.get("task") or {}).get("type")
            )
            if (
                any(value == "fail" for value in review.checks.values())
                or review.proposals
                or review.finding_ids
                or tuple(review.direct_dependencies)
                != tuple(scope_document["direct_dependencies"])
            ):
                raise ValueError("candidate diagnosability review is not PASS")
            validate_review_readiness(
                contract, report_document, [], scope_files=files
            )
            record = {
                **common,
                "type": "diagnosability_review",
                "command": "harness review diagnosability",
                "review_scope": {
                    "files": list(files),
                    "contract_refs": list(contract_refs),
                    "direct_dependencies": list(review.direct_dependencies),
                },
                "contract_required": review.contract_required,
                "checks": review.checks,
                "finding_ids": [],
                "finding_mapping": {},
            }
            validate_review_evidence(
                {
                    **{
                        key: value
                        for key, value in record.items()
                        if key
                        not in {
                            "candidate_tree",
                            "execution_domain",
                            "source_fingerprint",
                        }
                    },
                    "commit": candidate["candidate_tree"],
                    "workspace_fingerprint": source_fingerprint,
                    "workspace_fingerprint_after": source_fingerprint,
                }
            )
        except (ValidationError, ValueError) as exc:
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED") from exc
    else:
        from .interface_review import validate_review_report

        try:
            validate_review_report(
                root / ".harness", report_document, task_id=task_id
            )
        except ValueError as exc:
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED") from exc
        if any(value == "fail" for value in report_document["checks"].values()) or report_document.get("proposals"):
            raise CandidateRefusal("CANDIDATE_REVIEW_UNQUALIFIED")
        record = {
            **common,
            "type": "review",
            "command": "harness review interface",
            "contracts": report_document["contracts"],
            "checks": report_document["checks"],
            "proposals": [],
            "finding_mapping": {},
            "review_scope": {
                "files": list(files),
                "contract_refs": list(contract_refs),
            },
        }
    inputs = {
        "manifest": _digest(manifest_bytes),
        "scope": _digest(scope_bytes),
        "report": _digest(report_bytes),
    }
    receipt = {
        "schema": "candidate-review/v1",
        "domain": "harness:candidate-review:v1",
        "candidate_id": candidate_id,
        "kind": kind,
        "inputs": inputs,
        "report": report_document,
        "record": record,
        "qualification": {
            "candidate_tree": candidate["candidate_tree"],
            "parent_commit": candidate["parent"],
            "source_fingerprint": source_fingerprint,
            "outcome": "PASS",
            "scope_complete": True,
            "review_scope": list(files),
        },
    }
    review_id = _digest(b"harness:candidate-review:v1\0" + _canonical_bytes(receipt))
    receipt["review_id"] = review_id
    target = root / ".harness" / "evidence" / "candidate-review" / f"{review_id[7:]}.json"
    _publish_immutable(root, target, _canonical_bytes(receipt))
    return {"candidate": candidate_id, "review": review_id, "record": target.relative_to(root).as_posix(), "status": "RECORDED"}


@_candidate_entry
def accept(root: Path, candidate_id: str) -> dict[str, object]:
    from .candidate_assessment import (
        CandidateAssessmentError,
        build_candidate_assessment_view,
        semantic_source_snapshot,
    )
    from .quality_gate import assess_gate, gate_command_errors

    _, candidate = _candidate_record(root, candidate_id)
    task = _control_document(root / '.harness', 'current-task.yaml')
    if task.get("state") != "GATING":
        raise CandidateRefusal("CANDIDATE_PHASE_INVALID")
    proof_directory = root / ".harness" / "evidence" / "candidate-proof"
    qualified_proofs: list[tuple[Path, dict]] = []
    for path in sorted(proof_directory.glob("*.json")) if proof_directory.exists() else ():
        proof = _safe_json_file(path)
        if proof.get("candidate_id") != candidate_id:
            continue
        qualified_proofs.append((path, proof))
    review_directory = root / ".harness" / "evidence" / "candidate-review"
    qualified_reviews: list[tuple[Path, dict]] = []
    for path in sorted(review_directory.glob("*.json")) if review_directory.exists() else ():
        review = _safe_json_file(path)
        if review.get("candidate_id") == candidate_id:
            qualified_reviews.append((path, review))
    try:
        view = build_candidate_assessment_view(
            root, candidate, tuple(qualified_proofs), tuple(qualified_reviews)
        )
    except (CandidateAssessmentError, OSError, yaml.YAMLError) as exc:
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED") from exc
    if not qualified_proofs:
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED")
    if not _input_consistent(root, candidate, head=candidate['parent']):
        raise CandidateRefusal('CANDIDATE_DRIFT')
    _proof_inputs_unchanged(root, candidate_id)
    captured_sources = _gate_sources(root, list(view.evidence_refs))
    try:
        assessment = assess_gate(root / ".harness", assessment_view=view)
    except gate_command_errors() as exc:
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED") from exc
    from .controlplane import _apply_gate_convergence

    if assessment.status != "PASS" or assessment.blockers:
        if assessment.status != 'PASS':
            _apply_gate_convergence(root / '.harness', task, assessment,
                                    emit=lambda *args, **kwargs: None, head=view.parent_commit)
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED")
    if not _input_consistent(root, candidate, head=candidate['parent']):
        raise CandidateRefusal('CANDIDATE_DRIFT')
    _proof_inputs_unchanged(root, candidate_id)
    semantic = dict(view.semantic_sources)
    if (semantic_source_snapshot(root / ".harness") != semantic
            or _gate_sources(root, list(view.evidence_refs)) != captured_sources):
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED")
    receipt = {
        "schema": "candidate-acceptance/v1",
        "domain": "harness:candidate-acceptance:v1",
        "assessment_domain": view.domain,
        "candidate_id": candidate_id,
        "parent_commit": view.parent_commit,
        "candidate_tree": view.candidate_tree,
        "export_fingerprint": view.export_fingerprint,
        "proof_ids": list(view.proof_ids),
        "review_ids": list(view.review_ids),
        "evidence_refs": list(view.evidence_refs),
        "semantic_sources": semantic,
        "gate": assessment.status,
        "gate_blockers": [],
        "gate_sources": captured_sources,
    }
    acceptance_id = _digest(b"harness:candidate-acceptance:v1\0" + _canonical_bytes(receipt))
    receipt["acceptance_id"] = acceptance_id
    target = root / ".harness" / "evidence" / "candidate-acceptance" / f"{acceptance_id[7:]}.json"
    _publish_immutable(root, target, _canonical_bytes(receipt))
    _apply_gate_convergence(root / '.harness', task, assessment,
                            emit=lambda *args, **kwargs: None, head=view.parent_commit)
    return {"acceptance": acceptance_id, "candidate": candidate_id, "record": target.relative_to(root).as_posix(), "status": "ACCEPTED"}


def controlled_commit(root: Path, candidate_id: str, message_path: Path) -> dict[str, object]:
    import base64
    from . import source_access
    from .git_mutation import GitMutationError, commit_tree, repository_policy
    from .telemetry_lock import telemetry_lock
    from .transaction_recovery import (
        candidate_operations, candidate_publication_owner, require_no_pending_publications,
    )

    harness = root / ".harness"
    try:
        with telemetry_lock(harness):
            operations = candidate_operations(harness)
            if not any(item["phase"] in {"PREPARED", "REF_CAS_STARTED"} for item in operations):
                require_no_pending_publications(harness)
            _, candidate = _candidate_record(root, candidate_id)
            info = message_path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
            message = source_access.read_regular_bytes(message_path)
            if not message or b"\0" in message or len(message) > 1024 * 1024:
                raise CandidateRefusal("CANDIDATE_SCHEMA_UNSUPPORTED")
            for operation in operations:
                if (operation["payload"]["candidate_id"] == candidate_id
                        and operation["phase"] != "ABORTED_AUTHORITY_REVOKED"):
                    if operation["payload"]["message_sha256"] != _digest(message):
                        raise CandidateRefusal("CANDIDATE_RECORD_CONFLICT")
                    result = recover(root, operation["operation_id"])
                    return {**result, "status": "COMMITTED"}
            if any(item["phase"] in {"PREPARED", "REF_CAS_STARTED"} for item in operations):
                raise CandidateRefusal("RECOVERY_UNSUPPORTED")
            task = yaml.safe_load(source_access.read_regular_bytes_beneath(harness / "current-task.yaml", harness))
            if task.get("state") not in {"CONVERGED", "DONE"}:
                raise CandidateRefusal("CANDIDATE_PHASE_INVALID")
            grant = (task.get("authorizations") or {}).get("commit") or {}
            if grant.get("granted") is not True or grant.get("source") != "user":
                raise CandidateRefusal("USER_AUTHORITY_REQUIRED")
            acceptance, acceptance_path = _commit_acceptance(root, candidate)
            if task.get("gate", {}).get("status") != "PASS":
                raise CandidateRefusal("CANDIDATE_GATE_BLOCKED")
            if not _input_consistent(root, candidate, head=candidate["parent"]):
                raise CandidateRefusal("CANDIDATE_DRIFT")
            policy = repository_policy(root)
            name, email = policy["author_name"], policy["author_email"]
            if any(not isinstance(value, str) or not value or any(c in value for c in "\0\r\n<>")
                   for value in (name, email)):
                raise CandidateRefusal("CANDIDATE_GIT_UNSUPPORTED")
            stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
            identity = {f"GIT_{role}_{field}": value for role in ("AUTHOR", "COMMITTER")
                        for field, value in (("NAME", name), ("EMAIL", email), ("DATE", stamp))}
            proposed = commit_tree(root, candidate["candidate_tree"], candidate["parent"], message, identity)
            immutable = {"evidence/candidate-prepared/" + candidate_id[7:] + ".json",
                         acceptance_path.relative_to(harness).as_posix()}
            immutable.update(reference.removeprefix(".harness/") for reference in acceptance["evidence_refs"])
            snapshots = {reference: _digest(source_access.read_regular_bytes_beneath(harness / reference, harness))
                         for reference in immutable}
            payload = {"task_id": task["task"]["id"], "candidate_id": candidate_id,
                       "acceptance_id": acceptance["acceptance_id"], "parent": candidate["parent"],
                       "tree": candidate["candidate_tree"], "full_ref": candidate["full_ref"],
                       "proposed": proposed, "message_base64": base64.b64encode(message).decode(),
                       "message_sha256": _digest(message), "identity": identity, "git_policy": policy,
                       "accepted_sources": snapshots, "grant_receipt": _digest(_canonical_bytes(grant))}
            identifier = _digest(b"harness:candidate-operation:v1\0" + _canonical_bytes(payload))
            operation = {"schema": "candidate-operation/v1", "domain": "harness:candidate-operation:v1",
                         "operation_id": identifier, "payload": payload, "phase": "PREPARED",
                         "mutation_started": False, "grant_consumed": False}
            with candidate_publication_owner(harness, identifier):
                _write_operation(root, operation)
                result = recover(root, identifier)
                return {**result, "status": "COMMITTED"}
    except GitMutationError as exc:
        raise CandidateRefusal("CANDIDATE_GIT_UNSUPPORTED") from exc
    except OSError as exc:
        raise CandidateRefusal("RECOVERY_UNSUPPORTED") from exc


def status(root: Path, candidate_id: str) -> dict[str, object]:
    from .telemetry_lock import telemetry_lock
    from .transaction_recovery import _pending_paths, candidate_operations

    harness = root / ".harness"
    try:
        with telemetry_lock(harness):
            if _pending_paths(harness):
                raise CandidateRefusal("RECOVERY_UNSUPPORTED")
            _, candidate = _candidate_record(root, candidate_id)
            operations = [item for item in candidate_operations(harness)
                          if item["payload"]["candidate_id"] == candidate_id]
            for operation in operations:
                _historical_operation(root, operation)
            committed = [item for item in operations if item["phase"] == "TRACE_PUBLISHED"]
            current = _git(root, "rev-parse", "HEAD").decode().strip()
            expected = committed[0]["payload"]["proposed"] if committed else candidate["parent"]
            return {"candidate": candidate_id, "historically_committed": bool(committed),
                    "live_parent": current == candidate["parent"],
                    "live_proposed": any(item["payload"]["proposed"] == current for item in committed),
                    "input_consistent": _input_consistent(root, candidate, head=expected), "status": "KNOWN"}
    except OSError as exc:
        raise CandidateRefusal("RECOVERY_UNSUPPORTED") from exc


_GATE_FILES = (".candidate-active.json", "requirements.yaml", "invariants.yaml", "alignment.yaml", "alignment-freeze.yaml",
               "impact.yaml", "plan.yaml", "plan-execution.yaml", "gate.yaml", "observability.yaml",
               "review-outcome.yaml", "risk-boundaries.yaml", "test-scope-baseline.yaml",
               "test-scope-audit.yaml", "test-scope-seal.yaml")
_GATE_DIRECTORIES = ("decisions", "interface-contracts", "findings", "evidence")


def _gate_sources(root: Path, references: list[str]) -> dict[str, str | None]:
    from . import source_access
    from .candidate_assessment import semantic_source_snapshot
    from .git_mutation import GitMutationError, repository_policy

    harness = root / ".harness"
    try:
        policy = repository_policy(root)
    except GitMutationError as exc:
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED") from exc
    sources = {"@task": semantic_source_snapshot(harness)["current-task.yaml"],
               "@git": _digest(_canonical_bytes(policy))}
    names = set(_GATE_FILES)
    for directory in _GATE_DIRECTORIES:
        parent = harness / directory
        if parent.is_symlink():
            raise CandidateRefusal("CANDIDATE_GATE_BLOCKED")
        members = sorted(path.name for path in parent.glob("*.json" if directory == "evidence" else "*.yaml"))
        sources["@members/" + directory] = _digest(_canonical_bytes(members))
        names.update(directory + "/" + member for member in members)
    for reference in references:
        if not reference.startswith(".harness/evidence/"):
            raise CandidateRefusal("CANDIDATE_GATE_BLOCKED")
        names.add(reference.removeprefix(".harness/"))
    for name in names:
        path = harness / name
        sources[name] = (_digest(source_access.read_regular_bytes_beneath(path, harness))
                         if os.path.lexists(path) else None)
    package = Path(__file__).parent
    code = {str(path.relative_to(package)): _digest(path.read_bytes())
            for path in sorted(package.rglob("*")) if path.suffix in {".py", ".json", ".yaml"}
            and "__pycache__" not in path.parts and path.is_file()}
    sources["@tool"] = _digest(_canonical_bytes(code))
    return sources


def _proof_inputs_unchanged(root: Path, candidate_id: str) -> None:
    from .candidate_runner import CandidateRunnerError, _regular_bytes, _runtime

    try:
        for path in (root / ".harness/evidence/candidate-proof").glob("*.json"):
            proof = _safe_json_file(path)
            if proof.get("candidate_id") != candidate_id:
                continue
            execution = proof["execution"]
            runtime = execution["runtime"]
            if _runtime(runtime["executable"]) != runtime:
                raise CandidateRefusal("CANDIDATE_DRIFT")
            for dependency in execution["dependencies"]["files"]:
                if _digest(_regular_bytes(Path(dependency["source"]))) != dependency["sha256"]:
                    raise CandidateRefusal("CANDIDATE_DRIFT")
    except (OSError, ValueError, KeyError, CandidateRunnerError) as exc:
        raise CandidateRefusal("CANDIDATE_DRIFT") from exc


def _commit_acceptance(root: Path, candidate: dict) -> tuple[dict, Path]:
    from jsonschema import ValidationError, validate
    from .schema_resources import read_schema

    matches = []
    for path in (root / ".harness/evidence/candidate-acceptance").glob("*.json"):
        record = _safe_json_file(path)
        if record.get("candidate_id") == candidate["candidate_id"]:
            matches.append((record, path))
    try:
        if len(matches) != 1:
            raise ValueError("acceptance not uniquely selected")
        record, path = matches[0]
        validate(record, read_schema("candidate-acceptance.schema.json"))
        body = dict(record)
        identifier = body.pop("acceptance_id")
        if (identifier != _digest(b"harness:candidate-acceptance:v1\0" + _canonical_bytes(body))
                or path.name != identifier[7:] + ".json"
                or record["parent_commit"] != candidate["parent"]
                or record["candidate_tree"] != candidate["candidate_tree"]
                or not record.get("gate_sources")
                or _gate_sources(root, record["evidence_refs"]) != record["gate_sources"]):
            raise ValueError("acceptance source changed")
        return record, path
    except (ValueError, KeyError, ValidationError) as exc:
        raise CandidateRefusal("CANDIDATE_GATE_BLOCKED") from exc


def _publish_documents(root: Path, documents: dict[str, bytes]) -> None:
    """Use the existing inode-preserving, fsynced Harness publisher, not rename-only I/O."""
    from . import source_access, transaction

    harness = root / ".harness"
    before = {}
    for name in documents:
        path = harness / name
        if path.is_symlink():
            raise CandidateRefusal("RECOVERY_UNSUPPORTED")
        before[name] = (source_access.read_regular_bytes_beneath(path, harness)
                        if os.path.lexists(path) else None)
    artifacts = tuple(transaction.StagedArtifact(name, content) for name, content in documents.items())
    staged = transaction.stage(harness, list(artifacts))
    transaction.publish(harness, staged, durable=True,
                        replace_paths=frozenset(name for name, value in before.items() if value is not None),
                        expected_sources=before, expected_artifacts=artifacts)


def _operation_name(operation: dict) -> str:
    return f'.candidate-operations/{operation["operation_id"][7:]}.json'


def _write_operation(root: Path, operation: dict, *, task: dict | None = None) -> None:
    documents = {_operation_name(operation): _canonical_bytes(operation)}
    if task is not None:
        documents["current-task.yaml"] = yaml.safe_dump(task, sort_keys=False).encode()
    _publish_documents(root, documents)


def _historical_operation(root: Path, operation: dict) -> tuple[dict, dict]:
    """Check immutable captured metadata, not current worktree/authority freshness."""
    import base64
    from jsonschema import ValidationError, validate
    from . import source_access
    from .candidate_assessment import CandidateAssessmentError, historical_candidate_metadata

    payload = operation["payload"]
    try:
        task, candidate, _ = historical_candidate_metadata(root / '.harness', operation)
        message = base64.b64decode(payload["message_base64"], validate=True)
        if not message or b"\0" in message or _digest(message) != payload["message_sha256"]:
            raise ValueError("message mismatch")
        raw = _git(root, "cat-file", "commit", payload["proposed"])
        headers, separator, actual_message = raw.partition(b"\n\n")
        if (not separator or actual_message != message + (b"" if message.endswith(b"\n") else b"\n")
                or headers.splitlines()[:2] != [f'tree {payload["tree"]}'.encode(), f'parent {payload["parent"]}'.encode()]):
            raise ValueError("commit payload mismatch")
        return task, candidate
    except (OSError, ValueError, TypeError, KeyError, ValidationError, yaml.YAMLError, CandidateAssessmentError) as exc:
        raise CandidateRefusal("RECOVERY_UNSUPPORTED") from exc


def _input_consistent(root: Path, candidate: dict, *, head: str) -> bool:
    from .candidate_assessment import semantic_source_snapshot
    from .git_mutation import GitMutationError, repository_policy
    from . import source_access

    try:
        _reject_special_nodes(root)
        if (_digest(str(root.resolve()).encode()) != candidate['repository_identity']
                or repository_policy(root) != candidate["git_policy"]):
            return False
        index = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
        if not index.is_absolute():
            index = root / index
        index_info = index.lstat()
        if candidate["index"]["identity"] != [index_info.st_dev, index_info.st_ino, stat.S_IMODE(index_info.st_mode)]:
            return False
        untracked = sorted(_safe_path(path.decode("utf-8")) for path in
                           _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
                           if path and not path.startswith(b".harness/"))
        facts = [*candidate["inputs"]["tracked_worktree"], *candidate["inputs"]["untracked"],
                 *candidate["inputs"]["protected"]]
        return (_git(root, "rev-parse", "HEAD").decode().strip() == head
                and _git(root, "symbolic-ref", "-q", "HEAD").decode().strip() == candidate["full_ref"]
                and _digest(source_access.read_regular_bytes_beneath(index, root / ".git")) == candidate["index"]["sha256"]
                and untracked == [item["path"] for item in candidate["inputs"]["untracked"]]
                and all(_file_fact(root, item["path"]) == item for item in facts)
                and semantic_source_snapshot(root / ".harness") == candidate["semantic_sources"])
    except (OSError, ValueError, KeyError, CandidateRefusal, GitMutationError):
        return False


def _finish_operation(root: Path, operation: dict, candidate: dict) -> dict:
    payload = operation["payload"]
    reference = f'evidence/candidate-trace/{operation["operation_id"][7:]}.json'
    if operation["phase"] != "TRACE_PUBLISHED":
        trace = {"schema": "candidate-trace/v1", "domain": "harness:candidate-trace:v1",
                 "operation_id": operation["operation_id"], "candidate_id": payload["candidate_id"],
                 "acceptance_id": payload["acceptance_id"], "parent": payload["parent"],
                 "proposed": payload["proposed"], "historical_acceptance": True,
                 "postcheck_input_consistent": _input_consistent(root, candidate, head=payload["proposed"])}
        completed = {**operation, "phase": "TRACE_PUBLISHED"}
        _publish_documents(root, {reference: _canonical_bytes(trace),
                                  _operation_name(operation): _canonical_bytes(completed)})
    else:
        trace = _safe_json_file(root / ".harness" / reference)
        if (trace.get("operation_id") != operation["operation_id"]
                or trace.get("proposed") != payload["proposed"] or trace.get("historical_acceptance") is not True):
            raise CandidateRefusal("RECOVERY_UNSUPPORTED")
    return {"candidate": payload["candidate_id"], "operation": operation["operation_id"],
            "proposed": payload["proposed"], "trace": ".harness/" + reference, "status": "RECOVERED"}


def recover(root: Path, operation_id: str) -> dict[str, object]:
    from .transaction_recovery import (
        candidate_operations, candidate_publication_owner, recover_pending_publications,
    )
    from .git_mutation import GitMutationError, repository_policy, update_ref

    if not re_full_sha(operation_id):
        raise CandidateRefusal("RECOVERY_UNSUPPORTED")
    harness = root / ".harness"
    published = False
    try:
        with candidate_publication_owner(harness, operation_id):
            operation = next((item for item in candidate_operations(harness, allow_incomplete_trace=True)
                              if item["operation_id"] == operation_id), None)
            if operation is None:
                raise CandidateRefusal("RECOVERY_UNSUPPORTED")
            # Only explicit, known-operation recovery may settle its Harness metadata.
            # Legacy recovery remains metadata-only and never invokes this Git path.
            recover_pending_publications(harness)
            operation = next((item for item in candidate_operations(harness)
                              if item["operation_id"] == operation_id), None)
            if operation is None:
                raise CandidateRefusal("RECOVERY_UNSUPPORTED")
            task, candidate = _historical_operation(root, operation)
            payload = operation["payload"]
            current = _git(root, "rev-parse", payload["full_ref"]).decode().strip()
            if current == payload["proposed"] and operation["phase"] in {"REF_CAS_STARTED", "TRACE_PUBLISHED"}:
                published = True
                return _finish_operation(root, operation, candidate)
            if current != payload["parent"] or operation["phase"] == "TRACE_PUBLISHED":
                raise CandidateRefusal("RECOVERY_UNSUPPORTED")
            if operation["phase"] == "ABORTED_AUTHORITY_REVOKED":
                raise CandidateRefusal("USER_AUTHORITY_REQUIRED")
            grant = (task.get("authorizations") or {}).get("commit") or {}
            if grant.get("granted") is not True or grant.get('source') != 'user':
                if operation["phase"] == "PREPARED":
                    _write_operation(root, {**operation, "phase": "ABORTED_AUTHORITY_REVOKED"})
                raise CandidateRefusal("USER_AUTHORITY_REQUIRED")
            if (task.get("state") not in {"CONVERGED", "DONE"}
                    or not _input_consistent(root, candidate, head=payload["parent"])
                    or repository_policy(root) != payload["git_policy"]):
                raise CandidateRefusal("CANDIDATE_DRIFT")
            _commit_acceptance(root, candidate)
            _proof_inputs_unchanged(root, payload["candidate_id"])
            task["authorizations"]["commit"]["granted"] = False
            started = {**operation, "phase": "REF_CAS_STARTED", "mutation_started": True,
                       "grant_consumed": True}
            _write_operation(root, started, task=task)
            try:
                update_ref(root, payload["full_ref"], payload["proposed"], payload["parent"])
            except GitMutationError:
                if _git(root, "rev-parse", payload["full_ref"]).decode().strip() != payload["proposed"]:
                    raise CandidateRefusal("CANDIDATE_REF_CONFLICT")
            published = True
            return _finish_operation(root, started, candidate)
    except OSError as exc:
        code = "REF_PUBLISHED_POSTCHECK_FAILED" if published else "RECOVERY_UNSUPPORTED"
        raise CandidateRefusal(code) from exc
