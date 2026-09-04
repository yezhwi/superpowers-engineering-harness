"""Validation and persistence for Engineering Harness v0.2 complexity records."""

import datetime
import json
from pathlib import Path

from .transaction import StagedArtifact, publish, stage
from .workspace import git_head, snapshot

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
        for name in names[found_index + 1 :]:
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
    validate(document, _schema("complexity-finding.schema.json"))


def validate_complexity_checks(review: dict) -> None:
    checks = review.get("checks")
    if checks is None:
        return  # v0.2.7 legacy compatibility
    names = {"delete", "reuse", "stdlib", "native", "yagni", "shrink"}
    if set(checks) != names:
        _invalid("COMPLEXITY_CHECKS_INVALID")
    failed = set()
    for name, check in checks.items():
        if (
            not isinstance(check, dict)
            or set(check) != {"result", "evidence"}
            or check["result"] not in {"pass", "fail", "not_applicable"}
            or not isinstance(check["evidence"], str)
            or not check["evidence"]
        ):
            _invalid("COMPLEXITY_CHECK_INVALID")
        if check["result"] == "fail":
            failed.add(name)
    found = {finding.get("type") for finding in review.get("findings", [])}
    if not failed <= found:
        _invalid("COMPLEXITY_FINDING_REQUIRED")


def write_complexity_review(harness_dir: Path, review: dict, scope=None) -> list[Path]:
    """Persist validated CPLX records plus Harness-calculated scope metadata."""
    required = {"task", "findings"}
    if (
        not isinstance(review, dict)
        or required - review.keys()
        or not isinstance(review["findings"], list)
    ):
        _invalid("complexity review requires task and findings")
    validate_complexity_checks(review)
    finding_ids = set()
    for finding in review["findings"]:
        validate_complexity_finding(finding)
        if finding["id"] in finding_ids:
            _invalid(f"duplicate complexity finding: {finding['id']}")
        finding_ids.add(finding["id"])
        if (harness_dir / "findings" / f"{finding['id']}.yaml").exists():
            _invalid(f"complexity finding already exists: {finding['id']}")
    fingerprint = snapshot().fingerprint
    metadata = {
        "type": "review",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": "harness review complexity",
        "exit_code": 0,
        "commit": git_head(),
        "workspace_fingerprint": fingerprint,
        "workspace_fingerprint_after": fingerprint,
        "base": scope.base_commit if scope else review.get("base", "HEAD"),
        "head": scope.head_commit if scope else git_head(),
        "finding_ids": [finding["id"] for finding in review["findings"]],
        "checks": review.get("checks"),
        "review_scope": {
            "base_ref": scope.base_ref,
            "base_commit": scope.base_commit,
            "head_commit": scope.head_commit,
            "workspace_fingerprint": scope.workspace.fingerprint,
            "files": list(scope.files),
        }
        if scope
        else None,
    }
    artifacts = [
        StagedArtifact(
            f"findings/{finding['id']}.yaml",
            yaml.safe_dump(finding, sort_keys=False, allow_unicode=True).encode(),
        )
        for finding in review["findings"]
    ]
    artifacts.append(
        StagedArtifact(
            "evidence/complexity-review.json",
            json.dumps(metadata, indent=2).encode(),
            replace=True,
        )
    )
    publish(
        harness_dir,
        stage(harness_dir, artifacts),
        replace_paths=frozenset({"evidence/complexity-review.json"}),
    )
    return [
        harness_dir / "findings" / f"{finding['id']}.yaml"
        for finding in review["findings"]
    ]


def write_minimal_decision(harness_dir: Path, document: dict) -> Path:
    """Validate and atomically write canonical Minimal Decision evidence."""
    validate_minimal_decision(document)
    path = harness_dir / "evidence" / "minimal-implementation.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
    temporary.replace(path)
    return path
