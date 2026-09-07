"""Canonical Harness artifact path validation."""

from pathlib import Path
import re


class EvidenceReferenceError(ValueError):
    """An artifact reference does not name a canonical evidence file."""


class IdentifierError(ValueError):
    """Persisted artifact identifier is not canonical."""


def identifier_path(
    harness_dir: Path, directory_name: str, identifier: str, pattern: str
) -> Path:
    """Resolve exact identifier to a contained YAML artifact path."""
    directory = (harness_dir / directory_name).resolve()
    if not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
        raise IdentifierError("IDENTIFIER_INVALID")
    candidate = (directory / f"{identifier}.yaml").resolve()
    if candidate.parent != directory:
        raise IdentifierError("IDENTIFIER_INVALID")
    return candidate


def evidence_output_path(harness_dir: Path, filename: str) -> Path:
    """Return a write path that cannot leave the canonical evidence directory."""
    evidence_dir = (harness_dir / "evidence").resolve()
    if (
        not isinstance(filename, str)
        or not filename
        or Path(filename).is_absolute()
        or Path(filename).name != filename
        or ".." in Path(filename).parts
    ):
        raise EvidenceReferenceError("EVIDENCE_WRITE_PATH_INVALID")
    resolved = (evidence_dir / filename).resolve()
    if resolved.parent != evidence_dir:
        raise EvidenceReferenceError("EVIDENCE_WRITE_PATH_INVALID")
    return resolved


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
