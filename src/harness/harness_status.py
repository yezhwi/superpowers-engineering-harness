#!/usr/bin/env python3
"""harness_status.py -- unified persisted-state view.

Reads <harness-dir>/current-task.yaml and prints status.

Exit codes:
  0 = state valid and consistent
  1 = usage error
  2 = INVALID_HARNESS_STATE (missing file, unknown state,
      or DONE without gate PASS)
"""

import argparse
import sys
from pathlib import Path

import yaml

from .state_machine import STATES, is_legal

TEMPLATE_DEFAULTS = {
    "task": {"id": "UNKNOWN", "title": ""},
    "state": None,
    "iteration": 0,
    "max_iterations": 5,
    "verification": {},
    "findings": {},
    "gate": {"status": "unknown", "blocked_by": []},
}


def _load(harness_dir: Path):
    path = harness_dir / "current-task.yaml"
    if not path.exists():
        print(f"INVALID_HARNESS_STATE: missing {path}", file=sys.stderr)
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"INVALID_HARNESS_STATE: bad YAML: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(
            f"INVALID_HARNESS_STATE: {path} is not a mapping",
            file=sys.stderr,
        )
        return None
    for key, default in TEMPLATE_DEFAULTS.items():
        data.setdefault(key, {} if isinstance(default, dict) else default)
        if isinstance(default, dict):
            for k, v in default.items():
                data[key].setdefault(k, v)
    return data


def _validate(data) -> bool:
    state = data.get("state")
    if state not in STATES:
        print(f"INVALID_HARNESS_STATE: unknown state {state!r}",
              file=sys.stderr)
        return False
    # LAW 1: no DONE without quality gate PASS. Only legal entry to DONE
    # is CONVERGED -> DONE; a persisted DONE must show gate PASS.
    if state == "DONE" and data["gate"].get("status") != "PASS":
        print(
            "INVALID_HARNESS_STATE: DONE without gate PASS "
            "(only CONVERGED -> DONE is legal)",
            file=sys.stderr,
        )
        return False
    prev = data.get("previous_state")
    if prev is not None:
        if prev not in STATES:
            print(f"INVALID_HARNESS_STATE: unknown previous_state {prev!r}",
                  file=sys.stderr)
            return False
        if not is_legal(prev, state):
            print(f"INVALID_HARNESS_STATE: {prev} -> {state} is illegal",
                  file=sys.stderr)
            return False
    return True


def _render(data) -> str:
    ver = data["verification"]
    find = data["findings"]
    gate = data["gate"]
    lines = [
        f"{data['task']['id']}  {data['task'].get('title', '')}",
        "",
        f"State        {data['state']}",
        f"Iteration    {data['iteration']} / {data['max_iterations']}",
        "",
        f"Build        {ver.get('build', 'unknown')}",
        f"Unit Tests   {ver.get('unit_test', 'unknown')}",
        f"Integration  {ver.get('integration_test', 'unknown')}",
        "",
        "Findings",
        f"  Critical   {find.get('critical', 0)}",
        f"  Major      {find.get('major', 0)}",
        f"  Minor      {find.get('minor', 0)}",
        "",
        f"Gate         {gate.get('status', 'unknown')}",
    ]
    blocked_by = gate.get("blocked_by") or []
    if blocked_by:
        lines.append("")
        lines.append("Blocking")
        lines.extend(f"  {b}" for b in blocked_by)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Engineering Harness status")
    parser.add_argument("--harness-dir", default=".harness",
                        help="directory containing current-task.yaml")
    args = parser.parse_args(argv)

    data = _load(Path(args.harness_dir))
    if data is None:
        return 2
    if not _validate(data):
        return 2
    print(_render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
