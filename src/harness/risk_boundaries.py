"""Declared FAST risk boundaries; no semantic inference."""
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

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
        if any(
            not values or any(
                not isinstance(item, str)
                or not item
                or item.startswith("/")
                or ".." in item.split("/")
                for item in values
            )
            for values in result.values()
        ):
            raise ValueError
        return result
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValueError) as exc:
        raise RiskBoundaryPolicyError("RISK_BOUNDARY_POLICY_INVALID") from exc


def business_paths(paths) -> tuple[str, ...]:
    return tuple(sorted(path for path in paths if not (
        path.startswith((".harness/", "docs/", "tests/", "test/"))
        or ("/" not in path and path.endswith(".md"))
    )))


def matches_boundary(path: str, pattern: str) -> bool:
    """Match an anchored repository-relative path with recursive ``**``."""
    path_parts = tuple(path.split("/"))
    pattern_parts = tuple(pattern.split("/"))
    if not path or path.startswith("/") or ".." in path_parts:
        return False

    @lru_cache(maxsize=None)
    def matches(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        token = pattern_parts[pattern_index]
        if token == "**":
            return any(matches(next_index, pattern_index + 1)
                       for next_index in range(path_index, len(path_parts) + 1))
        return (
            path_index < len(path_parts)
            and fnmatchcase(path_parts[path_index], token)
            and matches(path_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


def required_level(paths, boundaries: dict[str, tuple[str, ...]]) -> str | None:
    required = None
    for path in paths:
        if any(matches_boundary(path, pattern) for pattern in boundaries["q3"]):
            return "Q3"
        if any(matches_boundary(path, pattern) for pattern in boundaries["q2"]):
            required = "Q2"
    return required
