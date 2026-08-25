"""Validation and persistence for Engineering Harness v0.2 complexity records."""

import datetime
import json
from pathlib import Path

from .collect_evidence import git_head, workspace_fingerprint

import yaml
from jsonschema import ValidationError, validate

from importlib import resources

SCHEMAS_DIR = resources.files("harness").joinpath("schemas")

LADDER = (
    ("reuse", "reuse"),
    ("stdlib", "stdlib"),
    ("native", "native"),
    ("existing_dependency", "existing_dependency"),
)


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _invalid(message: str) -> None:
    raise ValidationError(message)


def validate_minimal_decision(document: dict) -> None:
    """Validate Decision Ladder shape and ordered short-circuit semantics."""
    validate(document, _schema("minimal-implementation.schema.json"))
    checks = document["checks"]
    decision = document["decision"]["approach"]

    if decision == "unnecessary":
        if checks["existence"]["result"] != "unnecessary":
            _invalid("unnecessary decision requires unnecessary existence")
        return
    if checks["existence"]["result"] != "required":
        _invalid("non-unnecessary decision requires required existence")

    names = [name for name, _ in LADDER] + ["minimum_local_implementation"]
    found_index = None
    found_approach = None
    for index, (name, approach) in enumerate(LADDER):
        if checks[name]["result"] == "found":
            found_index = index
            found_approach = approach
            break

    if found_index is not None:
        if decision != found_approach:
            _invalid("decision approach must match first found check")
        for name in names[found_index + 1:]:
            check = checks[name]
            if check["checked"] or check["result"] != "skipped":
                _invalid("short-circuit requires later checks to be skipped")
        return

    local = checks["minimum_local_implementation"]
    if local["result"] == "skipped":
        _invalid("minimum local implementation cannot be skipped without earlier match")
    if decision not in {"local_implementation", "new_abstraction"}:
        _invalid("decision approach must be local implementation or new abstraction")


def validate_complexity_finding(document: dict) -> None:
    """Validate one evidence-backed complexity finding."""
    validate(document, _schema("finding.schema.json"))


def write_complexity_review(harness_dir: Path, review: dict) -> list[Path]:
    """Persist validated CPLX records plus fresh review metadata."""
    required = {"task", "base", "head", "findings"}
    if not isinstance(review, dict) or required - review.keys() or not isinstance(review["findings"], list):
        _invalid("complexity review requires task, base, head, and findings")
    findings_dir = harness_dir / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for finding in review["findings"]:
        validate_complexity_finding(finding)
        path = findings_dir / f"{finding['id']}.yaml"
        if path.exists():
            _invalid(f"complexity finding already exists: {finding['id']}")
        temporary = path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(finding, sort_keys=False, allow_unicode=True))
        temporary.replace(path)
        paths.append(path)
    evidence_dir = harness_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = workspace_fingerprint()
    metadata = {
        "type": "review", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": "harness review complexity", "exit_code": 0, "commit": git_head(),
        "workspace_fingerprint": fingerprint, "workspace_fingerprint_after": fingerprint,
        "base": review["base"], "head": review["head"],
        "finding_ids": [finding["id"] for finding in review["findings"]],
    }
    path = evidence_dir / "complexity-review.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2))
    temporary.replace(path)
    return paths


def write_minimal_decision(harness_dir: Path, document: dict) -> Path:
    """Validate and atomically write canonical Minimal Decision evidence."""
    validate_minimal_decision(document)
    path = harness_dir / "evidence" / "minimal-implementation.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
    temporary.replace(path)
    return path
