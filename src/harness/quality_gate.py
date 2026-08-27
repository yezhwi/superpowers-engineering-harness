#!/usr/bin/env python3
"""quality_gate.py -- deterministic quality gate (Milestone 2 core).

Reads .harness/{current-task.yaml, requirements.yaml, invariants.yaml,
gate.yaml}, findings/*.yaml, evidence/*.json and git HEAD.
All checks are deterministic Python logic -- no LLM judgement.

Exit codes:
  0 = PASS
  1 = BLOCKED (blockers listed on stdout)
  2 = INVALID_HARNESS_STATE
"""

import argparse
import json
import sys
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from .blockers import GateBlocker, RECOVERY_POLICY, blocker_document
from .evidence_validator import EvidenceValidationError, validate_evidence
from .state_machine import STATES
from .workspace import WorkspaceError, git_head as workspace_head, snapshot

# Finding statuses that must block the gate. Terminal/healthy:
# VERIFIED, CLOSED, REJECTED. FIXED (test green, regression pending)
# still blocks - full regression evidence does not exist yet.
OPEN_FINDING_STATUSES = {
    "PROPOSED", "REPRODUCING", "CONFIRMED", "FIXING", "FIXED",
}


class InvalidHarnessState(Exception):
    pass


from importlib import resources

SCHEMAS_DIR = resources.files("harness").joinpath("schemas")


def validate_schema(document: object, schema_name: str, source: Path) -> None:
    """Fail closed when any persisted harness document violates its schema."""
    schema_path = SCHEMAS_DIR / schema_name
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidHarnessState(f"cannot load {schema_path}: {exc}") from exc
    try:
        validate(document, schema)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise InvalidHarnessState(
            f"{source} fails {schema_name} at {location}: {exc.message}"
        ) from exc


def _load_yaml(path: Path):
    if not path.exists():
        raise InvalidHarnessState(f"missing {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise InvalidHarnessState(f"bad YAML in {path}: {exc}")
    if not isinstance(data, dict):
        raise InvalidHarnessState(f"{path} is not a mapping")
    return data


def git_head() -> str:
    try:
        return workspace_head()
    except WorkspaceError as exc:
        raise InvalidHarnessState(str(exc)) from exc


def load_evidence(evidence_dir: Path) -> dict:
    """Return {type: evidence_dict}; invalid files raise INVALID."""
    evidence = {}
    if not evidence_dir.is_dir():
        return evidence
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise InvalidHarnessState(f"bad JSON in {path}: {exc}")
        validate_schema(data, "evidence.schema.json", path)
        etype = data["type"]
        evidence[etype] = data
    return evidence


def load_findings(findings_dir: Path) -> list:
    findings = []
    if not findings_dir.is_dir():
        return findings
    for path in sorted(findings_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        validate_schema(data, "finding.schema.json", path)
        findings.append(data)
    return findings


def run_gate(harness_dir: Path, head: str | None = None,
             allow_converged: bool = False) -> tuple[str, list]:
    """Returns (status, blockers). status in {'PASS','BLOCKED'}.
    Raises InvalidHarnessState."""
    task = _load_yaml(harness_dir / "current-task.yaml")
    requirements_doc = _load_yaml(harness_dir / "requirements.yaml")
    invariants_doc = _load_yaml(harness_dir / "invariants.yaml")
    gate_doc = _load_yaml(harness_dir / "gate.yaml")

    validate_schema(task, "task.schema.json", harness_dir / "current-task.yaml")
    validate_schema(
        requirements_doc, "requirement.schema.json",
        harness_dir / "requirements.yaml",
    )
    validate_schema(
        invariants_doc, "invariant.schema.json",
        harness_dir / "invariants.yaml",
    )
    gate_cfg = gate_doc.get("gate", {})

    state = task.get("state")
    if state not in STATES:
        raise InvalidHarnessState(f"unknown task state {state!r}")

    # Single legal path: REVIEWING -> GATING -> quality gate.
    if state != "GATING" and not (allow_converged and state == "CONVERGED"):
        raise InvalidHarnessState(
            f"state {state} does not allow gate execution (must be GATING)"
        )

    head = head if head is not None else git_head()
    evidence = load_evidence(harness_dir / "evidence")
    findings = load_findings(harness_dir / "findings")
    impact_path = harness_dir / "impact.yaml"
    impact = _load_yaml(impact_path) if impact_path.exists() else {}
    # HEAD alone misses uncommitted edits. Shared snapshot excludes harness
    # runtime files, so evidence writes do not invalidate business proof.
    try:
        current_workspace = snapshot().fingerprint
    except WorkspaceError as exc:
        raise InvalidHarnessState(f"cannot fingerprint workspace: {exc}") from exc

    # Terminal/near-terminal findings require real proof records, not only
    # schema-shaped strings. Fail closed before open-finding policy runs.
    def finding_proof(finding, ref, expected_success, label, test_id=None):
        path = harness_dir / "evidence" / (ref if ref.endswith(".json") else f"{ref}.json")
        try:
            record = json.loads(path.read_text())
            validate_evidence(record, current_head=head, current_workspace=current_workspace,
                              expected_success=expected_success,
                              require_current_workspace=expected_success,
                              finding_id=finding["id"] if test_id else None,
                              test_id=test_id)
        except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
            raise InvalidHarnessState(f"{finding['id']} {label} evidence invalid: {exc}") from exc
    for finding in findings:
        state = finding["status"]
        if state in {"CONFIRMED", "FIXING", "FIXED", "VERIFIED", "CLOSED"}:
            finding_proof(finding, finding["regression_test"]["red_evidence"], False, "red", finding["regression_test"]["path"])
        if state in {"FIXED", "VERIFIED", "CLOSED"}:
            finding_proof(finding, finding["regression_test"]["green_evidence"], True, "green", finding["regression_test"]["path"])
        if state in {"VERIFIED", "CLOSED"}:
            ref = finding["evidence"]
            path = harness_dir / "evidence" / (ref if ref.endswith(".json") else f"{ref}.json")
            try:
                record = json.loads(path.read_text())
                from .evidence_validator import validate_finding_closure_evidence
                validate_finding_closure_evidence(
                    finding, record, impact, current_head=head,
                    current_workspace=current_workspace,
                )
            except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
                raise InvalidHarnessState(
                    f"{finding['id']} full regression evidence invalid: {exc}"
                ) from exc

    blockers: list[GateBlocker] = []

    def block(code: str, category: str, message: str, **identity) -> None:
        blockers.append(GateBlocker(
            code, category, message, recover_to=RECOVERY_POLICY.get(code), **identity
        ))

    # 1. Requirements: priority=must must be verified WITH fresh evidence.
    # A self-declared status=verified carries no weight on its own: each
    # verified must-requirement needs >=1 evidence ref resolving to an
    # evidence file that exists, ran successfully, and matches HEAD.
    req_cfg = gate_cfg.get("requirements", {})
    if req_cfg.get("must_verified", True):
        must_match_head = bool(
            gate_cfg.get("evidence", {}).get("must_match_head", True)
        )
        evidence_dir = harness_dir / "evidence"
        for req in requirements_doc.get("requirements", []):
            if req.get("priority") != "must":
                continue
            if req.get("status") != "verified":
                block("REQUIREMENT_UNVERIFIED", "verification", f"{req.get('id')} not verified", requirement_id=req.get("id"))
                continue
            refs = req.get("evidence") or []
            if not refs:
                block("EVIDENCE_MISSING", "verification", f"{req.get('id')} verified without evidence", requirement_id=req.get("id"))
                continue
            for ref in refs:
                name = ref if isinstance(ref, str) else                     (ref or {}).get("ref", "")
                if not name:
                    block("EVIDENCE_MISSING", "verification", f"{req.get('id')} has an empty evidence ref", requirement_id=req.get("id"))
                    continue
                fname = name if name.endswith(".json") else f"{name}.json"
                path = evidence_dir / fname
                if not path.is_file():
                    block("EVIDENCE_MISSING", "verification", f"{req.get('id')} evidence missing: {fname}", source=fname, requirement_id=req.get("id"))
                    continue
                try:
                    ev = json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    raise InvalidHarnessState(
                        f"bad JSON in {path}: {exc}")
                try:
                    validate_evidence(ev, current_head=head, current_workspace=current_workspace,
                                      expected_success=True)
                except EvidenceValidationError as exc:
                    block(str(exc).split(":", 1)[0], "verification", f"{req.get('id')} evidence {fname} invalid: {exc}", source=fname, requirement_id=req.get("id"))

    # 2. Invariants: violated blocks; unproven blocks for critical/major.
    # pending == not proven == BLOCKED. Only proven-safe (verified)
    # invariants may pass the gate. Minor invariants are configurable via
    # gate.invariants.minor_verified (default false).
    inv_cfg = gate_cfg.get("invariants", {})
    minor_verified = bool(inv_cfg.get("minor_verified", False))
    for inv in invariants_doc.get("invariants", []):
        status = inv.get("status")
        severity = inv.get("severity")
        iid = inv.get("id")
        if status == "violated":
            block("INVARIANT_UNVERIFIED", "implementation", f"{iid} violated", invariant_id=iid)
        elif status != "verified":
            if severity in ("critical", "major"):
                block("INVARIANT_UNVERIFIED", "verification", f"{iid} not verified (pending {severity} invariant is not proven)", invariant_id=iid)
            elif severity == "minor" and minor_verified:
                block("INVARIANT_UNVERIFIED", "verification", f"{iid} not verified", invariant_id=iid)
        elif severity in ("critical", "major") or minor_verified:
            refs = inv.get("verification") or []
            if not refs:
                block("EVIDENCE_MISSING", "verification", f"{iid} verified without verification evidence", invariant_id=iid)
            for ref in refs:
                name = ref if isinstance(ref, str) else (ref or {}).get("ref", "")
                path = evidence_dir / (name if name.endswith(".json") else f"{name}.json")
                try:
                    ev = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    block("EVIDENCE_MISSING", "verification", f"{iid} verification evidence missing: {name}", source=name, invariant_id=iid)
                    continue
                try:
                    validate_evidence(ev, current_head=head, current_workspace=current_workspace,
                                      expected_success=True)
                except EvidenceValidationError as exc:
                    block(str(exc).split(":", 1)[0], "verification", f"{iid} verification evidence {name} invalid: {exc}", source=name, invariant_id=iid)

    # 3. Required verification evidence exists, exit_code==0, fresh HEAD.
    ver_cfg = gate_cfg.get("verification", {})
    must_match_head = bool(
        gate_cfg.get("evidence", {}).get("must_match_head", True)
    )
    for vtype, policy in ver_cfg.items():
        if policy != "required":
            continue
        ev = evidence.get(vtype)
        label = vtype.replace("_", "-")
        if ev is None:
            block("EVIDENCE_MISSING", "verification", f"missing {label} evidence", source=vtype)
            continue
        try:
            validate_evidence(ev, current_head=head, current_workspace=current_workspace,
                              expected_success=True)
        except EvidenceValidationError as exc:
            block(str(exc).split(":", 1)[0], "verification", f"{label} evidence invalid: {exc}", source=vtype)

    # 4. Complexity: required review evidence and configured open severities.
    complexity_cfg = gate_cfg.get("complexity", {})
    if complexity_cfg.get("required", False):
        review_path = harness_dir / "evidence" / "complexity-review.json"
        try:
            review = json.loads(review_path.read_text())
            validate_schema(review, "evidence.schema.json", review_path)
        except (OSError, json.JSONDecodeError, InvalidHarnessState):
            block("COMPLEXITY_REVIEW_MISSING", "verification", "missing complexity-review evidence", source="complexity-review")
        else:
            try:
                validate_evidence(review, current_head=head, current_workspace=current_workspace,
                                  expected_success=True)
            except EvidenceValidationError as exc:
                block(str(exc).split(":", 1)[0], "verification", f"complexity-review evidence invalid: {exc}", source="complexity-review")
        blocking = set(complexity_cfg.get("blocking", ["high"]))
        for finding in findings:
            if (finding.get("id", "").startswith("CPLX-")
                    and finding.get("status") == "open"
                    and finding.get("severity") in blocking):
                block("IMPLEMENTATION_INCOMPLETE", "implementation", f"{finding['severity'].title()} complexity finding {finding['id']} is open", finding_id=finding["id"])

    # 5. Findings: open critical/major counts, regression debt.
    find_cfg = gate_cfg.get("findings", {})
    critical_allowed = int(find_cfg.get("critical_allowed", 0))
    major_allowed = int(find_cfg.get("major_allowed", 0))

    def is_open(f):
        return f.get("status") in OPEN_FINDING_STATUSES

    open_critical = [f for f in findings
                     if is_open(f) and f.get("severity") == "critical"]
    open_major = [f for f in findings
                  if is_open(f) and f.get("severity") == "major"]
    for f in open_critical[critical_allowed:]:
        block("FINDING_OPEN", "defect", f"Critical finding {f['id']} is open", finding_id=f["id"])
    for f in open_major[major_allowed:]:
        block("FINDING_OPEN", "defect", f"Major finding {f['id']} is open", finding_id=f["id"])

    # Confirmed findings must carry a regression test (LAW 4).
    confirmed = [f for f in findings if f.get("status") == "CONFIRMED"]
    regression_cfg = gate_cfg.get("regression", {})
    without_test_allowed = int(
        regression_cfg.get("confirmed_finding_without_test", 0))
    no_test = [f for f in confirmed
               if not (f.get("regression_test") or {}).get("path")]
    for f in no_test[without_test_allowed:]:
        block("IMPLEMENTATION_INCOMPLETE", "implementation", f"Confirmed finding {f['id']} has no regression test", finding_id=f["id"])

    status = "PASS" if not blockers else "BLOCKED"
    return status, blockers


def write_back(harness_dir: Path, status: str, blockers: list):
    path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task.setdefault("gate", {})
    task["gate"]["status"] = status
    task["gate"]["blocked_by"] = [blocker_document(blocker) for blocker in blockers]
    task["git"] = {"head": git_head()}
    path.write_text(yaml.safe_dump(task, sort_keys=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic quality gate")
    parser.add_argument("--harness-dir", default=".harness")
    args = parser.parse_args(argv)

    harness_dir = Path(args.harness_dir)
    try:
        status, blockers = run_gate(harness_dir)
        write_back(harness_dir, status, blockers)
    except InvalidHarnessState as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2

    if status == "PASS":
        print("QUALITY GATE: PASS")
        return 0

    print("QUALITY GATE: BLOCKED")
    print()
    print("Blocking:")
    for blocker in blockers:
        print(f"- {blocker.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
