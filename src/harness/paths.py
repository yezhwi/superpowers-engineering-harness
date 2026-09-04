"""Canonical Harness artifact path validation."""

from pathlib import Path


class EvidenceReferenceError(ValueError):
    """An artifact reference does not name a canonical evidence file."""


def evidence_path(harness_dir: Path, reference: str) -> Path:
    """Resolve ID, filename, project-relative, or absolute canonical evidence path."""
    evidence_dir = (harness_dir / "evidence").resolve()

    def invalid():
        candidates = ", ".join(
            path.stem for path in sorted(evidence_dir.glob("*.json"))
        )
        raise EvidenceReferenceError(
            f"EVIDENCE_REFERENCE_INVALID; candidates: {candidates}"
        )

    if not isinstance(reference, str) or not reference:
        invalid()
    candidate = Path(reference)
    if len(candidate.parts) == 1 and not candidate.is_absolute():
        resolved = evidence_dir / (
            candidate.name if candidate.suffix == ".json" else f"{candidate.name}.json"
        )
    else:
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (harness_dir.parent / candidate).resolve()
        )
    if resolved.parent != evidence_dir or resolved.suffix != ".json":
        invalid()
    return resolved
