"""Risk-derived context breadth and deterministic advisory phase routing."""

from harness.risk import PROFILES
from harness.state_machine import STATES

from .model import ContextBuildError

POLICIES = {"Q1": "LOCAL", "Q2": "BOUNDED", "Q3": "EXPANDED"}


def policy_for_risk(risk: dict) -> str:
    if not isinstance(risk, dict):
        raise ContextBuildError("CONTEXT_POLICY_MISMATCH", "classified risk required")
    level = risk.get("level")
    if (
        not isinstance(level, str)
        or level not in POLICIES
        or risk.get("profile") != PROFILES[level]
    ):
        raise ContextBuildError("CONTEXT_POLICY_MISMATCH", "risk/profile mismatch")
    return POLICIES[level]


def next_action(state: str, profile: str) -> str:
    """Advisory action, never a state transition or execution authorization."""
    if state not in STATES or profile not in PROFILES.values():
        raise ContextBuildError("CONTEXT_POLICY_MISMATCH", "unknown state/profile")
    if state == "CLASSIFIED":
        return "implement" if profile == "FAST" else "specify_contract"
    return {
        "CREATED": "classify_task",
        "SPECIFYING": "specify_contract",
        "PLANNED": "record_minimal_implementation",
        "IMPLEMENTING": "implement_and_record_impact",
        "VERIFYING": "collect_verification",
        "REVIEWING": "review_and_record_outcome",
        "REPRODUCING": "reproduce_finding",
        "FIXING": "fix_confirmed_finding",
        "GATING": "run_gate",
        "BLOCKED": "resume_from_blocker",
        "CONVERGED": "transition_done",
        "DONE": "none",
        "ESCALATED": "await_human",
    }[state]
