"""Persist deterministic review of declared external interface contracts."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import yaml

from .interface_contract import load_interface_contract
from .workspace import git_head, snapshot

CHECKS = {"boundary", "dto", "errors", "dependency", "compatibility", "tests"}


def write_review(harness_dir: Path, source: Path, *, task_id: str) -> Path:
    try:
        review = yaml.safe_load(source.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("INTERFACE_REVIEW_INVALID") from exc
    if not isinstance(review, dict) or review.get("task") != task_id:
        raise ValueError("INTERFACE_REVIEW_TASK_INVALID")
    contracts = review.get("contracts")
    checks = review.get("checks")
    if (
        not isinstance(contracts, list)
        or not contracts
        or not isinstance(checks, dict)
        or set(checks) != CHECKS
        or any(
            value not in {"pass", "fail", "not_applicable"} for value in checks.values()
        )
    ):
        raise ValueError("INTERFACE_REVIEW_INVALID")
    for contract_id in contracts:
        load_interface_contract(harness_dir, contract_id)
    if any(value == "fail" for value in checks.values()) and not review.get(
        "proposals"
    ):
        raise ValueError("INTERFACE_FINDING_REQUIRED")
    findings_dir = harness_dir / "findings"
    existing = [item for item in findings_dir.glob("FND-*.yaml")]
    next_id = (
        max((int(item.stem.removeprefix("FND-")) for item in existing), default=0) + 1
    )
    mapping = {}
    for proposal in review.get("proposals", []):
        required = {"target", "severity", "scenario", "location"}
        if (
            not isinstance(proposal, dict)
            or required - set(proposal)
            or not isinstance(proposal["location"], dict)
        ):
            raise ValueError("INTERFACE_FINDING_INVALID")
        finding_id = f"FND-{next_id:03d}"
        next_id += 1
        finding = {
            "id": finding_id,
            "kind": "requirement_violation",
            "category": "interface",
            "target": proposal["target"],
            "scenario": proposal["scenario"],
            "severity": proposal["severity"],
            "status": "PROPOSED",
            "location": proposal["location"],
        }
        (findings_dir / f"{finding_id}.yaml").write_text(
            yaml.safe_dump(finding, sort_keys=False)
        )
        mapping[proposal.get("local_id", finding_id)] = finding_id
    current = snapshot()
    record = {
        "type": "review",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": "harness review interface",
        "exit_code": 0,
        "commit": git_head(),
        "workspace_fingerprint": current.fingerprint,
        "workspace_fingerprint_after": current.fingerprint,
        "contracts": contracts,
        "checks": checks,
        "proposals": review.get("proposals", []),
        "finding_mapping": mapping,
    }
    path = harness_dir / "evidence" / "interface-review.json"
    path.write_text(json.dumps(record, indent=2))
    return path
