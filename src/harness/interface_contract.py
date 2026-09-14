"""Schema-validated external interface contract artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.schema_resources import read_schema

from .paths import (
    EvidenceReferenceError,
    IdentifierError,
    evidence_path,
    identifier_path,
)


class InterfaceContractError(ValueError):
    """Stable external-interface contract failure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _directory(harness_dir: Path) -> Path:
    return harness_dir / "interface-contracts"


def _path(harness_dir: Path, contract_id: str) -> Path:
    try:
        return identifier_path(
            harness_dir, "interface-contracts", contract_id, r"INT-[0-9]+"
        )
    except IdentifierError as exc:
        raise InterfaceContractError("INTERFACE_CONTRACT_ID_INVALID") from exc


def _validate(record: dict) -> None:
    schema = read_schema("interface-contract.schema.json")
    try:
        validate(record, schema)
    except ValidationError as exc:
        raise InterfaceContractError("INTERFACE_CONTRACT_INVALID") from exc
    if (
        record["compatibility"]["classification"] == "breaking"
        and record["breaking_change_approved"]
        and not record["breaking_change_reason"]
    ):
        raise InterfaceContractError("INTERFACE_CONTRACT_INVALID")


def _task_id(harness_dir: Path) -> str:
    try:
        value = yaml.safe_load(source_access.read_text(harness_dir / "current-task.yaml"))["task"][
            "id"
        ]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise InterfaceContractError("INTERFACE_CONTRACT_TASK_INVALID") from exc
    if not isinstance(value, str):
        raise InterfaceContractError("INTERFACE_CONTRACT_TASK_INVALID")
    return value


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(yaml.safe_dump(record, sort_keys=False))
    temporary.replace(path)


def load_interface_contracts(harness_dir: Path) -> list[dict]:
    directory = _directory(harness_dir)
    if not source_access.is_dir(directory):
        return []
    records = []
    for path in source_access.members(directory, "INT-*.yaml"):
        try:
            record = yaml.safe_load(source_access.read_text(path))
        except (OSError, yaml.YAMLError) as exc:
            raise InterfaceContractError("INTERFACE_CONTRACT_INVALID") from exc
        if not isinstance(record, dict):
            raise InterfaceContractError("INTERFACE_CONTRACT_INVALID")
        _validate(record)
        records.append(record)
    return records


def load_interface_contract(harness_dir: Path, contract_id: str) -> dict:
    path = _path(harness_dir, contract_id)
    if not source_access.is_file(path):
        raise InterfaceContractError("INTERFACE_CONTRACT_NOT_FOUND")
    try:
        record = yaml.safe_load(source_access.read_text(path))
    except (OSError, yaml.YAMLError) as exc:
        raise InterfaceContractError("INTERFACE_CONTRACT_INVALID") from exc
    if not isinstance(record, dict):
        raise InterfaceContractError("INTERFACE_CONTRACT_INVALID")
    _validate(record)
    return record


def _next_id(harness_dir: Path) -> str:
    return f"INT-{max((int(record['id'][4:]) for record in load_interface_contracts(harness_dir)), default=0) + 1:03d}"


def declare(harness_dir: Path, document: dict) -> dict:
    record = {
        **document,
        "id": _next_id(harness_dir),
        "task_id": _task_id(harness_dir),
        "status": "DECLARED",
        "breaking_change_approved": False,
        "breaking_change_reason": None,
        "approved_at": None,
        "created_at": _now(),
    }
    _validate(record)
    _write(_path(harness_dir, record["id"]), record)
    return record


def verify(harness_dir: Path, contract_id: str, evidence: str) -> dict:
    record = load_interface_contract(harness_dir, contract_id)
    try:
        resolved = evidence_path(harness_dir, evidence)
    except EvidenceReferenceError as exc:
        raise InterfaceContractError(str(exc)) from exc
    canonical = resolved.name
    if canonical not in record["verification"]:
        record["verification"].append(canonical)
    _validate(record)
    _write(_path(harness_dir, contract_id), record)
    return record


def approve_breaking(harness_dir: Path, contract_id: str, reason: str) -> dict:
    record = load_interface_contract(harness_dir, contract_id)
    if record["compatibility"]["classification"] != "breaking" or not reason.strip():
        raise InterfaceContractError("INTERFACE_BREAKING_APPROVAL_INVALID")
    record["breaking_change_approved"] = True
    record["breaking_change_reason"] = reason
    record["approved_at"] = _now()
    _validate(record)
    _write(_path(harness_dir, contract_id), record)
    return record
