#!/usr/bin/env python3
"""Harness evidence collection and persistence.

Usage:
  python scripts/collect_evidence.py --type unit_test --command "pytest"

Writes <harness-dir>/evidence/<type-with-dashes>.json containing:
  type, timestamp, command, exit_code, commit (git HEAD),
  stdout_tail, stderr_tail.

Evidence is saved even when the command fails.
Exit codes: 0 = evidence written; 2 = invalid harness state / usage.
"""

import argparse
import datetime
import json
import platform
import subprocess
import sys
from pathlib import Path

import yaml

from .budget import BudgetOverrideRequired, budget_action, check_budget, is_retry, record_budget, record_failure
from .evidence_validator import ReuseRequest, can_reuse_evidence
from .telemetry import update_telemetry
from .workspace import git_head as workspace_head, snapshot

VALID_TYPES = {
    "build", "lint", "typecheck", "unit_test", "integration_test",
    "contract_test", "security", "review", "custom",
}

TAIL_CHARS = 4000


def git_head() -> str:
    """Compatibility wrapper for shared workspace HEAD lookup."""
    try:
        return workspace_head()
    except RuntimeError as exc:
        raise RuntimeError(f"not a git repository or git failed: {exc}") from exc


def runtime_metadata() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "executable": sys.executable,
        "platform": f"{platform.system()}-{platform.machine()}",
    }


def workspace_fingerprint(repo_root: Path | None = None) -> str:
    """Compatibility wrapper for shared workspace snapshot fingerprint."""
    return snapshot(repo_root).fingerprint


def evidence_filename(evidence_type: str, *, finding_id: str | None = None,
                      phase: str | None = None) -> str:
    """Return deterministic generic or finding evidence filename."""
    stem = evidence_type.replace("_", "-")
    if finding_id is None:
        if phase is None:
            return f"{stem}.json"
        if phase not in {"red", "green"}:
            raise ValueError("task phase must be red or green")
        return f"fast-{phase}-{stem}.json"
    if phase not in {"red", "green", "full"}:
        raise ValueError("finding evidence requires phase red, green, or full")
    return f"{finding_id}-{phase}-{stem}.json"


def _tail(text: str) -> str:
    if not text:
        return ""
    return text[-TAIL_CHARS:]


def collect(evidence_type: str, command: str, finding_id: str | None = None,
            test_id: str | None = None, scope: str = "related",
            covered_tests: tuple[str, ...] = (), phase: str | None = None) -> dict:
    before = workspace_fingerprint()
    run = subprocess.run(
        command, shell=True, capture_output=True, text=True
    )
    after = workspace_fingerprint()
    evidence = {
        "type": evidence_type,
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "command": command,
        "exit_code": run.returncode,
        "commit": git_head(),
        "workspace_fingerprint": before,
        "workspace_fingerprint_after": after,
        "runtime": runtime_metadata(),
        "stdout_tail": _tail(run.stdout),
        "stderr_tail": _tail(run.stderr),
    }
    if evidence_type == "unit_test":
        evidence["scope"] = scope
        evidence["covered_tests"] = list(covered_tests)
    if finding_id is not None:
        evidence["subject"] = {"kind": "finding", "id": finding_id}
        evidence["test"] = {"node_id": test_id}
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect harness evidence")
    parser.add_argument("--type", required=True,
                        choices=sorted(VALID_TYPES))
    parser.add_argument("--command", required=True)
    parser.add_argument("--harness-dir", default=".harness")
    parser.add_argument("--finding")
    parser.add_argument("--test")
    parser.add_argument("--scope", choices=["related", "full_suite"], default="related")
    parser.add_argument("--covered-test", action="append", default=[])
    parser.add_argument("--phase", choices=["red", "green", "full"])
    parser.add_argument("--reuse-if-valid", action="store_true")
    parser.add_argument("--budget-override-reason")
    parser.add_argument("--budget-override-evidence")
    parser.add_argument("--budget-override-hypothesis")
    args = parser.parse_args(argv)

    try:
        head = git_head()
    except RuntimeError as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2

    if bool(args.finding) != bool(args.test):
        print("INVALID_USAGE: --finding and --test must be paired", file=sys.stderr)
        return 2
    if args.finding and not args.phase:
        print("INVALID_USAGE: --finding requires --phase", file=sys.stderr)
        return 2
    if not args.finding and args.phase == "full":
        print("INVALID_USAGE: task phase must be red or green", file=sys.stderr)
        return 2
    if args.type == "unit_test" and args.scope == "related" and not args.covered_test:
        print("RELATED_COVERED_TEST_REQUIRED", file=sys.stderr)
        return 2
    out_dir = Path(args.harness_dir) / "evidence"
    out_file = out_dir / evidence_filename(args.type, finding_id=args.finding,
                                            phase=args.phase)
    if args.reuse_if_valid and not args.finding and args.phase is None:
        request = ReuseRequest(args.type, args.command, args.scope,
                               tuple(args.covered_test), args.phase,
                               args.finding, args.test)
        try:
            candidate = json.loads(out_file.read_text())
            if can_reuse_evidence(candidate, request, current_head=head,
                                  current_workspace=workspace_fingerprint(),
                                  current_runtime=runtime_metadata()):
                print(f"EVIDENCE_REUSED: {out_file.name}")
                return 0
        except (OSError, json.JSONDecodeError):
            pass

    override_values = (args.budget_override_reason, args.budget_override_evidence, args.budget_override_hypothesis)
    if any(override_values) and not all(override_values):
        print("BUDGET_OVERRIDE_REQUIRED", file=sys.stderr); return 2
    task_path = Path(args.harness_dir) / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text()) if task_path.exists() else None
    action = budget_action(args.type, 0, args.command)
    override = ({"reason": args.budget_override_reason, "evidence": args.budget_override_evidence, "hypothesis": args.budget_override_hypothesis} if all(override_values) else None)
    try:
        if task and action:
            check_budget(task, action, override)
            if is_retry(task, args.command):
                check_budget(task, "retry", override)
    except BudgetOverrideRequired as exc:
        print(str(exc), file=sys.stderr); return 2

    evidence = collect(args.type, args.command, args.finding, args.test,
                       args.scope, tuple(args.covered_test), args.phase)
    evidence["commit"] = head

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(evidence, indent=2))
    if task and action:
        record_budget(task, action, override)
        if is_retry(task, args.command):
            record_budget(task, "retry", override)
        if evidence["exit_code"]:
            record_failure(task, args.command)
        task_path.write_text(yaml.safe_dump(task, sort_keys=False))
        update_telemetry(Path(args.harness_dir), task)

    print(f"evidence written: {out_file} "
          f"(exit_code={evidence['exit_code']}, commit={head[:12]})")
    # Evidence collection itself succeeds even when the command fails;
    # the gate decides based on exit_code in the evidence.
    return 0


if __name__ == "__main__":
    sys.exit(main())
