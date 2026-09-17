"""Audit already-implemented work without forging RED proof or tracker writes."""

from __future__ import annotations

import json
from pathlib import Path

from .evidence_validator import EvidenceValidationError, validate_evidence
from .quality_gate import fast_verification_policy
from .risk_boundaries import business_paths
from .workspace import (
    WorkspaceError,
    introducing_commit,
    name_only_diff,
    snapshot,
    verify_git_ref,
)

ALLOWED_STATES = frozenset({"CLASSIFIED", "PLANNED"})
CONCLUSIONS = frozenset(
    {"already_satisfied", "duplicate_request", "requires_reproduction"}
)


class ExistingVerificationError(ValueError):
    pass


def _fail(code: str) -> None:
    raise ExistingVerificationError(code)


def target_paths(task: dict) -> tuple[str, ...]:
    owned = tuple((task.get("scope") or {}).get("owned_paths") or ())
    if owned:
        return owned
    return business_paths(snapshot().changed_paths)


def require_green_evidence(harness_dir: Path) -> None:
    from harness import source_access

    current = snapshot()
    required = [
        name
        for name, policy in fast_verification_policy(harness_dir).items()
        if policy == "required"
    ]
    for name in required:
        path = harness_dir / "evidence" / f"{name.replace('_', '-')}.json"
        try:
            record = json.loads(source_access.read_text(path))
            validate_evidence(
                record,
                current_head=current.head,
                current_workspace=current.fingerprint,
                expected_success=True,
            )
        except (OSError, json.JSONDecodeError, EvidenceValidationError):
            _fail("EXISTING_VERIFICATION_GREEN_MISSING")
    unit_ok = False
    for name in ("fast-green-unit-test.json", "unit-test.json"):
        path = harness_dir / "evidence" / name
        if not source_access.is_file(path):
            continue
        try:
            record = json.loads(source_access.read_text(path))
            validate_evidence(
                record,
                current_head=current.head,
                current_workspace=current.fingerprint,
                expected_success=True,
            )
        except (OSError, json.JSONDecodeError, EvidenceValidationError):
            continue
        if record.get("type") == "unit_test":
            unit_ok = True
            break
    if not unit_ok:
        _fail("EXISTING_VERIFICATION_GREEN_MISSING")


def verify_existing(
    task: dict,
    harness_dir: Path,
    *,
    reference: str,
    reason: str,
    conclusion: str,
    accept_diff: str | None = None,
    untraceable_reason: str | None = None,
) -> dict:
    if task.get("state") not in ALLOWED_STATES:
        _fail("EXISTING_VERIFICATION_STATE_INVALID")
    if conclusion not in CONCLUSIONS:
        _fail("EXISTING_VERIFICATION_CONCLUSION_INVALID")
    if not isinstance(reason, str) or not reason.strip():
        _fail("EXISTING_VERIFICATION_REASON_REQUIRED")
    if conclusion == "requires_reproduction":
        _fail("EXISTING_VERIFICATION_REQUIRES_REPRODUCTION")
    try:
        resolved = verify_git_ref(reference)
    except WorkspaceError:
        _fail("EXISTING_VERIFICATION_REFERENCE_INVALID")
    paths = target_paths(task)
    try:
        changed = name_only_diff(reference, paths)
    except WorkspaceError as exc:
        _fail(str(exc).split(":", 1)[0] or "EXISTING_VERIFICATION_REFERENCE_INVALID")
    accepted_diff = (accept_diff or "").strip() or None
    if changed and not accepted_diff:
        _fail("EXISTING_VERIFICATION_DIFF_UNACCEPTED")
    require_green_evidence(harness_dir)
    provenance = None
    if paths:
        try:
            provenance = introducing_commit(reference, paths)
        except WorkspaceError:
            provenance = None
    untraceable = (untraceable_reason or "").strip() or None
    if provenance is None and not untraceable:
        _fail("EXISTING_VERIFICATION_UNTRACEABLE")
    return {
        "reference": resolved,
        "reason": reason.strip(),
        "conclusion": conclusion,
        "introducing_commit": None if provenance is None else provenance["commit"],
        "introducing_author": None if provenance is None else provenance["author"],
        "introducing_time": None if provenance is None else provenance["time"],
        "untraceable_reason": untraceable,
        "accepted_diff_reason": accepted_diff,
    }
