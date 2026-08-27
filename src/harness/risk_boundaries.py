"""Declared FAST risk boundaries; no semantic inference."""
from pathlib import Path, PurePosixPath

import yaml


class RiskBoundaryPolicyError(ValueError):
    pass


def load_boundaries(path: Path) -> dict[str, tuple[str, ...]]:
    try:
        data = yaml.safe_load(path.read_text())
        boundaries = data["boundaries"]
        if set(boundaries) != {"q2", "q3"}:
            raise ValueError
        result = {level: tuple(boundaries[level]) for level in ("q2", "q3")}
        if any(not values or any(not isinstance(item, str) or not item for item in values) for values in result.values()):
            raise ValueError
        return result
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValueError) as exc:
        raise RiskBoundaryPolicyError("RISK_BOUNDARY_POLICY_INVALID") from exc


def business_paths(paths) -> tuple[str, ...]:
    return tuple(sorted(path for path in paths if not (
        path.startswith((".harness/", "docs/", "tests/", "test/"))
        or ("/" not in path and path.endswith(".md"))
    )))


def required_level(paths, boundaries: dict[str, tuple[str, ...]]) -> str | None:
    required = None
    for path in paths:
        candidate = PurePosixPath(path)
        if any(candidate.match(pattern) for pattern in boundaries["q3"]):
            return "Q3"
        if any(candidate.match(pattern) for pattern in boundaries["q2"]):
            required = "Q2"
    return required
