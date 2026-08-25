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
import hashlib
import subprocess
import sys
from pathlib import Path

VALID_TYPES = {
    "build", "lint", "typecheck", "unit_test", "integration_test",
    "contract_test", "security", "review", "custom",
}

TAIL_CHARS = 4000


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"not a git repository or git failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def workspace_fingerprint(repo_root: Path | None = None) -> str:
    """Stable snapshot of tracked changes and untracked business files.

    `.harness/` is runtime state and excluded so evidence writing does not
    invalidate its own snapshot.
    """
    cwd = repo_root or Path.cwd()
    def run(*args):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode().strip())
        return result.stdout
    # Exclude harness runtime state from BOTH tracked diffs and untracked scan.
    # Attach/collect commands modify .harness by design; those writes must not
    # invalidate business-code evidence.
    exclude = ":(exclude).harness/**"
    parts = [run("rev-parse", "HEAD"), run("diff", "--binary", "HEAD", "--", ".", exclude),
             run("diff", "--cached", "--binary", "HEAD", "--", ".", exclude)]
    for name in sorted(run("ls-files", "--others", "--exclude-standard").decode().splitlines()):
        if name.startswith(".harness/"):
            continue
        path = cwd / name
        if path.is_file():
            parts.extend([name.encode(), hashlib.sha256(path.read_bytes()).digest()])
    return "sha256:" + hashlib.sha256(b"\0".join(parts)).hexdigest()


def _tail(text: str) -> str:
    if not text:
        return ""
    return text[-TAIL_CHARS:]


def collect(evidence_type: str, command: str, finding_id: str | None = None,
            test_id: str | None = None, scope: str = "related",
            covered_tests: tuple[str, ...] = ()) -> dict:
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
    args = parser.parse_args(argv)

    try:
        head = git_head()
    except RuntimeError as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2

    if bool(args.finding) != bool(args.test):
        print("INVALID_USAGE: --finding and --test must be paired", file=sys.stderr)
        return 2
    if args.type == "unit_test" and args.scope == "related" and not args.covered_test:
        print("RELATED_COVERED_TEST_REQUIRED", file=sys.stderr)
        return 2
    evidence = collect(args.type, args.command, args.finding, args.test,
                       args.scope, tuple(args.covered_test))
    evidence["commit"] = head

    out_dir = Path(args.harness_dir) / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{args.type.replace('_', '-')}.json"
    out_file.write_text(json.dumps(evidence, indent=2))

    print(f"evidence written: {out_file} "
          f"(exit_code={evidence['exit_code']}, commit={head[:12]})")
    # Evidence collection itself succeeds even when the command fails;
    # the gate decides based on exit_code in the evidence.
    return 0


if __name__ == "__main__":
    sys.exit(main())
