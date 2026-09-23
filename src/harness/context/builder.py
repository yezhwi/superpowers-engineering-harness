"""Deterministic, lossless Layer 0 projection. No relevance selection or writes."""

from copy import deepcopy

from harness import impact as impact_domain

from harness.blockers import blocker_document
from harness.quality_gate import OPEN_FINDING_STATUSES

from .model import AuthoritativeContext, ControlCore


def layer0_decisions(records: list[dict], task_id: str) -> list[dict]:
    """ACCEPTED decisions owned by the current task; no historical inlining."""
    return [
        record
        for record in records
        if record.get("status") == "ACCEPTED" and record.get("task_id") == task_id
    ]


def cross_task_decision_ids(records: list[dict], task_id: str) -> set[str]:
    """Decision ids the current task explicitly supersedes or is superseded by."""
    owned = {
        record["id"] for record in records if record.get("task_id") == task_id
    }
    referenced: set[str] = set()
    for record in records:
        if record.get("task_id") != task_id:
            continue
        for field in ("supersedes", "superseded_by"):
            value = record.get(field)
            if isinstance(value, str) and value and value not in owned:
                referenced.add(value)
    return referenced


def _alignment_summary(source: AuthoritativeContext) -> dict | None:
    """Layer 0 keeps the freeze pointer; the envelope is omitted separately."""
    if source.alignment is None:
        return None
    summary = {
        **source.references["alignment.yaml"],
        "frozen": source.alignment["freeze"]["frozen"],
        "contract_hash": source.alignment["freeze"]["contract_hash"],
    }
    seal = source.references.get("alignment-freeze.yaml")
    if seal:
        summary["seal"] = seal
    return summary


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
        {"contract_ref": record["ref"], "kind": record["kind"], **source.references["impact.yaml"]}
        for record in impact_domain.typed_contracts(
            (source.impact or {}).get("impact", {})
        )
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
            "decisions": layer0_decisions(source.decisions, task["task"]["id"]),
            "findings": [
                r for r in source.findings if r["status"] in OPEN_FINDING_STATUSES
            ],
            "blockers": blockers,
            "scope": task.get("scope"),
            "authorizations": task.get("authorizations"),
            "constraints": task["risk"]["dimensions"],
            "contracts": {"interfaces": interfaces, "impact": impact_contracts},
            "observability": observability,
            "alignment": _alignment_summary(source),
            "evidence": source.evidence,
            "gate": {"status": source.gate.status, "blocked_by": blockers},
        }
    )
