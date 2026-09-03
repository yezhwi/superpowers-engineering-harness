# v0.2.7 Decision Records and Interface-first Contracts Design

## Goal

Add persisted, user-owned engineering decisions and fail-closed external-interface contracts to unreleased v0.2.7. Preserve old Harness projects and avoid forcing abstractions on private implementation details.

## Scope

This design implements P0 and P1 from `docs/Superpowers-Engineering-Harness-v0.2.7-增强需求说明.md`:

- Decision proposal, acceptance, rejection, override, supersession, resume, conflict detection, status, and Gate checks.
- External-interface declaration, consumer and compatibility metadata, Q1 escalation, review input, verification evidence, and Gate checks.
- CLI, schemas, persisted artifacts, Skill, documentation, and regression tests.

No automatic user-decision acceptance, semantic OpenAPI/Protobuf diff engine, universal interface inference, DI framework, or logging-contract duplicate is added.

## Artifact model

`current-task.yaml` remains compact. New artifacts are independent and task-scoped:

```text
.harness/
  decisions/DEC-001.yaml
  interface-contracts/INT-001.yaml
```

Missing directories mean no records. Readers treat absent directories as empty for legacy compatibility.

### Decision

`DecisionRecord` has immutable identity and audit history:

```yaml
id: DEC-001
task_id: TASK-042
status: PROPOSED # PROPOSED | ACCEPTED | REJECTED | SUPERSEDED
topic: api-pagination
question: Which pagination contract should clients use?
context: [repository fact]
options: [{id: cursor, description: Stable cursor pagination}]
recommendation:
  option: cursor
  reasons: [matches existing API convention]
  tradeoffs: [clients retain cursor]
selected: null # populated only when accepted
scope: [src/harness/**]
constraints: [do not add offset pagination]
created_at: ISO-8601
accepted_at: null
supersedes: null
superseded_by: null
```

`accept` validates exactly one option. Default source is `accepted_recommendation` only when selected option equals recommendation; another selection requires explicit `user_override`. `supersede` creates a new record, links both records atomically, and changes old status to `SUPERSEDED`. It never overwrites old selected data.

Active decisions are `ACCEPTED` records without `superseded_by`. Gate blocks remaining `PROPOSED` records and malformed/referentially-invalid records. Impact and interface contracts can reference decision IDs; unknown, rejected, or superseded references block.

### Interface contract

`InterfaceContract` represents stable boundary, not language `interface`:

```yaml
id: INT-001
task_id: TASK-042
status: DECLARED
name: decision-api
kind: cli # http | rpc | event | sdk | plugin | cli | service
visibility: external
consumers: [agent-worker]
inputs: {description: command arguments and validation}
outputs: {description: machine-readable success result}
errors: {description: stable error codes and retryability}
compatibility:
  classification: compatible # compatible | breaking
  rationale: additive commands and artifacts
  migration: null
versioning: {required: false, strategy: null}
observability: {contract: observability.yaml}
decision_refs: []
verification: []
breaking_change_approved: false
created_at: ISO-8601
```

External interface declaration requires nonempty consumers, input/output/error semantics, compatibility classification, and verification references before Gate. `breaking` requires explicit persisted approval. No interface contract is required when no external interface is declared.

## Control-plane commands

Add `harness decision` subcommands:

```text
decision propose --topic --question --option ID=DESCRIPTION --recommend --reason --tradeoff --scope --constraint
decision accept ID --option OPTION [--source accepted-recommendation|user-override]
decision reject ID --reason REASON
decision supersede ID ...new proposal fields...
decision list
decision show ID
```

Add `harness interface` subcommands:

```text
interface declare --name --kind --consumer --input --output --error --compatibility --rationale ...
interface verify ID --evidence EVIDENCE
interface approve-breaking ID --reason REASON
interface list
interface show ID
```

Add contract-bound Interface Review:

```text
harness review interface --file review.yaml [--base REF]
```

Review input declares task, Git binding, inspected interface contract IDs, checks for boundary/DTO/error/dependency/compatibility/test coverage, and proposals. Harness validates and atomically publishes review evidence plus `category: interface` findings through existing Finding lifecycle. A clean review persists review evidence with no proposals.

Both domains validate schemas before publish. Multi-artifact mutations use existing transaction publication. User-facing invalid states return stable codes, not raw schema details.

## Integration

- `impact.yaml` gains `interfaces`. Each entry has ID, kind, visibility, consumers, compatibility, affected contracts, and contract ID.
- `harness impact add-interface` adds a declaration. Q1 declaration fails with `PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED` until user runs explicit Q2/Q3 escalation.
- `harness status` renders only counts and active summaries: accepted/proposed decisions; public-interface count and compatibility.
- Engineering Harness Skill reads active decision summary at Session Startup. Before asking for consequential choice, it presents facts, options, recommendation, reasons, trade-offs, and impact; explicit user response is persisted before continuing.
- `harness review interface --file` consumes declared external contracts. It may publish `INTERFACE` findings through existing finding lifecycle.

## Gate behavior

Gate checks only persisted facts. For active decision records it emits:

```text
DECISION_UNRESOLVED
DECISION_CONFLICT
DECISION_REFERENCE_INVALID
DECISION_SUPERSEDE_INVALID
```

For declared external interfaces it emits:

```text
INTERFACE_CONTRACT_MISSING
INTERFACE_COMPATIBILITY_UNDECLARED
INTERFACE_VERIFICATION_MISSING
INTERFACE_BREAKING_CHANGE_UNAPPROVED
```

All blockers fail closed. Existing task with no decision records and no declared public interface follows unchanged Gate behavior.

## Dependency direction

Domain modules own validation, loading, and mutations:

```text
cli -> controlplane -> decision/interface_contract -> schemas/artifacts
                    -> quality_gate/status (read-only projections)
```

`controlplane.py` remains command router. Avoid generic public interfaces or factories. Contract DTOs describe external boundary only; no persistence entity is exposed as API.

## Test strategy

TDD coverage includes schema validation; propose/accept/override/reject/supersede; invalid supersede; session resume; decision conflict; legacy compatibility; public-interface classification; Q1 escalation; contract and compatibility absence; compatible and unapproved/approved breaking change; stale interface evidence; interface finding lifecycle; private-helper no-ceremony; CLI/status/Skill/docs assertions.

Focused test suites run after each domain task. Final verification uses relevant domain suites and package wheel build; full suite runs only after explicit authorization for TASK-042.
