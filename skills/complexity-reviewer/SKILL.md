---
name: complexity-reviewer
description: Review verified diff for unnecessary implementation complexity before adversarial review.
---

# Complexity Reviewer

Run after verification, before transition `VERIFYING -> REVIEWING`.

Read current task, requirements, invariants, Minimal Decision evidence, `git diff`, changed dependency manifests, and relevant call paths. Review only:

- DELETE
- REUSE
- STDLIB
- NATIVE
- YAGNI
- SHRINK

Do not review correctness, security, performance, test coverage, requirement completeness, general architecture, or style. Necessary complexity required by contract/invariants is not a finding.

Every finding needs concrete evidence, location, reason, and recommendation. Use `CPLX-NNN`, severity `high|medium|low`, and status `open|resolved|accepted`; accepted requires acceptance reason. Record Minimal Decision drift as `reuse`, `stdlib`, or `native`, never new type.

Write review YAML with `task`, current full `head`, `base`, and `findings`, then run:

```bash
harness review complexity --file /path/to/review.yaml
```

HIGH open findings block gate. MEDIUM/LOW are advisory.
