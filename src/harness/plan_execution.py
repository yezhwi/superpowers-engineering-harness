"""Pure replay and projection for task-level Plan execution journals."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

_OPTIONAL_ITEM_LISTS = (
    "requirement_refs",
    "test_case_refs",
    "invariant_refs",
    "surfaces",
)
_TERMINAL = frozenset({"COMPLETE", "SKIPPED", "SUPERSEDED"})
_ACTIVE = frozenset({"IN_PROGRESS", "BLOCKED"})
_LEGAL_TRANSITIONS = {
    ("BEGIN", "PENDING", "IN_PROGRESS"),
    ("BLOCK", "IN_PROGRESS", "BLOCKED"),
    ("RESUME", "BLOCKED", "IN_PROGRESS"),
    ("RECONCILE", "IN_PROGRESS", "COMPLETE"),
    ("RECONCILE", "IN_PROGRESS", "SKIPPED"),
    ("RECONCILE", "IN_PROGRESS", "SUPERSEDED"),
    ("REFRESH_PROOF", "COMPLETE", "COMPLETE"),
}


@dataclass(frozen=True)
class ReplayIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ReplayResult:
    items: dict[str, dict]
    active_item: str | None
    next_item: str | None
    latest_proof_receipts: dict[str, dict]
    issues: tuple[ReplayIssue, ...]


class PlanExecutionError(ValueError):
    """A proposed pure execution transition cannot be replayed."""


def semantic_plan_fingerprint(plan: dict) -> str:
    """Return semantic Plan digest without execution state or presentation."""
    items = []
    for item in plan["items"]:
        normalized = {"id": item["id"], "intent": item["intent"]}
        normalized.update({name: item.get(name, []) for name in _OPTIONAL_ITEM_LISTS})
        items.append(normalized)
    payload = json.dumps(
        {"version": plan["version"], "items": items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _failure(code: str, message: str) -> ReplayResult:
    return ReplayResult({}, None, None, {}, (ReplayIssue(code, message),))


def _status(items: dict[str, dict], item_id: str) -> str:
    return items.get(item_id, {}).get("status", "PENDING")


def _active_item(items: dict[str, dict]) -> str | None:
    active = [item_id for item_id, record in items.items() if record["status"] in _ACTIVE]
    return active[0] if len(active) == 1 else None


def _next_item(plan_ids: list[str], items: dict[str, dict]) -> str | None:
    return next(
        (item_id for item_id in plan_ids if _status(items, item_id) not in _TERMINAL),
        None,
    )


def _proof_issue(transition: dict) -> ReplayIssue | None:
    receipt = transition.get("proof_receipt")
    if not isinstance(receipt, dict):
        return ReplayIssue("RECEIPT_INVALID", "proof transition lacks receipt")
    evidence = receipt.get("evidence")
    evidence_refs = transition.get("evidence_refs")
    surface_refs = transition.get("surface_refs")
    if not isinstance(evidence, list) or not isinstance(evidence_refs, list):
        return ReplayIssue("RECEIPT_INVALID", "proof evidence references are malformed")
    if [record.get("ref") for record in evidence if isinstance(record, dict)] != evidence_refs:
        return ReplayIssue("RECEIPT_MISMATCH", "proof receipt evidence differs from transition")
    if receipt.get("surface_refs") != surface_refs:
        return ReplayIssue("RECEIPT_MISMATCH", "proof receipt surfaces differ from transition")
    for record in evidence:
        if not isinstance(record, dict):
            return ReplayIssue("RECEIPT_INVALID", "proof evidence receipt is malformed")
        if record.get("exit_code") != 0:
            return ReplayIssue("RECEIPT_MISMATCH", "proof evidence was not successful")
        if record.get("commit") != receipt.get("head"):
            return ReplayIssue("RECEIPT_MISMATCH", "proof evidence head differs from receipt")
        if record.get("workspace_fingerprint") != receipt.get("workspace"):
            return ReplayIssue(
                "RECEIPT_MISMATCH",
                "proof evidence workspace differs from receipt",
            )
    return None


def _decision_issue(transition: dict) -> ReplayIssue | None:
    receipt = transition.get("decision_receipt")
    if not isinstance(receipt, dict):
        return ReplayIssue("RECEIPT_INVALID", "disposition lacks Decision receipt")
    if receipt.get("decision_id") != transition.get("decision_id"):
        return ReplayIssue("RECEIPT_MISMATCH", "Decision receipt differs from transition")
    if receipt.get("status") != "ACCEPTED":
        return ReplayIssue("RECEIPT_MISMATCH", "Decision receipt was not accepted")
    return None


def _project_transition(items: dict[str, dict], transition: dict) -> None:
    item_id = transition["item"]
    action = transition["action"]
    target = transition["to"]
    if action == "BEGIN":
        items[item_id] = {"status": "IN_PROGRESS"}
    elif action == "BLOCK":
        items[item_id] = {"status": "BLOCKED", "reason": transition["reason"]}
    elif action == "RESUME":
        items[item_id] = {"status": "IN_PROGRESS"}
    elif target == "COMPLETE":
        record = {"status": "COMPLETE"}
        for field in ("evidence_refs", "surface_refs"):
            if transition[field]:
                record[field] = deepcopy(transition[field])
        items[item_id] = record
    elif target == "SKIPPED":
        items[item_id] = {
            "status": "SKIPPED",
            "reason": transition["reason"],
            "decision_id": transition["decision_id"],
        }
    elif target == "SUPERSEDED":
        items[item_id] = {
            "status": "SUPERSEDED",
            "reason": transition["reason"],
            "decision_id": transition["decision_id"],
            "superseded_by": deepcopy(transition["superseded_by"]),
        }


def replay_plan_execution(plan: dict, execution: dict) -> ReplayResult:
    """Replay schema-valid execution v2 without reading current external facts."""
    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("items"), list)
        or not isinstance(execution, dict)
        or execution.get("version") != 2
        or not isinstance(execution.get("plan"), dict)
        or not isinstance(execution.get("transitions"), list)
        or not isinstance(execution.get("items"), dict)
    ):
        return _failure("STRUCTURE_INVALID", "execution v2 structure is invalid")

    try:
        expected_fingerprint = semantic_plan_fingerprint(plan)
    except (KeyError, TypeError):
        return _failure("STRUCTURE_INVALID", "plan structure is invalid")
    if execution["plan"].get("fingerprint") != expected_fingerprint:
        return _failure("FINGERPRINT_MISMATCH", "execution fingerprint differs from plan")

    transitions = execution["transitions"]
    if execution.get("sequence") != len(transitions):
        return _failure("SEQUENCE_COUNT_MISMATCH", "sequence differs from journal length")
    if any(
        not isinstance(transition, dict)
        or transition.get("sequence") != index
        for index, transition in enumerate(transitions, 1)
    ):
        return _failure("SEQUENCE_NONCONTIGUOUS", "transition sequence is not contiguous")

    plan_ids = [item.get("id") for item in plan["items"]]
    if any(not isinstance(item_id, str) for item_id in plan_ids):
        return _failure("STRUCTURE_INVALID", "plan item identity is invalid")
    plan_id_set = set(plan_ids)
    items: dict[str, dict] = {}
    latest_receipts: dict[str, dict] = {}

    for transition in transitions:
        item_id = transition.get("item")
        if item_id not in plan_id_set:
            return _failure("ITEM_UNKNOWN", f"transition item is absent from plan: {item_id}")

        current = _status(items, item_id)
        if transition.get("from") != current:
            return _failure(
                "FROM_MISMATCH",
                f"transition from {transition.get('from')} does not match {current}",
            )

        relationship = (
            transition.get("action"),
            transition.get("from"),
            transition.get("to"),
        )
        if relationship not in _LEGAL_TRANSITIONS:
            return _failure("LIFECYCLE_INVALID", "transition lifecycle is not legal")

        if transition["action"] == "BEGIN":
            expected_item = _next_item(plan_ids, items)
            if item_id != expected_item:
                return _failure(
                    "BEGIN_ORDER_INVALID",
                    f"BEGIN target {item_id} is not canonical next item {expected_item}",
                )

        if transition["action"] in {"RECONCILE", "REFRESH_PROOF"} and transition["to"] == "COMPLETE":
            if issue := _proof_issue(transition):
                return ReplayResult({}, None, None, {}, (issue,))
        if transition["to"] in {"SKIPPED", "SUPERSEDED"}:
            if issue := _decision_issue(transition):
                return ReplayResult({}, None, None, {}, (issue,))

        _project_transition(items, transition)
        active = [
            candidate
            for candidate, record in items.items()
            if record["status"] in _ACTIVE
        ]
        if len(active) > 1:
            return _failure("MULTIPLE_ACTIVE_ITEMS", "more than one item is active")

        if transition["to"] == "COMPLETE" and "proof_receipt" in transition:
            latest_receipts[item_id] = deepcopy(transition["proof_receipt"])

    if items != execution["items"]:
        return _failure("PROJECTION_MISMATCH", "journal replay differs from persisted items")

    return ReplayResult(
        deepcopy(items),
        _active_item(items),
        _next_item(plan_ids, items),
        deepcopy(latest_receipts),
        (),
    )


def append_plan_transition(plan: dict, execution: dict, transition: dict) -> dict:
    """Return execution with one contiguous transition and replay-derived items."""
    current = replay_plan_execution(plan, execution)
    if current.issues:
        raise PlanExecutionError(current.issues[0].code)

    candidate = deepcopy(execution)
    event = deepcopy(transition)
    event["sequence"] = execution["sequence"] + 1
    candidate["sequence"] = event["sequence"]
    candidate["transitions"].append(event)
    candidate["items"] = deepcopy(current.items)
    try:
        _project_transition(candidate["items"], event)
    except (KeyError, TypeError) as exc:
        raise PlanExecutionError("STRUCTURE_INVALID") from exc

    replayed = replay_plan_execution(plan, candidate)
    if replayed.issues:
        raise PlanExecutionError(replayed.issues[0].code)
    candidate["items"] = replayed.items
    return candidate
