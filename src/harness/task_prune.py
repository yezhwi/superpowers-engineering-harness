"""Safe planning and explicit execution for manual task archive pruning."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ._scope_replay import SCOPE_FILES
from .transaction_recovery import publication_admission

PLAN_PREFIX = "task-prune-plan/v1:"
FILES = frozenset({"current-task.yaml", "requirements.yaml", "invariants.yaml", "gate.yaml",
                   "impact.yaml", "observability.yaml", "plan.yaml", "plan-execution.yaml",
                   "alignment.yaml", "alignment-freeze.yaml", "recovery.yaml", *SCOPE_FILES})
DIRS = frozenset({"findings", "evidence"})
CURRENT_FILES = FILES - {"recovery.yaml"}
TASK_ID = re.compile(r"TASK-[0-9]+")
ARCHIVE_NAME = re.compile(r"(?P<task>TASK-[0-9]+)-(?P<stamp>[0-9]{8}T[0-9]{12}Z)")
ANCHOR = re.compile(r"#sha256=[0-9a-f]{64}")
REQUIRED_FILES = frozenset({"current-task.yaml", "requirements.yaml", "invariants.yaml",
                            "gate.yaml", "impact.yaml", "observability.yaml", *SCOPE_FILES})
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENTS = 4096
MAX_DEPTH = 32


class PruneError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def empty_counts() -> dict[str, int]:
    return {"distinct_ids": 0, "trusted_groups": 0, "candidate_groups": 0,
            "skipped_groups": 0, "removed_entries": 0, "removed_groups": 0,
            "logical_bytes": 0}


def result(task_id: str, plan_id: str, reason: str, counts: dict[str, int], phase: str,
           mutation_started: bool, candidates: list[str] | None = None,
           blocked: list[dict[str, str]] | None = None) -> dict[str, Any]:
    value = {"task_id": task_id, "plan_id": plan_id, "reason": reason, "counts": counts,
             "phase": phase, "mutation_started": mutation_started}
    if candidates is not None:
        value["candidates"] = candidates
    if blocked is not None:
        value["blocked"] = blocked
    return value


def _utc(value: Any) -> str:
    if not isinstance(value, str):
        raise PruneError("ARCHIVE_METADATA_INVALID")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PruneError("ARCHIVE_METADATA_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PruneError("ARCHIVE_METADATA_INVALID")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PruneError("STRUCTURED_INPUT_INVALID") from exc


def _tree(path: Path, device: int) -> list[dict[str, Any]] | None:
    records = []
    try:
        children = sorted(path.rglob("*"), key=lambda child: child.relative_to(path).as_posix())
        for child in children:
            info = child.lstat()
            if info.st_dev != device or stat.S_ISLNK(info.st_mode):
                return None
            if stat.S_ISDIR(info.st_mode):
                kind, size = "dir", 0
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                kind, size = "file", info.st_size
            else:
                return None
            records.append({"path": child.relative_to(path).as_posix(), "kind": kind,
                            "dev": info.st_dev, "ino": info.st_ino,
                            "mode": stat.S_IFMT(info.st_mode), "size": size,
                            "sha256": hashlib.sha256(child.read_bytes()).hexdigest()
                            if kind == "file" else None})
    except OSError:
        return None
    return records


def _archive(path: Path, device: int) -> dict[str, Any] | None:
    try:
        root = path.lstat()
        top = {child.name: child for child in path.iterdir()}
    except OSError:
        return None
    named = ARCHIVE_NAME.fullmatch(path.name)
    if (not named or not stat.S_ISDIR(root.st_mode) or stat.S_ISLNK(root.st_mode)
            or root.st_dev != device or not REQUIRED_FILES <= top.keys()
            or not DIRS <= top.keys() or any(name not in FILES | DIRS for name in top)):
        return None
    for name, child in top.items():
        try:
            info = child.lstat()
        except OSError:
            return None
        if name in DIRS:
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                return None
        elif not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
            return None
    try:
        document = _load_yaml(path / "current-task.yaml")
        if not isinstance(document, dict) or not isinstance(document.get("task"), dict):
            return None
        task_id = document["task"]["id"]
        raw_created = document["timestamps"]["created_at"]
        created = (_utc(raw_created) if raw_created is not None else
                   dt.datetime.strptime(named["stamp"], "%Y%m%dT%H%M%S%fZ")
                   .replace(tzinfo=dt.timezone.utc).isoformat(timespec="microseconds"))
    except (KeyError, TypeError, PruneError):
        return None
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id) or named["task"] != task_id:
        return None
    recovery = path / "recovery.yaml"
    if recovery.exists():
        try:
            audit = _load_yaml(recovery)
        except PruneError:
            return None
        if (not isinstance(audit, dict) or audit.get("previous_task_id") != task_id
                or not isinstance(audit.get("reason"), str)
                or not isinstance(audit.get("previous_state"), str)
                or not isinstance(audit.get("replacement_task_id"), str)
                or not TASK_ID.fullmatch(audit["replacement_task_id"])):
            return None
        try:
            _utc(audit.get("recovered_at"))
        except PruneError:
            return None
    members = _tree(path, device)
    if members is None:
        return None
    return {"name": path.name, "task_id": task_id, "created_at": created,
            "root": {"dev": root.st_dev, "ino": root.st_ino, "mode": stat.S_IFMT(root.st_mode)},
            "members": members}


def _skipped_fact(path: Path) -> dict[str, Any]:
    """Bind skipped direct-child identity/classification without reading payloads."""
    try:
        root = path.lstat()
        members = []
        if stat.S_ISDIR(root.st_mode) and not stat.S_ISLNK(root.st_mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                info = child.lstat()
                members.append({"name": child.name, "dev": info.st_dev, "ino": info.st_ino,
                                "mode": stat.S_IFMT(info.st_mode), "size": info.st_size})
        return {"name": path.name, "dev": root.st_dev, "ino": root.st_ino,
                "mode": stat.S_IFMT(root.st_mode), "members": members}
    except OSError:
        return {"name": path.name, "unreadable": True}


def _strings(value: Any):
    stack, seen, visited = [(value, 0)], set(), 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if visited > MAX_DOCUMENTS or depth > MAX_DEPTH:
            raise PruneError("STRUCTURED_INPUT_LIMIT")
        if isinstance(item, str):
            yield item
        elif isinstance(item, (dict, list)):
            identity = id(item)
            if identity in seen:
                raise PruneError("STRUCTURED_INPUT_LIMIT")
            seen.add(identity)
            values = list(item.items()) if isinstance(item, dict) else list(enumerate(item))
            for key, child in reversed(values):
                if isinstance(item, dict):
                    stack.append((key, depth + 1))
                stack.append((child, depth + 1))


def _documents(root: Path) -> list[Path]:
    paths = []
    for name in sorted(CURRENT_FILES):
        path = root / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            if name in REQUIRED_FILES:
                raise PruneError("STRUCTURED_INPUT_MISSING")
            continue
        except OSError as exc:
            raise PruneError("STRUCTURED_INPUT_INVALID") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PruneError("STRUCTURED_INPUT_UNSAFE")
        paths.append(path)
    for name in sorted(DIRS):
        directory = root / name
        try:
            info = directory.lstat()
        except FileNotFoundError:
            raise PruneError("STRUCTURED_INPUT_MISSING")
        except OSError as exc:
            raise PruneError("STRUCTURED_INPUT_INVALID") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise PruneError("STRUCTURED_INPUT_UNSAFE")
        pending = [(directory, 0)]
        while pending:
            parent, depth = pending.pop()
            if depth > MAX_DEPTH or len(paths) > MAX_DOCUMENTS:
                raise PruneError("STRUCTURED_INPUT_LIMIT")
            try:
                children = sorted(parent.iterdir(), key=lambda item: item.name)
            except OSError as exc:
                raise PruneError("STRUCTURED_INPUT_INVALID") from exc
            for path in children:
                try:
                    child = path.lstat()
                except OSError as exc:
                    raise PruneError("STRUCTURED_INPUT_INVALID") from exc
                if stat.S_ISLNK(child.st_mode) or not (stat.S_ISREG(child.st_mode) or stat.S_ISDIR(child.st_mode)):
                    raise PruneError("STRUCTURED_INPUT_UNSAFE")
                if stat.S_ISDIR(child.st_mode):
                    pending.append((path, depth + 1))
                elif path.suffix in {".yaml", ".yml", ".json"}:
                    paths.append(path)
    return paths


def _read_document(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_DOCUMENT_BYTES:
                raise PruneError("STRUCTURED_INPUT_LIMIT")
            raw = b""
            while len(raw) <= MAX_DOCUMENT_BYTES:
                chunk = os.read(fd, min(65536, MAX_DOCUMENT_BYTES + 1 - len(raw)))
                if not chunk:
                    return raw
                raw += chunk
            raise PruneError("STRUCTURED_INPUT_LIMIT")
        finally:
            os.close(fd)
    except PruneError:
        raise
    except OSError as exc:
        raise PruneError("STRUCTURED_INPUT_INVALID") from exc


def _reference(value: str, repo: Path) -> tuple[str, str | None]:
    text = value.strip()
    if "#" in text:
        text, suffix = text.rsplit("#", 1)
        if not ANCHOR.fullmatch("#" + suffix):
            return ("ambiguous", None) if "history/" in value else ("none", None)
    prefixes = ("history/", ".harness/history/", (repo / ".harness/history").as_posix() + "/")
    prefix = next((item for item in prefixes if text.startswith(item)), None)
    if prefix is None:
        return ("ambiguous", None) if "history/" in text else ("none", None)
    parts = text[len(prefix):].split("/")
    if not parts or not parts[0] or any(part in {"", ".."} for part in parts):
        return "ambiguous", None
    normalized = PurePosixPath(*(part for part in parts if part != "."))
    return "reference", normalized.parts[0]


def _references(repo: Path, roots: list[Path], candidates: set[str]) -> tuple[str, set[str], list[dict[str, str]]]:
    found: set[str] = set()
    facts = []
    for root in roots:
        for path in _documents(root):
            try:
                raw = _read_document(path)
                value = json.loads(raw.decode()) if path.suffix == ".json" else yaml.safe_load(raw.decode())
            except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
                raise PruneError("STRUCTURED_INPUT_INVALID") from exc
            facts.append({"root": root.name, "path": path.relative_to(root).as_posix(),
                          "sha256": hashlib.sha256(raw).hexdigest()})
            for scalar in _strings(value):
                kind, name = _reference(scalar, repo)
                if kind == "ambiguous":
                    if any(candidate in scalar for candidate in candidates):
                        return "AMBIGUOUS_REFERENCE", set(), facts
                    continue
                if kind == "reference" and name in candidates:
                    found.add(name)
    return ("LIVE_REFERENCE" if found else "READY"), found, facts


def _plan(harness_dir: Path) -> dict[str, Any]:
    try:
        harness = harness_dir.resolve(strict=True)
        repo = harness.parent.resolve(strict=True)
        harness_info = harness.lstat()
        raw = _read_document(harness / "current-task.yaml")
        current = yaml.safe_load(raw)
    except PruneError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PruneError("CURRENT_TASK_INVALID") from exc
    try:
        current_id = current["task"]["id"]
        raw_created = current["timestamps"].get("created_at")
        current_created = _utc(raw_created) if raw_created is not None else None
    except (KeyError, TypeError, PruneError) as exc:
        raise PruneError("CURRENT_TASK_INVALID") from exc
    if current_id is None:
        current_id = "UNKNOWN"
    elif not isinstance(current_id, str) or not TASK_ID.fullmatch(current_id):
        raise PruneError("CURRENT_TASK_INVALID")
    history = harness / "history"
    if history.is_symlink() or (history.exists() and not history.is_dir()):
        raise PruneError("HISTORY_ROOT_INVALID")
    trusted, skipped, unsafe_ids = [], [], set()
    history_info = history.stat() if history.exists() else None
    device = history_info.st_dev if history_info else harness_info.st_dev
    children = sorted(history.iterdir(), key=lambda item: item.name) if history.exists() else []
    for child in children:
        inspected = _archive(child, device)
        if inspected:
            trusted.append(inspected)
        else:
            skipped.append(_skipped_fact(child))
            named = ARCHIVE_NAME.fullmatch(child.name)
            if named:
                unsafe_ids.add(named["task"])
    if unsafe_ids:
        retained, rejected = [], []
        for archive in trusted:
            (rejected if archive["task_id"] in unsafe_ids else retained).append(archive)
        trusted = retained
        skipped.extend({"name": item["name"], "same_id_unsafe": True} for item in rejected)
    groups: dict[str, list[dict[str, Any]]] = {}
    for archive in trusted:
        groups.setdefault(archive["task_id"], []).append(archive)
    ordered = sorted(((max(item["created_at"] for item in versions), task_id)
                      for task_id, versions in groups.items() if task_id != current_id), reverse=True)
    kept_ids = {current_id, *(task_id for _, task_id in ordered[:9])}
    distinct = {current_id, *groups}
    candidates = ([item for item in trusted if item["task_id"] not in kept_ids]
                  if len(distinct) > 10 else [])
    candidates.sort(key=lambda item: item["name"])
    names = {item["name"] for item in candidates}
    roots = [harness, *(history / item["name"] for item in trusted if item["task_id"] in kept_ids)]
    reason, referenced, reference_facts = _references(repo, roots, names)
    if reason == "AMBIGUOUS_REFERENCE":
        candidates = []
    blocked = [{"name": name, "reason": "LIVE_REFERENCE"} for name in sorted(referenced)]
    facts = {"format": "task-prune-plan/v1", "root": str(repo), "harness": str(harness),
             "root_identity": {"dev": harness_info.st_dev, "ino": harness_info.st_ino,
                               "mode": stat.S_IFMT(harness_info.st_mode)},
             "history_identity": ({"dev": history_info.st_dev, "ino": history_info.st_ino,
                                   "mode": stat.S_IFMT(history_info.st_mode)}
                                  if history_info else None),
             "current": {"task_id": current_id, "created_at": current_created,
                         "sha256": hashlib.sha256(raw).hexdigest()},
             "archives": trusted, "skipped": skipped, "kept_ids": sorted(kept_ids),
             "references": reference_facts, "reason": reason, "candidates": candidates,
             "blocked": blocked}
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    counts = empty_counts()
    counts.update(distinct_ids=len(distinct), trusted_groups=len(trusted),
                  candidate_groups=len(candidates), skipped_groups=len(skipped))
    return {"task_id": current_id, "plan_id": PLAN_PREFIX + digest, "reason": reason,
            "counts": counts, "candidates": candidates, "blocked": blocked,
            "root_identity": facts["root_identity"],
            "history_identity": ({"dev": history_info.st_dev, "ino": history_info.st_ino,
                                  "mode": stat.S_IFMT(history_info.st_mode)}
                                 if history_info else None)}


def preview(harness_dir: Path) -> dict[str, Any]:
    with publication_admission(harness_dir):
        plan = _plan(harness_dir)
    reason = "NOOP" if plan["reason"] == "READY" and not plan["candidates"] else plan["reason"]
    return result(plan["task_id"], plan["plan_id"], reason, plan["counts"], "preview", False,
                  [item["name"] for item in plan["candidates"]], plan["blocked"])


def _remove_entry(parent_fd: int, name: str, is_dir: bool) -> None:
    (os.rmdir if is_dir else os.unlink)(name, dir_fd=parent_fd)


def _delete(history_fd: int, archive: dict[str, Any], counts: dict[str, int]) -> None:
    package_fd = os.open(archive["name"], os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=history_fd)
    try:
        actual_root = os.fstat(package_fd)
        expected_root = archive["root"]
        if (actual_root.st_dev, actual_root.st_ino, stat.S_IFMT(actual_root.st_mode)) != (expected_root["dev"], expected_root["ino"], expected_root["mode"]):
            raise PruneError("IDENTITY_CHANGED")
        expected_by_path = {item["path"]: item for item in archive["members"]}
        members = sorted(archive["members"], key=lambda item: (item["path"].count("/"), item["path"]), reverse=True)
        for member in members:
            parts = member["path"].split("/")
            parent, opened = package_fd, []
            try:
                traversed = []
                for part in parts[:-1]:
                    parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
                    opened.append(parent)
                    traversed.append(part)
                    expected_parent = expected_by_path.get("/".join(traversed))
                    actual_parent = os.fstat(parent)
                    if (not expected_parent or
                            (actual_parent.st_dev, actual_parent.st_ino, stat.S_IFMT(actual_parent.st_mode)) !=
                            (expected_parent["dev"], expected_parent["ino"], expected_parent["mode"])):
                        raise PruneError("IDENTITY_CHANGED")
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)) != (member["dev"], member["ino"], member["mode"]):
                    raise PruneError("IDENTITY_CHANGED")
                if member["kind"] == "file" and info.st_nlink != 1:
                    raise PruneError("IDENTITY_CHANGED")
                if member["kind"] == "file":
                    fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
                    try:
                        opened_file = os.fstat(fd)
                        digest = hashlib.sha256()
                        actual_size = 0
                        while True:
                            chunk = os.read(fd, 65536)
                            if not chunk:
                                break
                            actual_size += len(chunk)
                            digest.update(chunk)
                        if ((opened_file.st_dev, opened_file.st_ino,
                             stat.S_IFMT(opened_file.st_mode), opened_file.st_nlink) !=
                            (member["dev"], member["ino"], member["mode"], 1)
                                or actual_size != member["size"]
                                or digest.hexdigest() != member["sha256"]):
                            raise PruneError("IDENTITY_CHANGED")
                    finally:
                        os.close(fd)
                _remove_entry(parent, parts[-1], member["kind"] == "dir")
                counts["removed_entries"] += 1
                if member["kind"] == "file":
                    counts["logical_bytes"] += actual_size
            finally:
                for fd in reversed(opened):
                    os.close(fd)
    finally:
        os.close(package_fd)
    final_root = os.stat(archive["name"], dir_fd=history_fd, follow_symlinks=False)
    expected_root = archive["root"]
    if ((final_root.st_dev, final_root.st_ino, stat.S_IFMT(final_root.st_mode)) !=
            (expected_root["dev"], expected_root["ino"], expected_root["mode"])):
        raise PruneError("IDENTITY_CHANGED")
    _remove_entry(history_fd, archive["name"], True)
    counts["removed_entries"] += 1
    counts["removed_groups"] += 1


def apply(harness_dir: Path, supplied_plan_id: str) -> dict[str, Any]:
    counts, task_id, plan_id = empty_counts(), "UNKNOWN", ""
    try:
        with publication_admission(harness_dir):
            plan = _plan(harness_dir)
            task_id, plan_id = plan["task_id"], plan["plan_id"]
            counts.update(plan["counts"])
            if not re.fullmatch(r"task-prune-plan/v1:[0-9a-f]{64}", supplied_plan_id or ""):
                return result(task_id, plan_id, "INVALID_PLAN_ID", counts, "refused", False)
            if supplied_plan_id != plan_id:
                return result(task_id, plan_id, "PLAN_MISMATCH", counts, "refused", False)
            if plan["reason"] != "READY":
                return result(task_id, plan_id, plan["reason"], counts, "refused", False)
            if not plan["candidates"]:
                return result(task_id, plan_id, "NOOP", counts, "complete", False)
            root_fd = os.open(harness_dir, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
            try:
                root_info = os.fstat(root_fd)
                expected_root = plan["root_identity"]
                if ((root_info.st_dev, root_info.st_ino, stat.S_IFMT(root_info.st_mode)) !=
                        (expected_root["dev"], expected_root["ino"], expected_root["mode"])):
                    raise PruneError("IDENTITY_CHANGED")
                history_fd = os.open("history", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
                try:
                    history_info = os.fstat(history_fd)
                    expected_history = plan["history_identity"]
                    if (not expected_history or
                            (history_info.st_dev, history_info.st_ino, stat.S_IFMT(history_info.st_mode)) !=
                            (expected_history["dev"], expected_history["ino"], expected_history["mode"])):
                        raise PruneError("IDENTITY_CHANGED")
                    for archive in plan["candidates"]:
                        _delete(history_fd, archive, counts)
                finally:
                    os.close(history_fd)
            finally:
                os.close(root_fd)
        return result(task_id, plan_id, "APPLIED", counts, "complete", counts["removed_entries"] > 0)
    except PruneError as exc:
        mutated = counts["removed_entries"] > 0
        return result(task_id, plan_id, exc.code, counts, "partial" if mutated else "refused", mutated)
    except OSError:
        mutated = counts["removed_entries"] > 0
        return result(task_id, plan_id, "DELETE_FAILED", counts, "partial" if mutated else "refused", mutated)
