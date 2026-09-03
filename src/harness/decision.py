"""Persisted, user-owned engineering decision records."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from importlib import resources

import yaml
from jsonschema import ValidationError, validate

from .transaction import StagedArtifact, publish, stage


class DecisionError(ValueError):
    """Stable decision-domain failure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _directory(harness_dir: Path) -> Path:
    return harness_dir / "decisions"


def _schema() -> dict:
    return json.loads(resources.files("harness").joinpath("schemas/decision.schema.json").read_text())


def _validate(record: dict) -> None:
    try:
        validate(record, _schema())
    except ValidationError as exc:
        raise DecisionError("DECISION_RECORD_INVALID") from exc
    option_ids = [option["id"] for option in record["options"]]
    if len(option_ids) != len(set(option_ids)) or record["recommendation"]["option"] not in option_ids:
        raise DecisionError("DECISION_RECORD_INVALID")
    selected = record["selected"]
    if selected and selected["option"] not in option_ids:
        raise DecisionError("DECISION_RECORD_INVALID")


def _task_id(harness_dir: Path) -> str:
    try:
        task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
        task_id = task["task"]["id"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise DecisionError("DECISION_TASK_INVALID") from exc
    if not isinstance(task_id, str):
        raise DecisionError("DECISION_TASK_INVALID")
    return task_id


def _path(harness_dir: Path, decision_id: str) -> Path:
    if not decision_id.startswith("DEC-"):
        raise DecisionError("DECISION_ID_INVALID")
    return _directory(harness_dir) / f"{decision_id}.yaml"


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(yaml.safe_dump(record, sort_keys=False))
    temporary.replace(path)


def _next_id(harness_dir: Path) -> str:
    maximum = 0
    for record in load_decisions(harness_dir):
        maximum = max(maximum, int(record["id"].removeprefix("DEC-")))
    return f"DEC-{maximum + 1:03d}"


def load_decisions(harness_dir: Path) -> list[dict]:
    directory = _directory(harness_dir)
    if not directory.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(directory.glob("DEC-*.yaml")):
        try:
            record = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise DecisionError("DECISION_RECORD_INVALID") from exc
        if not isinstance(record, dict):
            raise DecisionError("DECISION_RECORD_INVALID")
        _validate(record)
        records.append(record)
    return records


def load_decision(harness_dir: Path, decision_id: str) -> dict:
    path = _path(harness_dir, decision_id)
    if not path.is_file():
        raise DecisionError("DECISION_NOT_FOUND")
    try:
        record = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise DecisionError("DECISION_RECORD_INVALID") from exc
    if not isinstance(record, dict):
        raise DecisionError("DECISION_RECORD_INVALID")
    _validate(record)
    return record


def _proposal_record(harness_dir: Path, document: dict) -> dict:
    if not isinstance(document, dict):
        raise DecisionError("DECISION_PROPOSAL_INVALID")
    record = {**document, "id": _next_id(harness_dir), "task_id": _task_id(harness_dir),
              "status": "PROPOSED", "selected": None, "created_at": _now(),
              "accepted_at": None, "rejected_at": None, "rejection_reason": None,
              "supersedes": None, "superseded_by": None}
    _validate(record)
    return record


def propose(harness_dir: Path, document: dict) -> dict:
    record = _proposal_record(harness_dir, document)
    _write(_path(harness_dir, record["id"]), record)
    return record


def accept(harness_dir: Path, decision_id: str, option: str, source: str) -> dict:
    record = load_decision(harness_dir, decision_id)
    if record["status"] != "PROPOSED" or option not in {item["id"] for item in record["options"]}:
        raise DecisionError("DECISION_ACCEPT_INVALID")
    recommended = option == record["recommendation"]["option"]
    if (recommended and source != "accepted_recommendation") or (not recommended and source != "user_override"):
        raise DecisionError("DECISION_SELECTION_SOURCE_INVALID")
    record["status"] = "ACCEPTED"
    record["selected"] = {"option": option, "source": source, "decided_by": "user"}
    record["accepted_at"] = _now()
    record["decision_reason"] = ["user accepted current recommendation" if recommended else "user selected an alternative option"]
    _validate(record)
    _write(_path(harness_dir, decision_id), record)
    return record


def reject(harness_dir: Path, decision_id: str, reason: str) -> dict:
    record = load_decision(harness_dir, decision_id)
    if record["status"] != "PROPOSED" or not reason.strip():
        raise DecisionError("DECISION_REJECT_INVALID")
    record["status"] = "REJECTED"
    record["rejection_reason"] = reason
    record["rejected_at"] = _now()
    _validate(record)
    _write(_path(harness_dir, decision_id), record)
    return record


def supersede(harness_dir: Path, decision_id: str, document: dict) -> tuple[dict, dict]:
    original = load_decision(harness_dir, decision_id)
    if original["status"] != "ACCEPTED" or original["superseded_by"] is not None:
        raise DecisionError("DECISION_SUPERSEDE_INVALID")
    replacement = _proposal_record(harness_dir, document)
    replacement["supersedes"] = original["id"]
    original["status"] = "SUPERSEDED"
    original["superseded_by"] = replacement["id"]
    _validate(original)
    _validate(replacement)
    artifacts = [
        StagedArtifact(f"decisions/{original['id']}.yaml", yaml.safe_dump(original, sort_keys=False).encode()),
        StagedArtifact(f"decisions/{replacement['id']}.yaml", yaml.safe_dump(replacement, sort_keys=False).encode()),
    ]
    publish(harness_dir, stage(harness_dir, artifacts), replace_paths=frozenset({f"decisions/{original['id']}.yaml"}))
    return original, replacement


def active_decisions(harness_dir: Path) -> list[dict]:
    return [record for record in load_decisions(harness_dir) if record["status"] == "ACCEPTED" and record["superseded_by"] is None]
