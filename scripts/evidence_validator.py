"""Compatibility wrapper for harness.evidence_validator."""

from harness.evidence_validator import *  # noqa: F401,F403

if __name__ == "__main__" and "main" in globals():
    raise SystemExit(main())
