"""Read-only recovery guidance for Harness diagnostic codes."""

from __future__ import annotations

from dataclasses import dataclass

from .blockers import RECOVERY_POLICY, is_user_authority_blocker


@dataclass(frozen=True)
class Remediation:
    code: str
    reason: str
    next_step: str


_EXACT = {
    "PLAN_STALE": Remediation(
        "PLAN_STALE",
        "Plan semantic digest differs from its execution record.",
        "Run: harness plan sync-fingerprint (only when execution is empty)",
    ),
    "PLAN_EXECUTION_NOT_EMPTY": Remediation(
        "PLAN_EXECUTION_NOT_EMPTY",
        "Execution history is immutable and cannot be rebound to a changed Plan.",
        "Run: harness check admission; then revise through normal implementation recovery.",
    ),
    "RELATED_COVERED_TEST_REQUIRED": Remediation(
        "RELATED_COVERED_TEST_REQUIRED",
        "Related test evidence needs an explicit covered test selector.",
        "Run: harness evidence run --type unit_test --scope related --covered-test path/to/test.py::test_name --command '<test command>'",
    ),
}


def explain(code: str) -> Remediation | None:
    """Return safe operator guidance without reading or changing task state."""
    if code in _EXACT:
        return _EXACT[code]
    if is_user_authority_blocker(code):
        return Remediation(
            code,
            "This change needs an explicit user decision or authority.",
            "User action required: review impact and record an explicit Decision.",
        )
    recovery = RECOVERY_POLICY.get(code)
    if recovery is None:
        return None
    return Remediation(
        code,
        f"Gate recovery target is {recovery}.",
        "Run: harness status; then run: harness resume",
    )
