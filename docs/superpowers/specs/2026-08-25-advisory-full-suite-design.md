# Advisory Full-Suite Design

## Goal

Make full-suite execution advisory rather than gate-blocking. Allow related-test closure for major and critical findings when structured impact coverage exists; require explicit per-finding user approval for critical related closure.

## Policy

- `impact.full_suite.recommended` remains visible risk metadata. It never blocks `IMPLEMENTING -> VERIFYING`, finding closure, or Gate.
- `--scope full_suite` still requires explicit authorization before execution.
- Major findings close with fresh related evidence covering every `impact.required_tests` entry.
- Critical findings close with either fresh full-suite evidence or fresh related evidence covering every required test plus explicit per-finding approval.
- Related closure rejects empty `impact.required_tests`.

## Interface

```bash
harness finding transition FND-001 VERIFIED \
  --evidence unit-test.json \
  --critical-related-approved
```

The approval flag is valid only for critical findings using related evidence. It persists on the finding:

```yaml
closure:
  mode: related
  critical_related_approved: true
  approved_at: <UTC ISO-8601>
  source: user
```

## Enforcement

One shared closure validator is used by transition and gate. It validates evidence freshness, related coverage, and critical approval. Gate rejects status-only edits or missing/invalid approval metadata.

## Compatibility

No new dependency. State transitions remain unchanged. Full-suite authorization remains available. Existing generic evidence remains valid outside finding closure.

## Tests

Cover advisory impact transition, major related closure, critical related closure rejection without approval, acceptance with approval, empty coverage rejection, and Gate revalidation.
