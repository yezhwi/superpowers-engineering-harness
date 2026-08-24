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
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from state_machine import STATES

# Finding statuses that must block the gate. Terminal/healthy:
# VERIFIED, CLOSED, REJECTED. FIXED (test green, regression pending)
# still blocks - full regression evidence does not exist yet.
OPEN_FINDING_STATUSES = {
    "PROPOSED", "REPRODUCING", "CONFIRMED", "FIXING", "FIXED",
}


class InvalidHarnessState(Exception):
    pass


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


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
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise InvalidHarnessState(
            f"cannot resolve git HEAD: {result.stderr.strip()}"
        )
    return result.stdout.strip()


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


def run_gate(harness_dir: Path, head: str | None = None) -> tuple[str, list]:
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

    # Gate may only be executed from GATING (or REVIEWING pre-transition).
    if state not in ("GATING", "REVIEWING"):
        raise InvalidHarnessState(
            f"state {state} does not allow gate execution "
            "(must be REVIEWING/GATING)"
        )

    head = head if head is not None else git_head()
    evidence = load_evidence(harness_dir / "evidence")
    findings = load_findings(harness_dir / "findings")

    blockers = []

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
                blockers.append(f"{req.get('id')} not verified")
                continue
            refs = req.get("evidence") or []
            if not refs:
                blockers.append(
                    f"{req.get('id')} verified without evidence")
                continue
            for ref in refs:
                name = ref if isinstance(ref, str) else                     (ref or {}).get("ref", "")
                if not name:
                    blockers.append(
                        f"{req.get('id')} has an empty evidence ref")
                    continue
                fname = name if name.endswith(".json") else f"{name}.json"
                path = evidence_dir / fname
                if not path.is_file():
                    blockers.append(
                        f"{req.get('id')} evidence missing: {fname}")
                    continue
                try:
                    ev = json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    raise InvalidHarnessState(
                        f"bad JSON in {path}: {exc}")
                if ev.get("exit_code") != 0:
                    blockers.append(
                        f"{req.get('id')} evidence {fname} failed "
                        f"(exit_code={ev.get('exit_code')})")
                elif must_match_head and ev.get("commit") != head:
                    blockers.append(
                        f"{req.get('id')} evidence {fname} is stale "
                        f"(commit {ev.get('commit')} != HEAD)")

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
            blockers.append(f"{iid} violated")
        elif status != "verified":
            if severity in ("critical", "major"):
                blockers.append(
                    f"{iid} not verified "
                    f"(pending {severity} invariant is not proven)")
            elif severity == "minor" and minor_verified:
                blockers.append(f"{iid} not verified")

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
            blockers.append(f"missing {label} evidence")
            continue
        if ev.get("exit_code") != 0:
            blockers.append(f"{label} evidence command failed "
                            f"(exit_code={ev.get('exit_code')})")
        if must_match_head and ev.get("commit") != head:
            blockers.append(f"{label} evidence is stale "
                            f"(commit {ev.get('commit')} != HEAD)")

    # 4. Findings: open critical/major counts, regression debt.
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
        blockers.append(f"Critical finding {f['id']} is open")
    for f in open_major[major_allowed:]:
        blockers.append(f"Major finding {f['id']} is open")

    # Confirmed findings must carry a regression test (LAW 4).
    confirmed = [f for f in findings if f.get("status") == "CONFIRMED"]
    regression_cfg = gate_cfg.get("regression", {})
    without_test_allowed = int(
        regression_cfg.get("confirmed_finding_without_test", 0))
    no_test = [f for f in confirmed
               if not (f.get("regression_test") or {}).get("path")]
    for f in no_test[without_test_allowed:]:
        blockers.append(
            f"Confirmed finding {f['id']} has no regression test")

    status = "PASS" if not blockers else "BLOCKED"
    return status, blockers


def write_back(harness_dir: Path, status: str, blockers: list):
    path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task.setdefault("gate", {})
    task["gate"]["status"] = status
    task["gate"]["blocked_by"] = blockers
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
    for b in blockers:
        print(f"- {b}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
