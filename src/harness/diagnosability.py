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


def load_contract(harness_dir: Path, *, task_type: str | None = None) -> dict:
    """Load and validate a persisted Contract, failing closed on absence."""
    path = harness_dir / "observability.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _invalid(f"cannot load {path}: {exc}")
    validate_contract(document, task_type=task_type)
    return document


@dataclass(frozen=True)
class DiagnosabilityReview:
    task: str
    contract_required: bool
    checks: dict[str, str]
    finding_ids: tuple[str, ...]
    direct_dependencies: tuple[str, ...]
    claimed_files: tuple[str, ...]
    findings: tuple[dict, ...]


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
    findings = tuple(document.get("findings", []))
    if {item.get("id") for item in findings} != set(document["finding_ids"]):
        raise ValueError("DIAG_FINDING_IDS_MISMATCH")
    return DiagnosabilityReview(document["task"], document["contract_required"], document["checks"], tuple(document["finding_ids"]), tuple(document["direct_dependencies"]), tuple(document["review_scope"]["files"]), findings)


def load_review_input(path: Path, *, task_id: str) -> DiagnosabilityReview:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _invalid(f"cannot load review: {exc}")
    return validate_review_input(document, task_id=task_id)


def validate_review_readiness(contract: dict, review: dict, findings: list[dict], *, scope_files: tuple[str, ...]) -> None:
    """Fail closed unless review, Contract, Findings, and scope agree."""
    if review.get("contract_required") is not contract.get("required"):
        raise ValueError("DIAG_CONTRACT_REQUIRED_MISMATCH")
    failed = {name for name, value in (review.get("checks") or {}).items() if value == "fail"}
    linked = {finding.get("id"): finding for finding in findings if finding.get("category") == "diagnosability"}
    if failed and not linked:
        raise ValueError("DIAG_FINDING_REQUIRED")
    for name in failed:
        if not any(name in finding.get("compliance", {}).get("required_checks", []) and finding.get("location", {}).get("file") in scope_files for finding in linked.values()):
            raise ValueError("DIAG_FINDING_LINKAGE_INVALID")


def gate_blockers(harness_dir: Path, task: dict, *, head: str, workspace: str):
    """Return deterministic Contract/readiness blockers; never inspect source."""
    from .blockers import GateBlocker
    risk = (task.get("risk") or {}).get("level")
    if risk not in {"Q2", "Q3"}:
        return []
    try:
        contract = load_contract(harness_dir, task_type=task.get("task", {}).get("type"))
    except ValueError as exc:
        return [GateBlocker("OBSERVABILITY_CONTRACT_INVALID", "implementation", str(exc), recover_to="IMPLEMENTING")]
    if risk == "Q3" and contract["applicability"]["reasons"] == ["not_assessed"]:
        return [GateBlocker("OBSERVABILITY_CONTRACT_INVALID", "implementation", "Q3 observability contract is not assessed", recover_to="IMPLEMENTING")]
    required = risk == "Q3" or contract["required"]
    if not required:
        return []
    path = harness_dir / "evidence" / "diagnosability-review.json"
    if not path.exists():
        return [GateBlocker("DIAGNOSABILITY_REVIEW_MISSING", "verification", "missing diagnosability review evidence", recover_to="VERIFYING")]
    try:
        record = json.loads(path.read_text())
        findings = [yaml.safe_load(item.read_text()) for item in (harness_dir / "findings").glob("*.yaml")]
        validate_review_readiness(contract, record, findings, scope_files=tuple(record.get("review_scope", {}).get("files", [])))
        if any(value == "fail" for value in record.get("checks", {}).values()):
            raise ValueError("DIAG_REVIEW_HAS_FAILED_CHECKS")
        validate_compliance_closure({"category": "diagnosability", "compliance": {"required_checks": [name for name, value in record.get("checks", {}).items() if value == "pass"]}}, record, current_head=head, current_workspace=workspace)
    except (OSError, json.JSONDecodeError, ValueError):
        return [GateBlocker("DIAGNOSABILITY_REVIEW_STALE", "verification", "diagnosability review evidence is invalid or stale", recover_to="VERIFYING")]
    return []


def validate_compliance_closure(finding: dict, record: dict, *, current_head: str, current_workspace: str) -> None:
    """Validate terminal DIAG proof without accepting ordinary Finding proof."""
    if finding.get("category") != "diagnosability":
        raise ValueError("DIAG_COMPLIANCE_FINDING_REQUIRED")
    if record.get("type") != "diagnosability_review" or record.get("exit_code") != 0:
        raise ValueError("DIAG_COMPLIANCE_EVIDENCE_INVALID")
    if record.get("commit") != current_head or record.get("workspace_fingerprint") != current_workspace or record.get("workspace_fingerprint_after") != current_workspace:
        raise ValueError("DIAG_COMPLIANCE_EVIDENCE_STALE")
    checks = record.get("checks") or {}
    for name in finding["compliance"]["required_checks"]:
        if checks.get(name) != "pass":
            raise ValueError("DIAG_COMPLIANCE_CHECK_FAILED")


def write_review(harness_dir: Path, review: DiagnosabilityReview, *, base_ref: str, task_type: str | None = None) -> Path:
    contract = load_contract(harness_dir, task_type=task_type)
    scope = review_scope(base_ref)
    files = tuple(sorted(set(scope.files) | set(contract["applicability"]["inspected_paths"]) | set(review.direct_dependencies)))
    if review.claimed_files != files:
        raise ValueError("DIAGNOSABILITY_SCOPE_MISMATCH")
    findings = [yaml.safe_load(item.read_text()) for item in (harness_dir / "findings").glob("*.yaml")] + list(review.findings)
    for finding in review.findings:
        validate(finding, json.loads(resources.files("harness").joinpath("schemas", "finding.schema.json").read_text()))
    review_data = {"contract_required": review.contract_required, "checks": review.checks, "finding_ids": list(review.finding_ids)}
    validate_review_readiness(contract, review_data, findings, scope_files=files)
    current = snapshot()
    for finding in review.findings:
        path = harness_dir / "findings" / f"{finding['id']}.yaml"
        if path.exists():
            raise ValueError("DIAG_FINDING_EXISTS")
    for finding in review.findings:
        path = harness_dir / "findings" / f"{finding['id']}.yaml"
        temp = path.with_suffix('.yaml.tmp')
        temp.write_text(yaml.safe_dump(finding, sort_keys=False), encoding='utf-8')
        temp.replace(path)
    record = {"type": "diagnosability_review", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "command": "harness review diagnosability", "exit_code": 0, "commit": git_head(), "workspace_fingerprint": current.fingerprint, "workspace_fingerprint_after": current.fingerprint, "review_scope": {"files": list(files), "direct_dependencies": list(review.direct_dependencies)}, "contract_required": review.contract_required, "checks": review.checks, "finding_ids": list(review.finding_ids)}
    evidence = harness_dir / "evidence" / "diagnosability-review.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    temp = evidence.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    temp.replace(evidence)
    return evidence
