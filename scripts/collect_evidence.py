#!/usr/bin/env python3
"""collect_evidence.py -- run a deterministic command and persist evidence.

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


def _tail(text: str) -> str:
    if not text:
        return ""
    return text[-TAIL_CHARS:]


def collect(evidence_type: str, command: str) -> dict:
    run = subprocess.run(
        command, shell=True, capture_output=True, text=True
    )
    return {
        "type": evidence_type,
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "command": command,
        "exit_code": run.returncode,
        "commit": git_head(),
        "stdout_tail": _tail(run.stdout),
        "stderr_tail": _tail(run.stderr),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect harness evidence")
    parser.add_argument("--type", required=True,
                        choices=sorted(VALID_TYPES))
    parser.add_argument("--command", required=True)
    parser.add_argument("--harness-dir", default=".harness")
    args = parser.parse_args(argv)

    try:
        head = git_head()
    except RuntimeError as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2

    evidence = collect(args.type, args.command)
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
