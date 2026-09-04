"""Schema-validated external interface contract artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
import json
from pathlib import Path

import yaml

from .paths import EvidenceReferenceError, evidence_path
from jsonschema import ValidationError, validate


class InterfaceContractError(ValueError):
    """Stable external-interface contract failure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _directory(harness_dir: Path) -> Path:
    return harness_dir / "interface-contracts"


def _path(harness_dir: Path, contract_id: str) -> Path:
    if not contract_id.startswith("INT-"):
        raise InterfaceContractError("INTERFACE_CONTRACT_ID_INVALID")
    return _directory(harness_dir) / f"{contract_id}.yaml"


def _validate(record: dict) -> None:
    schema = json.loads(
        resources.files("harness")
        .joinpath("schemas/interface-contract.schema.json")
        .read_text()
    )
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
        value = yaml.safe_load((harness_dir / "current-task.yaml").read_text())["task"][
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
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("INT-*.yaml")):
        try:
            record = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise InterfaceContractError("INTERFACE_CONTRACT_INVALID") from exc
        if not isinstance(record, dict):
            raise InterfaceContractError("INTERFACE_CONTRACT_INVALID")
        _validate(record)
        records.append(record)
    return records


def load_interface_contract(harness_dir: Path, contract_id: str) -> dict:
    path = _path(harness_dir, contract_id)
    if not path.is_file():
        raise InterfaceContractError("INTERFACE_CONTRACT_NOT_FOUND")
    try:
        record = yaml.safe_load(path.read_text())
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
