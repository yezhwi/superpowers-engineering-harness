"""Canonical Harness artifact path validation."""

from pathlib import Path


class EvidenceReferenceError(ValueError):
    """An artifact reference does not name a canonical evidence file."""


def evidence_path(harness_dir: Path, reference: str) -> Path:
    """Resolve one evidence filename without allowing directory escape."""
    candidate = Path(reference)
    if (
        not isinstance(reference, str)
        or not reference
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name in {"", ".", ".."}
    ):
        raise EvidenceReferenceError("EVIDENCE_REFERENCE_INVALID")
    name = candidate.name if candidate.suffix == ".json" else f"{candidate.name}.json"
    return harness_dir / "evidence" / name
