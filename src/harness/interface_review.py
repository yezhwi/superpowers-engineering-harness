"""Persist deterministic review of declared external interface contracts."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import yaml

from .interface_contract import load_interface_contract
from .transaction import StagedArtifact, publish, stage
from .workspace import git_head, snapshot

CHECKS = {"boundary", "dto", "errors", "dependency", "compatibility", "tests"}


def _load_existing_findings(findings_dir: Path) -> list[dict]:
    findings = []
    for path in sorted(findings_dir.glob("FND-*.yaml")):
        try:
            finding = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("INTERFACE_FINDING_INVALID") from exc
        if not isinstance(finding, dict):
            raise ValueError("INTERFACE_FINDING_INVALID")
        findings.append(finding)
    return findings


def _equivalent(finding: dict, proposal: dict) -> bool:
    return finding.get("category") == "interface" and all(
        finding.get(key) == proposal.get(key)
        for key in ("target", "severity", "scenario", "location")
    )


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

    existing = _load_existing_findings(harness_dir / "findings")
    next_id = max(
        (int(str(item.get("id", "")).removeprefix("FND-")) for item in existing),
        default=0,
    ) + 1
    generated = []
    mapping = {}
    for proposal in review.get("proposals", []):
        required = {"target", "severity", "scenario", "location"}
        if (
            not isinstance(proposal, dict)
            or required - set(proposal)
            or not isinstance(proposal["location"], dict)
        ):
            raise ValueError("INTERFACE_FINDING_INVALID")
        match = next(
            (finding for finding in existing if _equivalent(finding, proposal)), None
        )
        local_id = proposal.get("local_id")
        if match:
            mapping[local_id or match["id"]] = match["id"]
            continue
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
        generated.append(finding)
        existing.append(finding)
        mapping[local_id or finding_id] = finding_id

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
    artifacts = [
        StagedArtifact(
            f"findings/{finding['id']}.yaml",
            yaml.safe_dump(finding, sort_keys=False).encode(),
        )
        for finding in generated
    ]
    artifacts.append(
        StagedArtifact(
            "evidence/interface-review.json",
            json.dumps(record, indent=2).encode(),
            replace=True,
        )
    )
    publish(
        harness_dir,
        stage(harness_dir, artifacts),
        replace_paths=frozenset({"evidence/interface-review.json"}),
    )
    return harness_dir / "evidence" / "interface-review.json"
