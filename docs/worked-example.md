# Worked Lifecycle Example

Example requirement: cancelling same order twice must issue at most one refund.

```text
CREATED
  → task-contract
SPECIFYING
  REQ-001: duplicate cancellation issues one refund
  INV-001: refund is idempotent per order ID
PLANNED
  → Minimal Implementation Check records existing lock/idempotency capability or local minimum
IMPLEMENTING
  TDD: test duplicate cancellation RED; minimal idempotency implementation GREEN
VERIFYING
  record impact and run related test as fresh evidence
REVIEWING
  Complexity Reviewer checks changed diff
  Adversarial Review emits FND-001: concurrent cancellation may still double-refund
REPRODUCING
  concurrent regression test RED → FND-001 CONFIRMED
FIXING
  minimal synchronization fix; regression test GREEN
VERIFYING
  fresh related/full authorized evidence
GATING
  harness gate → PASS
CONVERGED
DONE
```

Commands commonly used during this lifecycle:

```bash
harness status
harness check minimal --file minimal-implementation.yaml
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness evidence --type unit_test --command "pytest tests/test_cancel.py::test_duplicate_cancel_single_refund"
harness review complexity --file complexity-review.yaml
harness gate
harness converge
```
