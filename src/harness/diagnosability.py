"""Persisted production-diagnosability contract validation."""

import json
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate


SCHEMA = resources.files("harness").joinpath("schemas", "observability.schema.json")
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
