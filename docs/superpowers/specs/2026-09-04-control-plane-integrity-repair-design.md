# Control-plane integrity repair design

## Scope

Repair canonical artifact lifecycle, publication, ownership scope, Gate projection, and CLI failure semantics identified in TASK-051. Reuse existing transaction, schema validation, workspace, and evidence helpers. Do not split modules, add dependencies, or alter trusted-local shell boundary from DEC-004/DEC-008.

## Artifact lifecycle and publication

Interface Finding schema must accept canonical Finding lifecycle states so a Finding can move from `PROPOSED` through existing closure states. Interface review will use same staged publication transaction as diagnosability/complexity. Before allocating a new ID, it will compare canonical identity fields against existing Findings. One publish set contains every newly allocated Finding and `interface-review.json`; failure rolls back every canonical target.

## Scope and review freshness

Ownership mutation normalizes sets: `add-change` and `adopt-path` add owned path and remove it from protected paths. `ignore-user-path` does not remove ownership. `project_task_scope` computes effective owned scope without protected-path subtraction for owned/contract paths. Gate review blockers derive current project task scope and compare it with recorded review scope; post-review ownership or impact changes invalidate required review proof.

## Gate and artifact validation

Finding loading catches YAML parser errors and rejects non-mapping artifacts as `InvalidHarnessState`. Gate/status recompute canonical Findings and assessment instead of treating cached task projection as authority. Gate preserves both `quality` and `release_readiness` for every outcome. Preflight only emits Ready when release readiness is `READY`. Invalid review preflight is mapped to documented CLI failure exit rather than traceback.

## Evidence and identity

Evidence attach validates external result against evidence schema plus current task binding, exit/provenance coherence, and freshness before persistence. Task classification freezes `base_ref`, `base_commit`, and `head_at_start`. Consumers resolve evidence references through one canonical resolver instead of retaining unverified raw path strings.

## Testing

Add regression tests for each repaired failure mode: Interface Finding close/retry/failure injection; ownership command sequences; scope-change stale review; canonical Finding after cached PASS; malformed YAML/preflight exit semantics; dual-axis Ready/blocked projections; invalid evidence attachment; Git identity/reference resolution. Run focused tests during TDD; build and authorized full suite only under Harness verification rules.

## Compatibility and observability

Existing CLI commands retain accepted success behavior. Failure responses become deterministic fail-closed results. No new external production interface or logging obligation; Q3 observability contract records this as non-applicable.
