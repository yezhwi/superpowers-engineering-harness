"""Controlled review outcomes and reason codes."""

REVIEW_REASON_CODES = {
    "PASS": {"REVIEW_CLEAN"},
    "VERIFICATION_GAP": {
        "TEST_COVERAGE_INSUFFICIENT",
        "EVIDENCE_INCOMPLETE",
        "INVARIANT_UNPROVEN",
        "TEST_SCOPE_INSUFFICIENT",
    },
    "DEFECT": {
        "LOGIC_ERROR",
        "REGRESSION",
        "CONTRACT_VIOLATION",
        "INVARIANT_VIOLATION",
        "DIAGNOSABILITY_VIOLATION",
    },
}


def is_allowed(outcome: str, reason_code: str) -> bool:
    return reason_code in REVIEW_REASON_CODES.get(outcome, set())
