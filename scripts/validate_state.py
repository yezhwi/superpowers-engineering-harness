#!/usr/bin/env python3
"""validate_state.py CURRENT TARGET

Exit codes:
  0 = legal transition
  1 = invalid transition or unknown state
"""

import sys

from state_machine import InvalidTransition, require_legal


def main(argv):
    if len(argv) != 3:
        print("usage: validate_state.py CURRENT TARGET", file=sys.stderr)
        return 1
    current, target = argv[1], argv[2]
    try:
        require_legal(current, target)
    except InvalidTransition as exc:
        print(exc)
        return 1
    print(f"OK: {current} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
