"""harness CLI (guide section 20): parse args -> init service -> render ->
exit code. No init logic here.

Exit codes:
  0 = SUCCESS
  1 = OPERATION_FAILED (e.g. outside a git repository)
  2 = INVALID_USAGE
"""

import argparse
import sys

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
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="initialize .harness/ at the git repo root")

    args = parser.parse_args(argv)
    if args.command != "init":
        parser.print_usage(sys.stderr)
        return 2

    try:
        result = init_current_repository()
    except RepositoryNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(_render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
