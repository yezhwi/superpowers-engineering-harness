"""Persisted production-diagnosability contract validation."""

import datetime
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .workspace import git_head, review_scope, snapshot

import yaml
from jsonschema import ValidationError, validate


SCHEMA = resources.files("harness").joinpath("schemas", "observability.schema.json")
REVIEW_SCHEMA = resources.files("harness").joinpath("schemas", "diagnosability-review.schema.json")
CHECK_NAMES = ("business_keys", "external_failure_context", "state_transitions", "caller_rejections", "sensitive_data", "duplicate_exception_logging", "low_value_logging")

_REQUIRED_FIELDS = {
    "version", "required", "applicability", "business_keys", "failure_boundaries",
}
_REQUIRED_DIMENSIONS = {"critical_events", "state_transitions", "external_dependencies"}


def _invalid(message: str) -> None:
    raise ValueError(f"OBSERVABILITY_CONTRACT_INVALID: {message}")


def _schema() -> dict:
    try:
        return json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _invalid(f"cannot load schema: {exc}")


def validate_contract(document: dict, *, task_type: str | None) -> None:
    """Validate Contract shape plus conditional diagnosability rules."""
    try:
        validate(document, _schema())
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        _invalid(f"{location}: {exc.message}")
    if not isinstance(document, dict):
        _invalid("contract is not a mapping")

    if document["required"]:
        missing = _REQUIRED_FIELDS - set(document)
        if missing:
            _invalid(f"required contract missing {sorted(missing)[0]}")
        if not _REQUIRED_DIMENSIONS & set(document):
            _invalid("required contract has no diagnostic dimension")
    else:
        allowed = {"version", "required", "applicability"}
        if task_type == "bugfix":
            allowed.add("bug_fix")
        unexpected = set(document) - allowed
        if unexpected:
            _invalid(f"non-required contract has unsupported field {sorted(unexpected)[0]}")

    bug_fix = document.get("bug_fix")
    if task_type == "bugfix":
        if not isinstance(bug_fix, dict):
            _invalid("bugfix contract requires bug_fix")
        gap = bug_fix["observability_gap"]
        has_improvement = "improvement" in bug_fix or "missing_information" in bug_fix
        if gap and not {"improvement", "missing_information"} <= set(bug_fix):
            _invalid("observability_gap=true requires improvement and missing_information")
        if not gap and has_improvement:
            _invalid("observability_gap=false forbids improvement and missing_information")
    elif bug_fix is not None:
        _invalid("bug_fix is allowed only for bugfix tasks")


def load_contract(harness_dir: Path) -> dict:
    """Load and validate a persisted Contract, failing closed on absence."""
    path = harness_dir / "observability.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _invalid(f"cannot load {path}: {exc}")
    validate_contract(document, task_type=None)
    return document


@dataclass(frozen=True)
class DiagnosabilityReview:
    task: str
    contract_required: bool
    checks: dict[str, str]
    finding_ids: tuple[str, ...]
    direct_dependencies: tuple[str, ...]
    claimed_files: tuple[str, ...]


def validate_review_input(document: dict, *, task_id: str) -> DiagnosabilityReview:
    try:
        validate(document, json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        _invalid(f"review: {exc}")
    if document["task"] != task_id:
        _invalid("review task mismatch")
    failed = {name for name, result in document["checks"].items() if result == "fail"}
    if failed and not document["finding_ids"]:
        raise ValueError("DIAG_FINDING_REQUIRED")
    return DiagnosabilityReview(document["task"], document["contract_required"], document["checks"], tuple(document["finding_ids"]), tuple(document["direct_dependencies"]), tuple(document["review_scope"]["files"]))


def load_review_input(path: Path, *, task_id: str) -> DiagnosabilityReview:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _invalid(f"cannot load review: {exc}")
    return validate_review_input(document, task_id=task_id)


def write_review(harness_dir: Path, review: DiagnosabilityReview, *, base_ref: str) -> Path:
    contract = load_contract(harness_dir)
    scope = review_scope(base_ref)
    files = tuple(sorted(set(scope.files) | set(contract["applicability"]["inspected_paths"]) | set(review.direct_dependencies)))
    if review.claimed_files != files:
        raise ValueError("DIAGNOSABILITY_SCOPE_MISMATCH")
    current = snapshot()
    record = {"type": "diagnosability_review", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "command": "harness review diagnosability", "exit_code": 0, "commit": git_head(), "workspace_fingerprint": current.fingerprint, "workspace_fingerprint_after": current.fingerprint, "review_scope": {"files": list(files), "direct_dependencies": list(review.direct_dependencies)}, "contract_required": review.contract_required, "checks": review.checks, "finding_ids": list(review.finding_ids)}
    evidence = harness_dir / "evidence" / "diagnosability-review.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    temp = evidence.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    temp.replace(evidence)
    return evidence
