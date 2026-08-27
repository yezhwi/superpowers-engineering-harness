"""Deterministic task state machine for the Engineering Harness.

Single source of truth for the fixed state enum and legal transition
table (spec docs/engineering-harness-v0.1.md sections 6.1-6.3).
"""

from typing import Dict, Set

STATES = frozenset({
    "CREATED",
    "SPECIFYING",
    "PLANNED",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "REPRODUCING",
    "FIXING",
    "GATING",
    "BLOCKED",
    "CONVERGED",
    "DONE",
    "ESCALATED",
})

TRANSITIONS: Set[tuple] = frozenset({
    ("CREATED", "SPECIFYING"),
    ("SPECIFYING", "PLANNED"),
    ("PLANNED", "IMPLEMENTING"),
    ("IMPLEMENTING", "VERIFYING"),
    ("VERIFYING", "IMPLEMENTING"),
    ("VERIFYING", "REVIEWING"),
    ("REVIEWING", "REPRODUCING"),
    ("REVIEWING", "VERIFYING"),
    ("REVIEWING", "GATING"),
    ("REPRODUCING", "REVIEWING"),
    ("REPRODUCING", "FIXING"),
    ("FIXING", "VERIFYING"),
    ("GATING", "BLOCKED"),
    ("GATING", "CONVERGED"),
    ("BLOCKED", "IMPLEMENTING"),
    ("BLOCKED", "VERIFYING"),
    ("BLOCKED", "REPRODUCING"),
    ("BLOCKED", "ESCALATED"),
    ("CONVERGED", "DONE"),
})


class InvalidTransition(Exception):
    """Raised when a transition is not in the legal table or a state is unknown."""


def is_legal(current: str, target: str) -> bool:
    """Return True iff current -> target is a legal transition.

    Raises InvalidTransition for unknown states.
    """
    if current not in STATES:
        raise InvalidTransition(f"unknown state: {current!r}")
    if target not in STATES:
        raise InvalidTransition(f"unknown target state: {target!r}")
    return (current, target) in TRANSITIONS


def require_legal(current: str, target: str) -> None:
    """Raise InvalidTransition with a readable message if illegal."""
    if is_legal(current, target):
        return
    raise InvalidTransition(
        f"INVALID TRANSITION:\n{current} -> {target}"
    )


def legal_targets(current: str) -> Set[str]:
    """All states legally reachable from current. Raises on unknown state."""
    if current not in STATES:
        raise InvalidTransition(f"unknown state: {current!r}")
    return {t for (c, t) in TRANSITIONS if c == current}


_TRANSITION_MAP: Dict[str, Set[str]] = {
    s: legal_targets(s) for s in STATES
}
