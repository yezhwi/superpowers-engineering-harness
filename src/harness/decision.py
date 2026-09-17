"""Persisted, user-owned engineering decision records."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.schema_resources import read_schema

from .paths import IdentifierError, identifier_path
from .transaction import StagedArtifact, publish, stage


class DecisionError(ValueError):
    """Stable decision-domain failure."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _directory(harness_dir: Path) -> Path:
    return harness_dir / "decisions"


def _schema() -> dict:
    return read_schema("decision.schema.json")


def _validate(record: dict) -> None:
    try:
        validate(record, _schema())
    except ValidationError as exc:
        raise DecisionError("DECISION_RECORD_INVALID") from exc
    option_ids = [option["id"] for option in record["options"]]
    if (
        len(option_ids) != len(set(option_ids))
        or record["recommendation"]["option"] not in option_ids
    ):
        raise DecisionError("DECISION_RECORD_INVALID")
    selected = record["selected"]
    if selected and selected["option"] not in option_ids:
        raise DecisionError("DECISION_RECORD_INVALID")


def _task_id(harness_dir: Path) -> str:
    try:
        task = yaml.safe_load(source_access.read_text(harness_dir / "current-task.yaml"))
        task_id = task["task"]["id"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise DecisionError("DECISION_TASK_INVALID") from exc
    if not isinstance(task_id, str):
        raise DecisionError("DECISION_TASK_INVALID")
    return task_id


def _path(harness_dir: Path, decision_id: str) -> Path:
    try:
        return identifier_path(harness_dir, "decisions", decision_id, r"DEC-[0-9]+")
    except IdentifierError as exc:
        raise DecisionError("DECISION_ID_INVALID") from exc


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(yaml.safe_dump(record, sort_keys=False))
    temporary.replace(path)


def _index_record(record: dict) -> dict:
    content = yaml.safe_dump(record, sort_keys=False).encode()
    return {
        "id": record["id"],
        "task_id": record["task_id"],
        "status": record["status"],
        "supersedes": record["supersedes"],
        "superseded_by": record["superseded_by"],
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


def _publish_records(harness_dir: Path, records: list[dict]) -> None:
    current = {record["id"]: record for record in load_decisions(harness_dir)}
    current.update({record["id"]: record for record in records})
    artifacts = [
        StagedArtifact(
            f"decisions/{record['id']}.yaml",
            yaml.safe_dump(record, sort_keys=False).encode(),
        )
        for record in records
    ]
    artifacts.append(
        StagedArtifact(
            "decisions/index.yaml",
            yaml.safe_dump(
                {"decisions": [_index_record(current[key]) for key in sorted(current)]},
                sort_keys=False,
            ).encode(),
        )
    )
    paths = frozenset(artifact.relative_path for artifact in artifacts)
    publish(harness_dir, stage(harness_dir, artifacts), replace_paths=paths)


def _next_id(harness_dir: Path) -> str:
    maximum = 0
    for record in load_decisions(harness_dir):
        maximum = max(maximum, int(record["id"].removeprefix("DEC-")))
    return f"DEC-{maximum + 1:03d}"


def reindex(harness_dir: Path) -> list[dict]:
    records = load_decisions(harness_dir)
    _publish_records(harness_dir, records)
    return load_decision_index(harness_dir)


def ensure_decision_index(harness_dir: Path) -> None:
    """Rebuild a missing index from existing members before Context capture."""
    directory = _directory(harness_dir)
    if not source_access.exists(directory):
        return
    path = directory / "index.yaml"
    if source_access.exists(path):
        return
    if source_access.members(directory, "DEC-*.yaml"):
        reindex(harness_dir)


def load_decision_index(harness_dir: Path) -> list[dict]:
    directory = _directory(harness_dir)
    if not source_access.exists(directory):
        return []
    path = directory / "index.yaml"
    if not source_access.exists(path):
        return []
    try:
        document = yaml.safe_load(source_access.read_text(path))
    except (OSError, yaml.YAMLError) as exc:
        raise DecisionError("DECISION_INDEX_INVALID") from exc
    records = document.get("decisions") if isinstance(document, dict) else None
    required = {"id", "task_id", "status", "supersedes", "superseded_by", "sha256"}
    if (
        not isinstance(records, list)
        or any(not isinstance(record, dict) or set(record) != required for record in records)
        or len({record["id"] for record in records}) != len(records)
    ):
        raise DecisionError("DECISION_INDEX_INVALID")
    members = source_access.members(_directory(harness_dir), "DEC-*.yaml")
    indexed = {record["id"]: record for record in records}
    if {path.stem for path in members} != set(indexed):
        raise DecisionError("DECISION_INDEX_INVALID")
    return records


def load_decisions(harness_dir: Path) -> list[dict]:
    directory = _directory(harness_dir)
    if not source_access.is_dir(directory):
        return []
    records: list[dict] = []
    for path in source_access.members(directory, "DEC-*.yaml"):
        try:
            record = yaml.safe_load(source_access.read_text(path))
        except (OSError, yaml.YAMLError) as exc:
            raise DecisionError("DECISION_RECORD_INVALID") from exc
        if not isinstance(record, dict):
            raise DecisionError("DECISION_RECORD_INVALID")
        _validate(record)
        records.append(record)
    return records


def load_decision(harness_dir: Path, decision_id: str) -> dict:
    path = _path(harness_dir, decision_id)
    if not source_access.is_file(path):
        raise DecisionError("DECISION_NOT_FOUND")
    try:
        record = yaml.safe_load(source_access.read_text(path))
    except (OSError, yaml.YAMLError) as exc:
        raise DecisionError("DECISION_RECORD_INVALID") from exc
    if not isinstance(record, dict):
        raise DecisionError("DECISION_RECORD_INVALID")
    _validate(record)
    return record


def _proposal_record(harness_dir: Path, document: dict) -> dict:
    if not isinstance(document, dict):
        raise DecisionError("DECISION_PROPOSAL_INVALID")
    record = {
        **document,
        "id": _next_id(harness_dir),
        "task_id": _task_id(harness_dir),
        "status": "PROPOSED",
        "selected": None,
        "created_at": _now(),
        "accepted_at": None,
        "rejected_at": None,
        "rejection_reason": None,
        "supersedes": None,
        "superseded_by": None,
    }
    _validate(record)
    return record


def propose(harness_dir: Path, document: dict) -> dict:
    record = _proposal_record(harness_dir, document)
    _publish_records(harness_dir, [record])
    return record


def accept(harness_dir: Path, decision_id: str, option: str, source: str) -> dict:
    record = load_decision(harness_dir, decision_id)
    if record["status"] != "PROPOSED" or option not in {
        item["id"] for item in record["options"]
    }:
        raise DecisionError("DECISION_ACCEPT_INVALID")
    recommended = option == record["recommendation"]["option"]
    if (recommended and source != "accepted_recommendation") or (
        not recommended and source != "user_override"
    ):
        raise DecisionError("DECISION_SELECTION_SOURCE_INVALID")
    record["status"] = "ACCEPTED"
    record["selected"] = {"option": option, "source": source, "decided_by": "user"}
    record["accepted_at"] = _now()
    record["decision_reason"] = [
        "user accepted current recommendation"
        if recommended
        else "user selected an alternative option"
    ]
    _validate(record)
    if record["supersedes"] is None:
        _publish_records(harness_dir, [record])
        return record
    original = load_decision(harness_dir, record["supersedes"])
    if original["status"] != "ACCEPTED" or original["superseded_by"] is not None:
        raise DecisionError("DECISION_SUPERSEDE_INVALID")
    original["status"] = "SUPERSEDED"
    original["superseded_by"] = record["id"]
    _validate(original)
    _publish_records(harness_dir, [original, record])
    return record


def reject(harness_dir: Path, decision_id: str, reason: str) -> dict:
    record = load_decision(harness_dir, decision_id)
    if record["status"] != "PROPOSED" or not reason.strip():
        raise DecisionError("DECISION_REJECT_INVALID")
    record["status"] = "REJECTED"
    record["rejection_reason"] = reason
    record["rejected_at"] = _now()
    _validate(record)
    _publish_records(harness_dir, [record])
    return record


def supersede(harness_dir: Path, decision_id: str, document: dict) -> tuple[dict, dict]:
    original = load_decision(harness_dir, decision_id)
    if original["status"] != "ACCEPTED" or original["superseded_by"] is not None:
        raise DecisionError("DECISION_SUPERSEDE_INVALID")
    replacement = _proposal_record(harness_dir, document)
    replacement["supersedes"] = original["id"]
    _validate(replacement)
    _publish_records(harness_dir, [replacement])
    return original, replacement


def active_decisions(harness_dir: Path) -> list[dict]:
    return [
        record
        for record in load_decisions(harness_dir)
        if record["status"] == "ACCEPTED" and record["superseded_by"] is None
    ]
