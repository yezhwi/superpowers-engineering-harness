"""harness CLI (guide section 20): parse args -> init service -> render ->
exit code. No init logic here.

Exit codes:
  0 = SUCCESS
  1 = OPERATION_FAILED (e.g. outside a git repository)
  2 = INVALID_USAGE
"""

import argparse
import sys

from harness import controlplane
from harness.init import InitResult, init_current_repository
from harness.repository import RepositoryNotFoundError


def _render(result: InitResult) -> str:
    lines = [f"Harness initialized at {result.harness_dir}"]
    if result.created:
        lines.append("Created:")
        lines.extend(f"  created  {p.name}" for p in result.created)
    if result.skipped:
        lines.append("Skipped (already present, untouched):")
        lines.extend(f"  skipped  {p.name}" for p in result.skipped)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Engineering Harness deterministic control plane",
    )
    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser("init", help="initialize .harness/ at the git repo root")
    p_status = sub.add_parser(
        "status", help="render unified persisted-state view")
    p_status.add_argument("--harness-dir", default=".harness")
    p_trans = sub.add_parser(
        "transition", help="validate and persist a state transition")
    p_trans.add_argument("target")
    p_ev = sub.add_parser(
        "evidence", help="run a command and save HEAD-bound evidence")
    p_ev.add_argument("--type", required=True)
    p_ev.add_argument("--command", required=True,
                      dest="evidence_command")
    sub.add_parser("gate", help="run the deterministic quality gate")
    p_finding = sub.add_parser("finding", help="inspect findings")
    f_sub = p_finding.add_subparsers(dest="finding_command")
    f_sub.add_parser("list", help="list all findings")
    p_show = f_sub.add_parser("show", help="show one finding record")
    p_show.add_argument("id")
    sub.add_parser("converge", help="deterministic convergence decision")

    args = parser.parse_args(argv)

    if args.subcommand == "init":
        try:
            result = init_current_repository()
        except RepositoryNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(_render(result))
        return 0
    if args.subcommand == "status":
        return controlplane.cmd_status()
    if args.subcommand == "transition":
        return controlplane.cmd_transition(args.target)
    if args.subcommand == "evidence":
        return controlplane.cmd_evidence(args.type, args.evidence_command)
    if args.subcommand == "gate":
        return controlplane.cmd_gate()
    if args.subcommand == "finding":
        if args.finding_command == "list":
            return controlplane.cmd_finding_list()
        if args.finding_command == "show":
            return controlplane.cmd_finding_show(args.id)
        parser.print_usage(sys.stderr)
        return 2
    if args.subcommand == "converge":
        return controlplane.cmd_converge()

    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
