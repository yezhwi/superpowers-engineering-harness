"""Fail-closed validation of full Context before any CLI publication exists."""

from copy import deepcopy
from pathlib import Path
from typing import Protocol

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.blockers import blocker_document
from harness.quality_gate import OPEN_FINDING_STATUSES
from harness.schema_resources import read_schema

from .builder import build_control_core, layer0_decisions
from .escalation import effective_policy
from .freshness import capture, contained_path, digest, file_version, require_fresh
from .model import AuthoritativeContext, ContextBuildError
from .policy import policy_for_risk
from .selector import ContextSelector, DeterministicSelector
from .source import FileContextSource


class ContextIntegrityChecker(Protocol):
    def validate(self, harness_dir: Path, document: dict) -> dict[str, bool]: ...


def _schema(document) -> None:
    schema = read_schema("context.schema.json")
    try:
        validate(document, schema)
    except ValidationError as exc:
        raise ContextBuildError("CONTEXT_SCHEMA_INVALID", str(exc.message)) from exc


def _omitted(source: AuthoritativeContext) -> list[dict]:
    # Full mode retains non-global control records in working, but large bodies
    # remain referenced. Compact selection adds its own accounting in Step 4.
    names = [
        name
        for name in source.references
        if name.startswith(("evidence/", "interface-contracts/"))
    ]
    if source.observability is not None:
        names.append("observability.yaml")
    return [
        {"id": name, "reason": "body_not_inlined", **source.references[name]}
        for name in sorted(names)
    ]


def _manifest(source: AuthoritativeContext, versions: dict, working: dict) -> dict:
    groups = {
        "requirements": source.requirements,
        "invariants": source.invariants,
        "decisions": source.decisions,
        "findings": source.findings,
        "evidence": source.evidence,
    }
    return {
        "candidate_boundary": "declared-control-artifacts",
        "sources": {
            name: {
                "loaded": versions["files"].get(
                    name + (".yaml" if name in {"requirements", "invariants"} else "/")
                )
                is not None,
                "hash": versions[f"{name}_hash"],
                "total": len(records),
                "included": (
                    sum(r["priority"] == "must" for r in records)
                    + len(working["requirements"])
                    if name == "requirements"
                    else sum(
                        r["status"] == "ACCEPTED"
                        and r.get("task_id") == source.task["task"]["id"]
                        for r in records
                    )
                    + len(working["decisions"])
                    if name == "decisions"
                    else sum(r["status"] in OPEN_FINDING_STATUSES for r in records)
                    + len(working["findings"])
                    if name == "findings"
                    else len(records)
                ),
            }
            for name, records in groups.items()
        },
    }


def resolve_reference(repo_root: Path, reference: dict) -> None:
    """Check file bytes and optional unique record-id fragment; no fuzzy match."""
    ref = reference.get("ref")
    if not isinstance(ref, str):
        raise ContextBuildError(
            "CONTEXT_REFERENCE_BROKEN", "reference must be a string"
        )
    filename, separator, fragment = ref.partition("#")
    path = contained_path(repo_root, filename)
    try:
        version = file_version(path)
        if version is None:
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", f"missing reference: {filename}"
            )
        if reference.get("sha256") != version:
            raise ContextBuildError("CONTEXT_STALE", f"reference changed: {filename}")
        if separator:
            if not fragment or source_access.is_dir(path):
                raise ContextBuildError("CONTEXT_REFERENCE_BROKEN", "invalid fragment")
            value = yaml.safe_load(source_access.read_text(path))
            matches = []

            def walk(item):
                if isinstance(item, dict):
                    if item.get("id") == fragment:
                        matches.append(item)
                    for child in item.values():
                        walk(child)
                elif isinstance(item, list):
                    for child in item:
                        walk(child)

            walk(value)
            if len(matches) != 1:
                raise ContextBuildError(
                    "CONTEXT_REFERENCE_BROKEN", f"fragment not unique: {fragment}"
                )
    except (OSError, yaml.YAMLError) as exc:
        raise ContextBuildError(
            "CONTEXT_REFERENCE_BROKEN", f"cannot resolve {filename}"
        ) from exc


def _references(root: Path, value) -> None:
    if isinstance(value, dict):
        if "ref" in value:
            resolve_reference(root, value)
        for child in value.values():
            _references(root, child)
    elif isinstance(value, list):
        for child in value:
            _references(root, child)


def _same(actual, expected, detail: str) -> None:
    # JSON equality distinguishes booleans from integers, unlike Python ==.
    if digest(actual) != digest(expected):
        raise ContextBuildError("CONTEXT_INACCURATE", detail)


def _check(source: AuthoritativeContext, document: dict, root: Path) -> dict:
    from .read_scope import context_read_scope

    task_ref = source.references["current-task.yaml"]["ref"]
    with context_read_scope((root / task_ref).parent, document["generated_from"]):
        return _check_document(source, document, root)


def _check_document(source: AuthoritativeContext, document: dict, root: Path) -> dict:
    core = document["control"]
    risk = source.task["risk"]
    base_policy = policy_for_risk(risk)
    policy = effective_policy(source.task, source.expansions)
    _same(document["expansions"], source.expansions, "altered expansions")
    if (
        core["task"]["risk"] != risk
        or document["base_policy"] != base_policy
        or document["policy"] != policy
    ):
        raise ContextBuildError(
            "CONTEXT_POLICY_MISMATCH",
            "risk/profile or policy differs from authoritative task",
        )
    mandatory = {
        "requirements": [r for r in source.requirements if r["priority"] == "must"],
        "invariants": source.invariants,
        "decisions": layer0_decisions(source.decisions, source.task["task"]["id"]),
        "findings": [
            r for r in source.findings if r["status"] in OPEN_FINDING_STATUSES
        ],
    }
    for group, records in mandatory.items():
        if any(not isinstance(r.get("id"), str) for r in core[group]):
            raise ContextBuildError("CONTEXT_SCHEMA_INVALID", f"invalid id in {group}")
        if not {r["id"] for r in records} <= {r["id"] for r in core[group]}:
            raise ContextBuildError("CONTEXT_INCOMPLETE", f"missing global {group}")
        _same(core[group], records, f"altered {group}")
    blockers = [blocker_document(b) for b in source.gate.blockers]
    _same(
        core["task"],
        {"id": source.task["task"]["id"], "state": source.task["state"], "risk": risk},
        "altered task",
    )
    for field in ("scope", "authorizations"):
        _same(core[field], source.task.get(field), f"altered {field}")
    _same(core["constraints"], risk["dimensions"], "altered constraints")
    _same(core["blockers"], blockers, "altered blockers")
    _same(
        core["gate"],
        {"status": source.gate.status, "blocked_by": blockers},
        "altered live gate",
    )
    _same(core["evidence"], source.evidence, "altered evidence")
    _references(root, document)
    # Compare remaining projection fields after resolving refs, so broken refs
    # retain their actionable error code rather than an opaque equality failure.
    expected = build_control_core(source)
    for field in ("contracts", "observability"):
        _same(core[field], expected[field], f"altered {field}")
    selected = DeterministicSelector().select(source, policy, mode=document["mode"])
    _same(document["working"], selected.working, "altered working candidates")
    _same(document["references"], source.references, "altered references")
    _same(
        document["omitted"],
        _omitted(source) + selected.omitted,
        "altered omission accounting",
    )
    _same(
        document["manifest"],
        _manifest(source, document["generated_from"], selected.working),
        "altered manifest",
    )
    _same(
        document["context_hash"],
        digest(
            {key: value for key, value in document.items() if key != "context_hash"}
        ),
        "context hash mismatch",
    )
    return {
        "completeness": True,
        "accuracy": True,
        "freshness": True,
        "traceability": True,
    }


def _load_stable(harness_dir: Path, before: dict) -> AuthoritativeContext:
    from .read_scope import context_read_scope

    with context_read_scope(harness_dir, before):
        source = FileContextSource(harness_dir).load()
    require_fresh(before, capture(harness_dir))
    return source


def build_context(
    harness_dir: Path, *, mode: str = "full", selector: ContextSelector | None = None
) -> dict:
    from harness.decision import ensure_decision_index

    ensure_decision_index(harness_dir)
    before = capture(harness_dir)
    source = _load_stable(harness_dir, before)
    policy = effective_policy(source.task, source.expansions)
    from .read_scope import context_read_scope

    with context_read_scope(harness_dir, before):
        selected = (selector or DeterministicSelector()).select(
            deepcopy(source), policy, mode=mode
        )
    document = deepcopy(
        {
            "version": 1,
            "mode": mode,
            "base_policy": policy_for_risk(source.task["risk"]),
            "policy": policy,
            "expansions": source.expansions,
            "control": build_control_core(source),
            "working": selected.working,
            "references": source.references,
            "omitted": _omitted(source) + selected.omitted,
            "manifest": _manifest(source, before, selected.working),
            "generated_from": before,
        }
    )
    document["context_hash"] = digest(document)
    _schema(document)
    _check(source, document, harness_dir.absolute().parent)
    require_fresh(before, capture(harness_dir))
    return document


def validate_context(harness_dir: Path, document: dict) -> dict[str, bool]:
    """Read-only: validate the supplied old view, never regenerate over it."""
    _schema(document)
    before = capture(harness_dir)
    require_fresh(document["generated_from"], before)
    source = _load_stable(harness_dir, before)
    result = _check(source, document, harness_dir.absolute().parent)
    require_fresh(before, capture(harness_dir))
    return result
