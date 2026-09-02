"""Persisted production-diagnosability contract validation."""

import datetime
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .transaction import StagedArtifact, publish, stage
from .workspace import git_head, project_task_scope, review_scope, snapshot

import yaml
from jsonschema import ValidationError, validate


SCHEMA = resources.files("harness").joinpath("schemas", "observability.schema.json")
REVIEW_SCHEMA = resources.files("harness").joinpath("schemas", "diagnosability-review.schema.json")
PROPOSAL_SCHEMA = resources.files("harness").joinpath("schemas", "diagnosability-proposal.schema.json")
FINDING_SCHEMA = resources.files("harness").joinpath("schemas", "diagnosability-finding.schema.json")
REVIEW_EVIDENCE_SCHEMA = resources.files("harness").joinpath("schemas", "diagnosability-review-evidence.schema.json")
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
    proposals: tuple[dict, ...]


def validate_review_input(document: dict, *, task_id: str) -> DiagnosabilityReview:
    try:
        validate(document, json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        _invalid(f"review: {exc}")
    if document["task"] != task_id:
        _invalid("review task mismatch")
    failed = {name for name, result in document["checks"].items() if result == "fail"}
    proposals = tuple(document.get("proposals", []))
    for proposal in proposals:
        try:
            validate(proposal, json.loads(PROPOSAL_SCHEMA.read_text(encoding="utf-8")))
        except ValidationError as exc:
            code = "DIAG_PROPOSAL_FIELD_REQUIRED" if exc.validator == "required" else "DIAG_FINDING_INVALID"
            raise ValueError(code) from exc
    if failed and not proposals:
        raise ValueError("DIAG_FINDING_REQUIRED")
    return DiagnosabilityReview(document["task"], document["contract_required"], document["checks"], tuple(document["finding_ids"]), tuple(document["direct_dependencies"]), tuple(document["review_scope"]["files"]), proposals)


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
    files = set(scope_files)
    if not set(contract.get("applicability", {}).get("inspected_paths", [])) <= files:
        raise ValueError("DIAG_CONTRACT_SCOPE_INCOMPLETE")
    checks = review.get("checks") or {}
    required_dimensions = {
        "business_keys": "business_keys",
        "external_failure_context": "failure_boundaries",
        "state_transitions": "state_transitions",
    }
    for check, field in required_dimensions.items():
        if checks.get(check) == "not_applicable" and contract.get(field):
            raise ValueError("DIAG_NOT_APPLICABLE_INVALID")
    failed = {name for name, value in checks.items() if value == "fail"}
    finding_ids = set(review.get("finding_ids") or [])
    linked = {finding.get("id"): finding for finding in findings if finding.get("category") == "diagnosability" and finding.get("id") in finding_ids}
    if failed and not linked:
        raise ValueError("DIAG_FINDING_REQUIRED")
    for name in failed:
        if not any(name in finding.get("compliance", {}).get("required_checks", []) and finding.get("location", {}).get("file") in scope_files for finding in linked.values()):
            raise ValueError("DIAG_FINDING_LINKAGE_INVALID")


def validate_review_evidence(record: dict) -> None:
    """Validate canonical persisted review evidence before Gate admission."""
    try:
        validate(record, json.loads(REVIEW_EVIDENCE_SCHEMA.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("DIAG_REVIEW_EVIDENCE_INVALID") from exc
    checks = record["checks"]
    if set(checks) != set(CHECK_NAMES):
        raise ValueError("DIAG_CHECK_SET_INVALID")
    if any(value not in {"pass", "fail", "not_applicable"} for value in checks.values()):
        raise ValueError("DIAG_CHECK_VALUE_INVALID")


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
        validate_review_evidence(record)
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
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    if task.get("scope") is None:
        files = tuple(sorted(set(scope.files) | set(contract["applicability"]["inspected_paths"]) | set(review.direct_dependencies)))
    else:
        impact_path = harness_dir / "impact.yaml"
        impact_doc = yaml.safe_load(impact_path.read_text()) if impact_path.exists() else {"impact": {}}
        files = project_task_scope(
            task, impact_doc.get("impact") or {},
            inspected_paths=contract["applicability"]["inspected_paths"],
            direct_dependencies=review.direct_dependencies,
        )
    if review.claimed_files != files:
        raise ValueError("DIAGNOSABILITY_SCOPE_MISMATCH")
    existing = [yaml.safe_load(item.read_text()) for item in (harness_dir / "findings").glob("*.yaml")]
    def equivalent(finding, proposal):
        return finding.get("category") == "diagnosability" and all((finding.get(key) if key != "required_checks" else finding.get("compliance", {}).get("required_checks")) == proposal[key] for key in ("target", "reason_code", "location", "required_checks"))
    for proposal in review.proposals:
        match = next((finding for finding in existing if equivalent(finding, proposal)), None)
        if match:
            raise ValueError(f"DIAG_PROPOSAL_DUPLICATE: {proposal['local_id']} matches {match['id']}")
    next_id = max([int(finding["id"].split("-")[1]) for finding in existing if str(finding.get("id", "")).startswith("FND-")] or [0]) + 1
    generated = []
    mapping = {}
    for proposal in review.proposals:
        fid = f"FND-{next_id:03d}"; next_id += 1; mapping[proposal["local_id"]] = fid
        generated.append({"id": fid, "kind": "requirement_violation", "category": "diagnosability", "target": proposal["target"], "scenario": proposal["local_id"], "severity": proposal["severity"], "status": "PROPOSED", "reason_code": proposal["reason_code"], "location": proposal["location"], "compliance": {"evidence_kind": "static_compliance", "required_checks": proposal["required_checks"]}})
    for finding in generated:
        try:
            validate(finding, json.loads(FINDING_SCHEMA.read_text(encoding="utf-8")))
        except ValidationError as exc:
            raise ValueError("DIAG_FINDING_INVALID") from exc
    findings = existing + generated
    review_data = {"contract_required": review.contract_required, "checks": review.checks, "finding_ids": list(mapping.values())}
    validate_review_readiness(contract, review_data, findings, scope_files=files)
    current = snapshot()
    record = {"type": "diagnosability_review", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "command": "harness review diagnosability", "exit_code": 0, "commit": git_head(), "workspace_fingerprint": current.fingerprint, "workspace_fingerprint_after": current.fingerprint, "review_scope": {"files": list(files), "direct_dependencies": list(review.direct_dependencies)}, "contract_required": review.contract_required, "checks": review.checks, "finding_ids": list(mapping.values()), "finding_mapping": mapping}
    artifacts = [StagedArtifact(f"findings/{finding['id']}.yaml", yaml.safe_dump(finding, sort_keys=False).encode()) for finding in generated]
    artifacts.append(StagedArtifact("evidence/diagnosability-review.json", json.dumps(record, indent=2).encode(), replace=True))
    publish(harness_dir, stage(harness_dir, artifacts), replace_paths=frozenset({"evidence/diagnosability-review.json"}))
    return harness_dir / "evidence" / "diagnosability-review.json"
