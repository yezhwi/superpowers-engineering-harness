"""Compatibility wrapper for harness.complexity."""
from harness.complexity import *  # noqa: F401,F403

if __name__ == "__main__" and "main" in globals():
    raise SystemExit(main())
