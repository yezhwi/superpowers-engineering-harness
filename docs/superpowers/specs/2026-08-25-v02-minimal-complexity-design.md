# Engineering Harness v0.2 Design

## Scope

Implement two Harness-native P0 capabilities:

1. Minimal Implementation Check: PREVENT unnecessary implementation before coding.
2. Complexity Reviewer: DETECT unnecessary complexity after verification.

No Ponytail runtime dependency, scoring/budget system, repository-wide audit, technical-debt ledger, automatic refactoring, or automatic deletion.

## Architecture

Skills make contextual engineering judgments. Harness CLI validates and persists resulting records; deterministic gate enforces configured policy. No LLM runtime is added to CLI.

New skills:

- `skills/minimal-implementation/SKILL.md`: runs in `PLANNED`, before transition to `IMPLEMENTING`; searches repository and records fixed Decision Ladder result.
- `skills/complexity-reviewer/SKILL.md`: runs after verification and before adversarial review; reads task contract, invariants, Minimal Decision, diff, and relevant call paths.

New CLI commands:

- `harness check minimal --file <yaml>` validates then atomically persists `.harness/evidence/minimal-implementation.yaml`.
- `harness review complexity --file <yaml>` validates complexity review input, atomically writes `CPLX-NNN.yaml` records to `.harness/findings/`, and writes review metadata/evidence.

Workflow guards:

- `PLANNED -> IMPLEMENTING` requires valid minimal-implementation evidence.
- `VERIFYING -> REVIEWING` requires valid complexity-review evidence.

Existing state machine remains unchanged.

## Data model

### Minimal decision

`.harness/evidence/minimal-implementation.yaml` has version, task ID, ordered ladder checks, and decision.

Ladder order:

1. existence
2. reuse
3. stdlib
4. native
5. existing dependency
6. minimum local implementation

Validation requires `existence`; a positive candidate short-circuits later checks as `skipped`; `decision.approach` must agree with ladder result. `unnecessary` is valid only when existence reports unnecessary.

### Complexity findings

Reuse `.harness/findings/`, finding discovery, and gate infrastructure. Extend `finding.schema.json` with a separate `CPLX-NNN` branch:

- `category: complexity`
- `type`: `delete`, `reuse`, `stdlib`, `native`, `yagni`, or `shrink`
- `severity`: `high`, `medium`, or `low`
- `status`: `open`, `resolved`, or `accepted`
- location, summary, reason, evidence, recommendation
- `accepted` requires `acceptance_reason`

Existing `FND-NNN` schema and reproduction lifecycle stay unchanged.

### Complexity review evidence

Review metadata records task identity and diff HEAD/base. Gate policy uses existing `gate.yaml`:

```yaml
complexity:
  required: true
  blocking:
    - high
```

Missing required review metadata blocks gate. Open HIGH complexity findings block. MEDIUM and LOW findings remain non-blocking. Resolved and justified accepted findings do not block.

## Error handling

`check minimal` and `review complexity` reject malformed YAML/schema, invalid task phases, and invalid persistence paths with exit 2. Persist writes atomically. Gate fails closed for invalid minimal/review evidence, malformed complexity findings, or accepted findings missing reason.

## Tests

Tests cover reuse, stdlib, native, YAGNI, shrink, necessary-complexity negative case, short-circuiting, decision drift, HIGH/MEDIUM/accepted gate behavior, transition preconditions, and fail-closed schema validation. Existing finding lifecycle tests protect FND compatibility.

## Dogfood constraints

Use no new dependencies. Add only two Skills, small validation/persistence helpers, schemas, templates, CLI wiring, gate checks, and targeted tests. Run Minimal Check and Complexity Reviewer on v0.2 diff before completion.
