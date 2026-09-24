"""Typed Gate blockers and deterministic recovery selection."""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

BlockerCategory = Literal[
    "verification", "implementation", "defect", "harness", "convergence"
]


USER_AUTHORITY_BLOCKER_CODES = frozenset(
    {
        "CONTRACT_CHANGED",
        "SCOPE_DRIFT_API",
        "SCOPE_DRIFT_PERMISSION",
        "SCOPE_DRIFT_PERSISTENCE",
        "DECISION_UNRESOLVED",
    }
)


def is_user_authority_blocker(code: str) -> bool:
    """Return True when autonomous recovery requires user authority."""
    return code in USER_AUTHORITY_BLOCKER_CODES or code.startswith("SCOPE_DRIFT_")


@dataclass(frozen=True)
class GateBlocker:
    code: str
    category: BlockerCategory
    message: str
    source: str | None = None
    requirement_id: str | None = None
    invariant_id: str | None = None
    finding_id: str | None = None
    recover_to: str | None = None  # Derived display field; never routing authority.

    def __contains__(self, text: str) -> bool:
        """Compatibility for callers that searched legacy blocker strings."""
        return text in self.message


RECOVERY_POLICY = {
    "EVIDENCE_MISSING": "VERIFYING",
    "EVIDENCE_WORKSPACE_STALE": "VERIFYING",
    "EVIDENCE_HEAD_MISMATCH": "VERIFYING",
    "EVIDENCE_RESULT_MISMATCH": "VERIFYING",
    "FAST_REGRESSION_EVIDENCE_MISSING": "VERIFYING",
    "FAST_USER_CHANGE_MODIFIED": "VERIFYING",
    "FAST_REPOSITORY_VERIFICATION_MISSING": "VERIFYING",
    "RISK_REVALIDATION_POLICY_MISSING": "IMPLEMENTING",
    "RISK_ESCALATION_REQUIRED": "IMPLEMENTING",
    "REQUIRED_VERIFICATION_MISSING": "VERIFYING",
    "REQUIREMENT_UNVERIFIED": "VERIFYING",
    "INVARIANT_UNVERIFIED": "VERIFYING",
    "INVARIANT_VIOLATED": "IMPLEMENTING",
    "COMPLEXITY_REVIEW_MISSING": "VERIFYING",
    "COMPLEXITY_REVIEW_STALE": "VERIFYING",
    "OBSERVABILITY_CONTRACT_INVALID": "IMPLEMENTING",
    "DIAGNOSABILITY_REVIEW_MISSING": "VERIFYING",
    "DIAGNOSABILITY_REVIEW_STALE": "VERIFYING",
    "FINDING_OPEN": "REPRODUCING",
    "IMPLEMENTATION_INCOMPLETE": "IMPLEMENTING",
    "CONTRACT_CHANGED": "ESCALATED",
    "SCOPE_DRIFT_API": "ESCALATED",
    "SCOPE_DRIFT_PERMISSION": "ESCALATED",
    "SCOPE_DRIFT_PERSISTENCE": "ESCALATED",
    "DECISION_UNRESOLVED": "ESCALATED",
    "TEST_PLAN_INCOMPLETE": "IMPLEMENTING",
    "TEST_BINDING_MISSING": "IMPLEMENTING",
    "TEST_EVIDENCE_MISSING": "VERIFYING",
    "MAX_CONVERGENCE_ITERATIONS": "ESCALATED",
}

_PRIORITY = {
    "defect": 0,
    "implementation": 1,
    "verification": 2,
    "convergence": 3,
    "harness": 4,
}


def blocker_from_message(message: str) -> GateBlocker:
    """Map existing deterministic Gate diagnostics to stable routing data."""
    missing = re.fullmatch(r"missing ([a-z-]+) evidence", message)
    if missing:
        source = missing.group(1).replace("-", "_")
        return GateBlocker(
            "EVIDENCE_MISSING",
            "verification",
            message,
            source=source,
            recover_to="VERIFYING",
        )
    finding = re.fullmatch(r"(?:Critical|Major) finding (FND-[0-9]+) is open", message)
    if finding:
        return GateBlocker(
            "FINDING_OPEN",
            "defect",
            message,
            finding_id=finding.group(1),
            recover_to="REPRODUCING",
        )
    if "EVIDENCE_" in message or "complexity-review" in message:
        code = next(
            (part for part in message.split() if part.startswith("EVIDENCE_")),
            "COMPLEXITY_REVIEW_STALE",
        )
        return GateBlocker(code, "verification", message, recover_to="VERIFYING")
    return GateBlocker(
        "REQUIRED_VERIFICATION_MISSING",
        "implementation",
        message,
        recover_to="IMPLEMENTING",
    )


def blocker_document(blocker: GateBlocker) -> dict:
    """YAML-safe persisted representation."""
    return asdict(blocker)


def select_recovery(blockers: list[GateBlocker]) -> str | None:
    """Return highest-priority permitted recovery target, never a guess."""
    if not blockers:
        return None
    if any(is_user_authority_blocker(item.code) for item in blockers):
        return None  # User decisions belong to the Guard or Gate, never resume.
    blocker = min(blockers, key=lambda item: _PRIORITY[item.category])
    target = RECOVERY_POLICY.get(blocker.code)
    return None if target == "ESCALATED" else target


def compute_blocker_fingerprint(blockers: Sequence[GateBlocker | dict]) -> str:
    """Deterministic hash of sorted blocker identity fields."""
    records = []
    for item in blockers:
        if isinstance(item, GateBlocker):
            code = item.code or ""
            category = item.category or ""
            source = item.source or ""
            req_id = item.requirement_id or ""
            inv_id = item.invariant_id or ""
            fnd_id = item.finding_id or ""
        elif isinstance(item, dict):
            code = str(item.get("code") or "")
            category = str(item.get("category") or "")
            source = str(item.get("source") or "")
            req_id = str(item.get("requirement_id") or "")
            inv_id = str(item.get("invariant_id") or "")
            fnd_id = str(item.get("finding_id") or "")
        else:
            continue
        records.append(
            {
                "code": code,
                "category": category,
                "source": source,
                "requirement_id": req_id,
                "invariant_id": inv_id,
                "finding_id": fnd_id,
            }
        )

    records.sort(
        key=lambda r: (
            r["code"],
            r["category"],
            r["source"],
            r["requirement_id"],
            r["invariant_id"],
            r["finding_id"],
        )
    )
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
