"""Validated, reference-only Alignment contract artifacts."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from harness import source_access, transaction
from harness.schema_resources import read_schema


class AlignmentError(ValueError):
    """Stable alignment-domain error."""


@dataclass(frozen=True)
class AlignmentIssue:
    code: str
    subject_id: str | None = None


def _validate(document: dict) -> None:
    try:
        validate(document, read_schema("alignment.schema.json"))
    except ValidationError as exc:
        raise AlignmentError("ALIGNMENT_INVALID") from exc


def load_alignment(harness_dir: Path) -> dict:
    """Load and validate one thin Alignment envelope without mutating it."""
    try:
        document = yaml.safe_load(source_access.read_text(harness_dir / "alignment.yaml"))
    except (OSError, yaml.YAMLError) as exc:
        raise AlignmentError("ALIGNMENT_INVALID") from exc
    if not isinstance(document, dict):
        raise AlignmentError("ALIGNMENT_INVALID")
    _validate(document)
    return document


def contract_hash(document: dict) -> str:
    """Return SHA-256 for frozen intent fields, excluding implementation detail."""
    _validate(document)
    projection = {
        "goal": document["goal"],
        "scope": document["scope"],
        "non_goals": document["non_goals"],
        "boundaries": document["boundaries"],
        "constraints": document["constraints"],
        "assumptions": document["assumptions"],
        "acceptance_criteria": document["acceptance_criteria"],
        "verification": [
            {
                "id": record["id"],
                "acceptance_criteria": record["acceptance_criteria"],
                "method": record["method"],
                "expected_evidence": record["expected_evidence"],
            }
            for record in document["verification"]
        ],
        "decision_ids": document["decision_ids"],
        "interface_contract_ids": document["interface_contract_ids"],
    }
    encoded = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def classify_scope_drift(
    *,
    frozen_hash: str,
    current_hash: str,
    external_interface_changed: bool,
    permission_boundary_changed: bool,
    persistence_boundary_changed: bool,
) -> list[AlignmentIssue]:
    """Classify only declared contract/interface facts; never inspect code semantics."""
    issues = []
    if frozen_hash != current_hash:
        issues.append(AlignmentIssue("CONTRACT_CHANGED"))
    if external_interface_changed:
        issues.append(AlignmentIssue("SCOPE_DRIFT_API"))
    if permission_boundary_changed:
        issues.append(AlignmentIssue("SCOPE_DRIFT_PERMISSION"))
    if persistence_boundary_changed:
        issues.append(AlignmentIssue("SCOPE_DRIFT_PERSISTENCE"))
    return issues


def freeze_record(
    document: dict, *, decisions: list[dict], boundary_refs: dict
) -> dict:
    """Project current frozen Alignment facts into its immutable seal."""
    selections = {
        item["id"]: item["selected"]["option"]
        for item in decisions
        if item.get("status") == "ACCEPTED"
        and item.get("selected")
        and item["id"] in document["decision_ids"]
    }
    return {
        "version": 1,
        "task_id": document["task_id"],
        "contract_hash": contract_hash(document),
        "decision_selections": selections,
        "boundary_refs": boundary_refs,
        "frozen_at": document["freeze"]["frozen_at"],
    }


def sealed_freeze_drift(
    harness_dir: Path,
    document: dict,
    *,
    decisions: list[dict],
    boundary_refs: dict,
    bootstrap: bool = True,
) -> list[AlignmentIssue]:
    """Bootstrap legacy freeze once; classify immutable baseline changes.

    Read-only callers pass ``bootstrap=False`` so a missing seal is drift
    instead of a new baseline written during inspection.
    """
    validate_freeze(document)
    record = freeze_record(
        document, decisions=decisions, boundary_refs=boundary_refs
    )
    try:
        validate(record, read_schema("alignment-freeze.schema.json"))
    except ValidationError as exc:
        raise AlignmentError("ALIGNMENT_FREEZE_INVALID") from exc
    path = harness_dir / "alignment-freeze.yaml"
    if not path.exists():
        if not bootstrap:
            return [AlignmentIssue("CONTRACT_CHANGED")]
        transaction.atomic_write(path, yaml.safe_dump(record, sort_keys=False).encode())
        return []
    try:
        actual = yaml.safe_load(source_access.read_text(path))
        validate(actual, read_schema("alignment-freeze.schema.json"))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise AlignmentError("ALIGNMENT_FREEZE_INVALID") from exc
    if any(actual[key] != record[key] for key in ("task_id", "contract_hash", "decision_selections")):
        return [AlignmentIssue("CONTRACT_CHANGED")]
    codes = {"interface": "SCOPE_DRIFT_API", "permission": "SCOPE_DRIFT_PERMISSION", "persistence": "SCOPE_DRIFT_PERSISTENCE"}
    return [AlignmentIssue(codes[kind], ref) for kind in codes for ref in sorted(set(actual["boundary_refs"][kind]) ^ set(boundary_refs[kind]))]


def validate_sealed_freeze(harness_dir: Path, document: dict, *, decisions: list[dict], boundary_refs: dict) -> None:
    issues = sealed_freeze_drift(harness_dir, document, decisions=decisions, boundary_refs=boundary_refs)
    if issues:
        raise AlignmentError(issues[0].code)


def validate_freeze(document: dict) -> None:
    """Reject an unfrozen, malformed, or stale contract freeze without mutation."""
    _validate(document)
    freeze = document["freeze"]
    if (
        not freeze["frozen"]
        or not freeze["frozen_at"]
        or freeze["contract_hash"] != contract_hash(document)
    ):
        raise AlignmentError("ALIGNMENT_FREEZE_INVALID")


def check_completeness(
    document: dict,
    *,
    requirement_ids: set[str],
    critical_requirement_ids: set[str] = frozenset(),
    proposed_decision_ids: set[str] = frozenset(),
) -> list[AlignmentIssue]:
    """Return ordered Intent Closure diagnostics for one validated envelope."""
    _validate(document)
    issues: list[AlignmentIssue] = []

    if not document["goal"]["summary"].strip():
        issues.append(AlignmentIssue("ALIGNMENT_GOAL_MISSING"))
    if not document["scope"]["in"] or not document["scope"]["out"]:
        issues.append(AlignmentIssue("ALIGNMENT_SCOPE_MISSING"))
    issues.extend(
        AlignmentIssue("OPEN_DECISION", decision_id)
        for decision_id in sorted(
            set(document["open_decisions"]) | set(proposed_decision_ids)
        )
    )
    issues.extend(
        AlignmentIssue("OPEN_LOOP", loop_id)
        for loop_id in sorted(document["open_loops"])
    )

    acceptance_criteria = document["acceptance_criteria"]
    ac_by_id = {record["id"]: record for record in acceptance_criteria}
    requirements_with_ac = {
        requirement_id
        for record in acceptance_criteria
        for requirement_id in record["requirement_ids"]
    }
    issues.extend(
        AlignmentIssue("REQ_WITHOUT_AC", requirement_id)
        for requirement_id in sorted(requirement_ids - requirements_with_ac)
    )
    issues.extend(
        AlignmentIssue("AC_WITHOUT_REQ", ac_id)
        for ac_id, record in sorted(ac_by_id.items())
        if not record["requirement_ids"]
    )

    verified_ac_ids = {
        ac_id
        for record in document["verification"]
        for ac_id in record["acceptance_criteria"]
    }
    issues.extend(
        AlignmentIssue("AC_WITHOUT_VERIFICATION", ac_id)
        for ac_id in sorted(ac_by_id)
        if ac_id not in verified_ac_ids
    )
    issues.extend(
        AlignmentIssue("VERIFICATION_EXPECTED_EVIDENCE_MISSING", record["id"])
        for record in sorted(document["verification"], key=lambda item: item["id"])
        if not record["expected_evidence"].strip()
    )

    surfaced_ac_ids = {
        ac_id
        for record in document["implementation_surfaces"]
        for ac_id in record["acceptance_criteria"]
    }
    for requirement_id in sorted(critical_requirement_ids):
        ac_ids = {
            record["id"]
            for record in acceptance_criteria
            if requirement_id in record["requirement_ids"]
        }
        if not ac_ids or not ac_ids & surfaced_ac_ids:
            issues.append(AlignmentIssue("CRITICAL_REQ_WITHOUT_SURFACE", requirement_id))

    return issues
