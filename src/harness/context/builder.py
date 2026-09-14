"""Deterministic, lossless Layer 0 projection. No relevance selection or writes."""

from copy import deepcopy

from harness.blockers import blocker_document
from harness.quality_gate import OPEN_FINDING_STATUSES

from .model import AuthoritativeContext, ControlCore


def build_control_core(source: AuthoritativeContext) -> ControlCore:
    """Project validated source records; final Context Integrity is a later step.

    Non-MUST requirements and terminal records remain in ``source`` for later
    Working Set / omission accounting. Never mutate or alias authoritative data.
    """
    task = source.task
    blockers = [blocker_document(blocker) for blocker in source.gate.blockers]
    interfaces = [
        {
            "id": record["id"],
            **source.references[f"interface-contracts/{record['id']}.yaml"],
        }
        for record in source.interface_contracts
    ]
    impact_contracts = [
        {"path": path, **source.references["impact.yaml"]}
        for path in (source.impact or {}).get("impact", {}).get("contracts", [])
    ]
    observability = None
    if source.observability is not None:
        observability = {
            "required": source.observability["required"],
            "applicability": {
                **source.references["observability.yaml"],
                "section": "applicability",
            },
        }
    return deepcopy(
        {
            "task": {
                "id": task["task"]["id"],
                "state": task["state"],
                "risk": task["risk"],
            },
            "requirements": [r for r in source.requirements if r["priority"] == "must"],
            "invariants": source.invariants,
            "decisions": [r for r in source.decisions if r["status"] == "ACCEPTED"],
            "findings": [
                r for r in source.findings if r["status"] in OPEN_FINDING_STATUSES
            ],
            "blockers": blockers,
            "scope": task.get("scope"),
            "authorizations": task.get("authorizations"),
            "constraints": task["risk"]["dimensions"],
            "contracts": {"interfaces": interfaces, "impact": impact_contracts},
            "observability": observability,
            "evidence": source.evidence,
            "gate": {"status": source.gate.status, "blocked_by": blockers},
        }
    )
