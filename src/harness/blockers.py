"""Typed Gate blockers and deterministic recovery selection."""

from dataclasses import asdict, dataclass
import re
from typing import Literal


BlockerCategory = Literal[
    "verification", "implementation", "defect", "harness", "convergence"
]


@dataclass(frozen=True)
class GateBlocker:
    code: str
    category: BlockerCategory
    message: str
    source: str | None = None
    finding_id: str | None = None
    recover_to: str | None = None


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
        return GateBlocker("EVIDENCE_MISSING", "verification", message,
                           source=source, recover_to="VERIFYING")
    finding = re.fullmatch(r"(?:Critical|Major) finding (FND-[0-9]+) is open", message)
    if finding:
        return GateBlocker("FINDING_OPEN", "defect", message,
                           finding_id=finding.group(1), recover_to="REPRODUCING")
    if "EVIDENCE_" in message or "complexity-review" in message:
        code = next((part for part in message.split() if part.startswith("EVIDENCE_")),
                    "COMPLEXITY_REVIEW_STALE")
        return GateBlocker(code, "verification", message, recover_to="VERIFYING")
    return GateBlocker("REQUIRED_VERIFICATION_MISSING", "implementation", message,
                       recover_to="IMPLEMENTING")


def blocker_document(blocker: GateBlocker) -> dict:
    """YAML-safe persisted representation."""
    return asdict(blocker)


def select_recovery(blockers: list[GateBlocker]) -> str | None:
    """Return highest-priority permitted recovery target, never a guess."""
    if not blockers:
        return None
    blocker = min(blockers, key=lambda item: _PRIORITY[item.category])
    return blocker.recover_to
