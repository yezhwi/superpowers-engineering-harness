"""Compatibility wrapper for harness.harness_status."""

from harness.harness_status import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
