"""Derived evidence of what Harness generated, not proof of Agent consumption."""

from copy import deepcopy
from datetime import datetime

from .model import ContextBuildError


def context_evidence(document: dict, integrity: dict, generated_at: str) -> dict:
    try:
        stamp = datetime.fromisoformat(generated_at)
        if stamp.tzinfo is None:
            raise ValueError("timezone required")
    except (TypeError, ValueError) as exc:
        raise ContextBuildError(
            "CONTEXT_SCHEMA_INVALID", "invalid Context Evidence timestamp"
        ) from exc
    if set(integrity) != {
        "completeness",
        "accuracy",
        "freshness",
        "traceability",
    } or not all(value is True for value in integrity.values()):
        raise ContextBuildError(
            "CONTEXT_INACCURATE", "Context Integrity has not passed"
        )
    included = {
        group: [record["id"] for record in document["control"][group]]
        + [record["id"] for record in document["working"].get(group, [])]
        for group in ("requirements", "invariants", "decisions", "findings")
    }
    return deepcopy(
        {
            "task_id": document["control"]["task"]["id"],
            "context_hash": document["context_hash"],
            "generated_at": generated_at,
            "mode": document["mode"],
            "base_policy": document["base_policy"],
            "policy": document["policy"],
            "generated_from": document["generated_from"],
            "integrity": integrity,
            "included": included,
            "omitted": document["omitted"],
            "expansions": document["expansions"],
        }
    )
