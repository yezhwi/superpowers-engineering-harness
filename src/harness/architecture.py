"""Pure Architecture model validation, ownership resolution, and fingerprinting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from jsonschema import ValidationError, validate

from harness.schema_resources import read_schema

_MAX_ARCHITECTURE_BYTES = 1024 * 1024
_FORBIDDEN_PATTERN_CHARS = frozenset("?[]{}")


class ArchitectureError(ValueError):
    """Stable Architecture error code plus non-sensitive detail."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class ArchitectureEvidence:
    type: Literal["source", "config", "documentation"]
    path: str


@dataclass(frozen=True)
class ArchitectureModule:
    id: str
    name: str
    responsibility: str
    depends_on: tuple[str, ...]
    evidence: tuple[ArchitectureEvidence, ...]


@dataclass(frozen=True)
class OwnershipRule:
    id: str
    pattern: str
    kind: Literal["production", "shared", "support"]
    modules: tuple[str, ...]
    allow_empty: bool
    empty_reason: str | None


@dataclass(frozen=True)
class ArchitectureModel:
    version: int
    modules: tuple[ArchitectureModule, ...]
    ownership: tuple[OwnershipRule, ...]


@dataclass(frozen=True)
class OwnershipResolution:
    path: str
    status: Literal["resolved", "unresolved", "ambiguous"]
    kind: str | None = None
    modules: tuple[str, ...] = ()
    rule_id: str | None = None
    rule_ids: tuple[str, ...] = ()
    pattern: str | None = None
    score: tuple[int, int, int] | None = None


def _semantic_bytes(document: object) -> bytes:
    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArchitectureError("ARCHITECTURE_SCHEMA_INVALID", "not JSON-compatible") from exc


def _segments(value: str, *, pattern: bool) -> tuple[str, ...]:
    code = "ARCHITECTURE_PATTERN_INVALID" if pattern else "ARCHITECTURE_PATH_INVALID"
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ArchitectureError(code, "path must be canonical repository-relative POSIX")
    segments = tuple(value.split("/"))
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ArchitectureError(code, "path contains noncanonical segment")
    if pattern:
        if any(char in value for char in _FORBIDDEN_PATTERN_CHARS):
            raise ArchitectureError(code, "unsupported wildcard syntax")
        for index, segment in enumerate(segments):
            if segment == "**":
                if index != len(segments) - 1:
                    raise ArchitectureError(code, "recursive wildcard must be final")
            elif "*" in segment and segment != "*":
                raise ArchitectureError(code, "wildcard must occupy one segment")
    elif any(char in value for char in "*?[]{}"):
        raise ArchitectureError(code, "literal path required")
    return segments


def _rule_identity(rule: OwnershipRule) -> tuple:
    return (
        rule.pattern,
        rule.kind,
        tuple(sorted(rule.modules)),
        rule.allow_empty,
        rule.empty_reason or "",
    )


def load_architecture_document(
    document: object, *, source_size_bytes: int | None = None
) -> ArchitectureModel:
    """Validate and convert one Architecture document without repository I/O."""
    size = len(_semantic_bytes(document)) if source_size_bytes is None else source_size_bytes
    if type(size) is not int or size < 0 or size > _MAX_ARCHITECTURE_BYTES:
        raise ArchitectureError("ARCHITECTURE_SIZE_LIMIT", "canonical YAML exceeds 1 MiB")
    try:
        validate(document, read_schema("architecture.schema.json"))
    except (ValidationError, TypeError) as exc:
        raise ArchitectureError("ARCHITECTURE_SCHEMA_INVALID", "schema validation failed") from exc
    assert isinstance(document, dict)

    raw_modules = document["modules"]
    module_ids = [record["id"] for record in raw_modules]
    if len(set(module_ids)) != len(module_ids):
        raise ArchitectureError("ARCHITECTURE_MODEL_INVALID", "duplicate module id")
    known_modules = set(module_ids)
    modules: list[ArchitectureModule] = []
    for record in raw_modules:
        dependencies = tuple(record["depends_on"])
        if record["id"] in dependencies:
            raise ArchitectureError("ARCHITECTURE_MODEL_INVALID", "self dependency")
        if not set(dependencies) <= known_modules:
            raise ArchitectureError("ARCHITECTURE_MODEL_INVALID", "unknown dependency")
        evidence = tuple(
            ArchitectureEvidence(item["type"], item["path"])
            for item in record["evidence"]
        )
        for item in evidence:
            _segments(item.path, pattern=False)
        modules.append(
            ArchitectureModule(
                record["id"],
                record["name"],
                record["responsibility"],
                dependencies,
                evidence,
            )
        )

    raw_rules = document["ownership"]
    rule_ids = [record["id"] for record in raw_rules]
    if len(set(rule_ids)) != len(rule_ids):
        raise ArchitectureError("ARCHITECTURE_MODEL_INVALID", "duplicate ownership id")
    rules: list[OwnershipRule] = []
    for record in raw_rules:
        _segments(record["pattern"], pattern=True)
        modules_for_rule = tuple(record["modules"])
        if not set(modules_for_rule) <= known_modules:
            raise ArchitectureError("ARCHITECTURE_MODEL_INVALID", "unknown ownership module")
        allow_empty = record.get("allow_empty", False)
        if allow_empty and not modules_for_rule:
            raise ArchitectureError(
                "ARCHITECTURE_MODEL_INVALID", "empty support rule cannot be evidence-anchored"
            )
        rules.append(
            OwnershipRule(
                record["id"],
                record["pattern"],
                record["kind"],
                modules_for_rule,
                allow_empty,
                record.get("empty_reason"),
            )
        )
    identities = [_rule_identity(rule) for rule in rules]
    if len(set(identities)) != len(identities):
        raise ArchitectureError("ARCHITECTURE_MODEL_INVALID", "duplicate ownership rule")
    return ArchitectureModel(document["version"], tuple(modules), tuple(rules))


def _match_score(pattern: str, path: str) -> tuple[int, int, int] | None:
    pattern_segments = _segments(pattern, pattern=True)
    path_segments = _segments(path, pattern=False)
    path_index = 0
    for segment in pattern_segments:
        if segment == "**":
            if path_index >= len(path_segments):
                return None
            path_index = len(path_segments)
            break
        if path_index >= len(path_segments):
            return None
        if segment != "*" and segment != path_segments[path_index]:
            return None
        path_index += 1
    if path_index != len(path_segments):
        return None
    exact = int(all(segment not in {"*", "**"} for segment in pattern_segments))
    literal_count = sum(segment not in {"*", "**"} for segment in pattern_segments)
    return exact, literal_count, len(pattern_segments)


def ownership_match_score(
    rule: OwnershipRule, path: str
) -> tuple[int, int, int] | None:
    """Return deterministic rule score for one canonical path, or no match."""
    return _match_score(rule.pattern, path)


def resolve_ownership(model: ArchitectureModel, path: str) -> OwnershipResolution:
    """Resolve one canonical path without repository access or implicit tie-breaks."""
    _segments(path, pattern=False)
    matches = [
        (score, rule)
        for rule in model.ownership
        if (score := _match_score(rule.pattern, path)) is not None
    ]
    if not matches:
        return OwnershipResolution(path, "unresolved")
    best_score = max(score for score, _ in matches)
    best = [rule for score, rule in matches if score == best_score]
    if len(best) != 1:
        return OwnershipResolution(
            path,
            "ambiguous",
            rule_ids=tuple(sorted(rule.id for rule in best)),
            score=best_score,
        )
    rule = best[0]
    return OwnershipResolution(
        path,
        "resolved",
        kind=rule.kind,
        modules=tuple(sorted(rule.modules)),
        rule_id=rule.id,
        rule_ids=(rule.id,),
        pattern=rule.pattern,
        score=best_score,
    )


def architecture_fingerprint(model: ArchitectureModel) -> str:
    """Hash normalized semantic Architecture facts, never YAML presentation."""
    normalized = {
        "version": model.version,
        "modules": sorted(
            (
                {
                    "id": module.id,
                    "name": module.name,
                    "responsibility": module.responsibility,
                    "depends_on": sorted(module.depends_on),
                    "evidence": sorted(
                        ({"type": item.type, "path": item.path} for item in module.evidence),
                        key=lambda item: (item["type"], item["path"]),
                    ),
                }
                for module in model.modules
            ),
            key=lambda item: item["id"],
        ),
        "ownership": sorted(
            (
                {
                    "id": rule.id,
                    "pattern": rule.pattern,
                    "kind": rule.kind,
                    "modules": sorted(rule.modules),
                    "allow_empty": rule.allow_empty,
                    "empty_reason": rule.empty_reason,
                }
                for rule in model.ownership
            ),
            key=lambda item: (
                item["pattern"],
                item["kind"],
                item["modules"],
                item["allow_empty"],
                item["empty_reason"] or "",
                item["id"],
            ),
        ),
    }
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
