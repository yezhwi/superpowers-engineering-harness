# Changelog

## 0.2.2

- Add typed Gate blockers and `harness resume` reason-driven recovery.
- Add structured `harness review outcome` routing for pass, verification gaps, and defects.
- Project current Evidence freshness in read-only `harness status`.
- Calculate complexity review scope from task Git baseline, committed, staged, unstaged, and relevant untracked changes.
- Derive recovery target from typed blocker code; add controlled review reason codes and release version consistency coverage.
- Make `harness gate` sole Gate evaluation and convergence authority; deprecate `harness converge`.

## 0.2.1

- Package runtime modules, schemas, and templates inside installed distributions.
- Add wheel-isolation coverage for execution outside source checkout.
- Add audited `harness task recover` for replacing stale active tasks.
