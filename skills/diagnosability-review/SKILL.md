---
name: diagnosability-review
description: Review Q2/Q3 changed business paths for production diagnosability and persist structured review input.
---

# Diagnosability Review

Run only in `REVIEWING`: `harness review diagnosability --file <file>` rejects other task states.

Read `.harness/observability.yaml`, changed files, declared direct dependencies, and existing logging, correlation, masking, exception-handler, and reason-code conventions.

Do not scan whole repository. Do not add code. Do not prescribe logger framework.

For each review, create input for `harness review diagnosability --file <file>` with all checks:

```text
business_keys
external_failure_context
state_transitions
caller_rejections
sensitive_data
duplicate_exception_logging
low_value_logging
```

Use `pass`, `fail`, or `not_applicable`. Every `fail` needs concrete `FND-*` DIAG Finding with linked `REQ-*`, code location, scenario, severity, reason code, and static-compliance required checks.

Never recommend full-object logging, method entry/exit logs, automatic insertion, or generic logging best practice. Claim only reviewed-scope evidence.
